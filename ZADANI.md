# Zadání: Taxfolio – portfolio a daně z investic (CZ/SK)

> Stav: **v1.0 – odsouhlaseno** (architektura a plán v `ARCHITEKTURA.md`) – k diskusi. Místa označená `❓` čekají na rozhodnutí.
> Daňové údaje jsou orientační (stav k 10/2026) a aplikace je musí mít v konfiguraci po jednotlivých letech, ne natvrdo v kódu.

## 1. Cíl

Lokální aplikace, která načte exporty z Interactive Brokers (CSV, příp. XML) a nabídne:

1. **Obchodní deník** – přehled a vyhledávání ve všech obchodech: co, kdy, za kolik, proč (vstupní příkaz, stop-loss, take-profit, …), výsledek uzavřené pozice.
2. **Daňový pohled** – podklady pro daňové přiznání v **ČR** a **SR**: dividendy (celkem, podle zemí, sražená daň), realizované zisky/ztráty, uplatnění osvobození (časový test, limity), výpočet daně a vyplněné hodnoty pro řádky/přílohy přiznání.

Mimo rozsah (v1): automatické podání přiznání a generování XML pro EPO/eDane, napojení na IBKR API v reálném čase, daňové poradenství. Aplikace je kalkulačka podkladů, ne náhrada daňového poradce.

## 2. Vstupní data z IBKR

### 2.1 Doporučený zdroj: Flex Query (Activity Flex Query)
Flex Query umožňuje vybrat sekce a sloupce, exportuje se do CSV/XML a lze ho stahovat i přes Flex Web Service (token + query ID). Aplikace dodá **návod / šablonu, které sekce a pole zapnout**.

| Sekce Flex Query | K čemu je potřeba | Klíčová pole |
|---|---|---|
| **Trades** (úroveň `EXECUTION` + `CLOSED_LOT`) | obchodní deník, párování lotů, časový test | `TradeID`, `IBOrderID`, `OrderType`, `OrderReference`, `OrderTime`, `DateTime`, `Buy/Sell`, `Open/CloseIndicator`, `Notes/Codes`, `Symbol`, `ISIN`, `AssetClass`, `Quantity`, `TradePrice`, `Proceeds`, `IBCommission`, `CostBasis`, `FifoPnlRealized`, `CurrencyPrimary`, `FXRateToBase`, `ListingExchange`, `OpenDateTime` (closed lot), `HoldingPeriodDateTime` |
| **Orders** | rekonstrukce bracket/OCA příkazů (parent → SL/TP) | `IBOrderID`, `OrderType`, `OrderReference`, `ParentID`/OCA skupina (pokud dostupné) |
| **Cash Transactions** | dividendy, srážková daň, úroky, poplatky, vklady/výběry | `Type` (Dividends, Payment In Lieu Of Dividends, Withholding Tax, Broker Interest Received/Paid, Other Fees, Deposits/Withdrawals), `Symbol`, `ISIN`, `Description`, `Amount`, `Currency`, `DateTime`, `SettleDate`, `ActionID` |
| **Corporate Actions** | splity, spin-offy, fúze, změny tickeru → úprava lotů | `Type`, `Description`, `Quantity`, `Proceeds`, `Value`, `DateTime` |
| **Open Positions** | aktuální stav, nerealizovaný P/L, plánování časového testu | `Symbol`, `Quantity`, `CostBasis`, `OpenDateTime` (lot level) |
| **Financial Instrument Information** | země emitenta, typ instrumentu, burza | `ISIN`, `IssuerCountryCode`, `AssetClass`, `SubCategory`, `ListingExchange` |
| **Transfers** (ACATS/FOP) | přenesené pozice z jiného brokera (nákupní cena a datum) | `Symbol`, `Quantity`, `TransferPrice`, `Date` |
| **Option Exercises/Assignments/Expirations** | správné zdanění opcí | `Type`, `Symbol`, `Quantity`, `DateTime` |
| **Conversion Rates** | volitelná kontrola kurzů IBKR | `FromCurrency`, `ToCurrency`, `Rate`, `Date` |

### 2.2 Další podporované vstupy
- **Activity Statement CSV** (standardní výpis z Reports → Statements; vícesekční CSV, kde 1. sloupec je název sekce: *Trades, Dividends, Withholding Tax, Deposits & Withdrawals, Interest, Fees, Corporate Actions, Open Positions, Realized & Unrealized Performance Summary, Financial Instrument Information…*). Slouží jako záloha / pro starší roky.
- **Tax dokumenty** (jen jako kontrola, ne primární zdroj): 1042-S (US srážková daň pro nerezidenty), Dividend Report, Realized Summary / Tax Optimizer (metoda párování lotů na straně IBKR).
- **Kurzy měn**: ČNB (denní kurzy + jednotný kurz GFŘ), ECB/NBS (pro SR) – stahované automaticky a cachované lokálně.

### 2.3 Požadavky na import
- Více souborů, více let, více účtů; **deduplikace** (podle `TradeID`, `TransactionID`/`ActionID`), aby šel stejný rok importovat opakovaně.
- Detekce formátu (Flex CSV / Flex XML / Activity Statement CSV) a validace povinných polí s čitelnou chybou („chybí sloupec OrderType – zapněte ho ve Flex Query“).
- Párování srážkové daně k dividendě (stejné `ActionID`/ISIN + datum), včetně **pozdějších korekcí** (IBKR v únoru reklasifikuje US dividendy a vrací/doráží srážku – korekce se musí přiřadit k původnímu roku/dividendě).
- Historie importů (co, kdy, kolik záznamů) a možnost import vrátit.

## 3. Modul A – Obchodní deník

### 3.1 Datový model (zjednodušeně)
- **Execution** – jednotlivé vyplnění příkazu.
- **Order** – seskupené executions podle `IBOrderID`, s typem příkazu a rolí.
- **Lot** – nakoupené množství s datem a pořizovací cenou (vč. poplatků), mění se splity/corporate actions.
- **Round-trip / Pozice** – otevření → (dokupy, částečné výstupy) → uzavření; agregovaný P/L, doba držení, R-multiple (pokud znám SL).

### 3.2 Důvod obchodu (klasifikace)
Automatická klasifikace s možností ručního přepsání:

| Role | Pravidlo (heuristika) |
|---|---|
| Vstup | `Open/CloseIndicator = O` |
| Stop-loss | uzavírací příkaz typu `STP`, `STP LMT`, `TRAIL`, `TRAIL LIMIT`; nebo child příkaz bracketu se stop cenou |
| Take-profit | uzavírací `LMT` příkaz, který je child bracketu/OCA, nebo cena nad/pod vstupem ve směru zisku |
| Ruční výstup | uzavírací `MKT`/`LMT` bez parent vazby |
| Nucená likvidace | `Notes/Codes` obsahuje `L` (liquidation) |
| Opce | expirace (`Ep`), exercise (`Ex`), assignment (`A`) |
| Corporate action | split, merger, spin-off, delisting |

- Uživatel může vyplňovat `OrderReference` přímo v TWS (např. `SL`, `TP`, `breakout-entry`) – pokud je vyplněn, má přednost před heuristikou.
- Ke každému obchodu lze přidat **vlastní poznámku a štítky** (strategie, setup, chyba…), uložené lokálně – import je nepřepíše.

### 3.3 Funkce
- Tabulka obchodů / pozic s fulltextem a filtry: symbol, ISIN, období, směr (long/short), třída aktiva, důvod výstupu, výsledek (zisk/ztráta), měna, burza, štítky.
- Detail pozice: časová osa executions, průměrná cena, poplatky, P/L v měně obchodu i v CZK/EUR, doba držení.
- Statistiky: win rate, průměrný zisk/ztráta, profit factor, P/L podle důvodu výstupu (kolik vydělaly TP vs. kolik stály SL), podle symbolu, měsíce, strategie.
- Přehled peněžních toků: vklady, výběry, konverze měn, poplatky, úroky.
- Export filtrovaného výběru do CSV/XLSX.

## 4. Modul B – Daňový pohled

### 4.1 Společné přehledy (pro vybraný rok a zemi rezidence)
- **Dividendy**: hrubá částka, sražená daň, čistá částka – celkem, **podle země zdroje** (z `IssuerCountryCode`/ISIN), podle titulu, po měsících; v originální měně i přepočtené.
- **Realizované zisky** a **realizované ztráty** zvlášť (ne jen saldo), po titulech a po obchodech; rozlišení *osvobozeno / zdanitelné*.
- **Úroky** a ostatní kapitálové příjmy (payment in lieu of dividends, securities lending).
- **Poplatky** – které lze uplatnit jako výdaj (poplatky za obchod – ano, součást pořizovací ceny / snížení příjmu; poplatky za data – ❓ ověřit).
- **Otevřené pozice a časový test** – kdy který lot splní časový test (kalendář „od kdy prodat bez daně“) a nerealizovaný zisk/ztráta.
- **Simulace / optimalizace** – „co když prodám X ks dnes“: daňový dopad, využití limitu osvobození, započtení ztráty proti zisku v témže roce (tax-loss harvesting), čekání na časový test.

### 4.2 Párování lotů
- Výchozí metoda **FIFO** (vyžadováno v ČR pro časový test u stejného CP; v SR obvyklá). Konfigurovatelné pro případné jiné metody, pokud to legislativa dané země připouští.
- Párování počítá aplikace sama (nezávisle na nastavení Tax Optimizeru v IBKR) – výsledek IBKR `FifoPnlRealized` slouží jen ke kontrole a odchylky se zobrazí.

### 4.3 Přepočet měn
- **ČR**: volba pro celý rok – **jednotný kurz** (pokyn GFŘ, roční) **nebo denní kurz ČNB** ke dni transakce (§ 38 ZDP); volba musí být konzistentní pro celé zdaňovací období.
- **SR**: referenční kurz **ECB/NBS** ke dni uskutočnění transakce / připsání příjmu (❓ ověřit přípustné alternativy dle § 31 ZDP SR).
- Nákup i prodej se přepočítávají každý svým kurzem (ne zisk v USD × kurz).

### 4.4 Pravidla – Česká republika (ZDP č. 586/1992 Sb.)

| Oblast | Pravidlo (ověřit pro každý rok) |
|---|---|
| Prodej CP – zařazení | § 10 (ostatní příjmy), sazba 15 % / 23 % nad 36násobek průměrné mzdy (pro 2025 hranice 1 676 052 Kč) |
| Osvobození – časový test | držba **> 3 roky** u akcií/ETF/CP (FIFO, každý lot zvlášť) |
| Strop časového testu | **2025: 40 mil. Kč** (příjmy nad limit zdanitelné). **Od 1. 1. 2026 strop pro CP a podíly zrušen** (pro kryptoaktiva zůstává) |
| Osvobození – limit příjmů | úhrn **hrubých příjmů** z prodeje CP za rok **≤ 100 000 Kč** → osvobozeno vše (počítají se i prodeje osvobozené časovým testem? ❓ ověřit) |
| Ztráty | ztráty z prodeje CP lze v rámci § 10 započíst jen proti ziskům ze stejného druhu příjmů v témže roce; celková ztráta = 0, nepřevádí se do dalších let, nesnižuje jiné příjmy |
| Opce, deriváty | § 10, bez časového testu (❓ potvrdit pro jednotlivé typy) |
| Zahraniční dividendy | § 8, sazba 15 %; zahrnout **hrubou** částku; zápočet zahraniční daně metodou prostého zápočtu (§ 38f) max. do výše české daně, typicky max. 15 % (USA s W‑8BEN 15 %); nadlimitní srážka (např. DE 26,375 %) je ztracená → aplikace upozorní na možnost vratky v zemi zdroje |
| Možnost samostatného základu | zahraniční dividendy lze zdanit v samostatném základu daně § 16a (15 %, bez vlivu na progresi) |
| CZ dividendy | srážková daň 15 % u zdroje, do DAP nevstupují |
| Úroky z účtu u IBKR | § 8, zahraniční příjem → DAP |
| Oznamovací povinnost | osvobozené příjmy nad **5 mil. Kč** je nutné oznámit (§ 38v) – aplikace upozorní |
| Výstupy | hodnoty pro **Přílohu č. 2** (ostatní příjmy § 10), ř. 38 (§ 8), **Přílohu č. 3** (zápočet daně ze zahraničí – po státech), samostatný list § 16a |
| Zdravotní/sociální | z kapitálových příjmů a § 10 u nepodnikatele se neplatí |

### 4.5 Pravidla – Slovenská republika (ZDP č. 595/2003 Z. z.)

| Oblast | Pravidlo (ověřit pro každý rok) |
|---|---|
| Prodej CP – zařazení | § 8 (ostatné príjmy), sazba 19 % / 25 % nad hranici 176,8násobku životného minima |
| Osvobození – časový test | držba **> 1 rok** a CP **přijaté na regulovaný trh** (i zahraniční), od přijetí k obchodování > 1 rok; ne pro CP v obchodním majetku |
| Osvobození 500 € | pokud úhrn příjmů z prodeje CP **snížený o výdaje** ≤ 500 € ročně → osvobozeno; jinak se zdaňuje jen část nad 500 €; limit je **společný s jinými § 8 příjmy (např. nájom)** – aplikace musí umožnit zadat, zda už limit čerpáte jinde |
| Ztráty | ztráta z prodeje CP se nezohledňuje (nelze ji odečíst od jiných příjmů); v rámci roku se zisky a ztráty z CP vzájemně kompenzují (❓ potvrdit) |
| Zdravotní odvody | ze zdanitelných kapitálových zisků (§ 8) se platí **zdravotné poistenie** (2025: 16 % ❓ ověřit) – aplikace spočítá orientačně |
| Zahraniční dividendy | osobitný základ dane; sazba dle roku, **za který byl zisk vykázán**: 7 % (zisky 2017–2023, 2025+), 10 % (zisk 2024); **35 %** ze nezmluvných/nespolupracujících států; zápočet dane zaplacené v zahraničí (zmluvné štáty) |
| SK dividendy | srážková daň u zdroje |
| Výstupy | hodnoty pro **DP typ B** – VI. oddiel (§ 8), příloha k osobitnému základu dane (dividendy), výpočet zápočtu |

> Pozn.: Aplikace nemá z IBKR dat informaci, za jaký rok byl zisk, ze kterého je dividenda vyplacena (SK 7 % vs 10 %). Návrh: výchozí pravidlo podle data výplaty + ruční přepsání u jednotlivé dividendy.

### 4.6 Výstupy daňového modulu
- Souhrnná stránka „co napsat do přiznání“ (pro ČR / SR) s odkazem na řádek/přílohu.
- Detailní **příloha s výpočtem** (PDF/XLSX): seznam prodejů s nákupními loty, daty, kurzy, osvobozením a důvodem; seznam dividend se srážkovou daní a kurzy – pro případnou kontrolu správcem daně.
- Upozornění: chybějící nákupní data (přenesené pozice), nespárované srážky, korekce dividend, pozice s neznámou zemí emitenta, překročení limitů.

## 5. Nefunkční požadavky
- **Lokální běh, data neopouští počítač** (finanční údaje). Žádné cloudové úložiště v1.
- Daňová pravidla jako **verzovaná konfigurace po letech a zemích** (YAML/JSON), ne natvrdo v kódu; každé pravidlo s odkazem na zdroj.
- Přesná aritmetika (`Decimal`), zaokrouhlování dle pravidel přiznání.
- Testy výpočtů na referenčních příkladech (ručně spočítané případy).
- Jazyk UI: čeština (slovenština ❓).

## 6. Rozhodnutí

| # | Téma | Rozhodnutí |
|---|---|---|
| D1 | Forma | **Desktop aplikace**, lokální data (SQLite). |
| D2 | Instrumenty v1 | **Akcie, ETF, forex (konverze měn), dluhopisy.** Opce/futures/CFD mimo rozsah v1 (import je zaznamená, ale označí jako „nepodporováno“). |
| D3 | Rezidence | **ČR i SR, přepínatelně** – rezidence se nastavuje po letech (lze změnit v průběhu historie); stejná data lze vyhodnotit pro obě země. |
| D4 | SL/TP | **Kombinace** – heuristika podle typu příkazu + bracket/OCA vazeb + `OrderReference`, vždy s možností ručního přeznačení v aplikaci. |
| D5 | Výstupy pro přiznání | **Pouze hodnoty k řádkům/přílohám přiznání** (+ detailní příloha s výpočtem). Generování XML pro EPO / eDane mimo rozsah. |
| D6 | Platformy | **Linux, Windows i macOS** – jeden kód, nativní balíčky pro každou platformu. |
| D7 | Účty a měny | Aktuálně **1 účet IBKR (U13672605), bázová měna EUR** (dle exportů; uživatel původně uváděl USD). Aplikace musí podporovat **více účtů** (přidání dalšího účtu, filtr / součet přes účty) a **přepínání zobrazovací měny** (USD / CZK / EUR / měna obchodu). Daňové výpočty vždy v měně státu rezidence (CZK pro ČR, EUR pro SR) bez ohledu na zobrazovací měnu. |
| D8 | Import | **Ruční nahrání souborů i stažení přes Flex Web Service**. Token a Query ID se ukládají do systémové klíčenky (Keychain / Credential Manager / Secret Service), ne do konfiguračního souboru. Stahování po úsecích max. 365 dní (limit Flex Query), s deduplikací. |
| D9 | Historie a výběr roku | Data **od roku 2024**. Uživatel volí **zdaňovací rok**, pro který se zpracovávají přehledy a daň. Párování lotů se ale vždy počítá z celé dostupné historie (nákup z roku 2024 prodaný v roce 2026). Pokud prodej nemá dohledatelný nákup v importovaných datech (pozice otevřená před 2024 nebo převedená), použije se `OpenDateTime` + `CostBasis` z closed-lot záznamu IBKR, případně ruční doplnění – a aplikace to zvýrazní. |
| D10 | SR dividendy | Výchozí pravidlo **rok zisku = rok výplaty − 1** → sazba dle roku zisku (2017–2023: 7 %, 2024: 10 %, 2025+: 7 %; nespolupracující státy 35 %). Tedy výplata v 2025 → 10 %, výplata v 2026 → 7 %. U konkrétní dividendy lze rok zisku / sazbu **ručně přepsat**. |
| D11 | Technologie | **Python + PySide6 (Qt)**, SQLite, `Decimal`; detail v `ARCHITEKTURA.md`. |
| D12 | Historie pozic | Žádné převedené pozice ani nákupy před 2024 → všechny loty lze dohledat v importovaných datech. Ruční doplnění lotu zůstává jako záložní funkce (pro budoucí účty), nemá prioritu. |

### 6.1 Doplnění rozsahu z rozhodnutí D2
- **Dluhopisy**: nákup/prodej (vč. naběhlého úroku – AÚV placený při nákupu / přijatý při prodeji), kupóny, splacení jistiny při splatnosti.
  - ČR: kupóny ze zahraničí § 8; prodej/splacení § 10 s 3letým časovým testem a limitem 100 000 Kč (❓ ověřit zacházení s AÚV a se splacením).
  - SR: úroky/kupóny – osobitný základ / § 7 (❓ ověřit sazbu 19 %), prodej § 8 vč. pravidla 1 rok + regulovaný trh (❓ ověřit pro dluhopisy).
- **Forex**: přehled konverzí, kurzových zisků/ztrát z držby cizí měny.
  - ČR: ❓ ověřit, zda kurzové rozdíly ze zůstatku na účtu u nepodnikatele podléhají dani a zda platí osvobození (limit/časový test pro cizí měnu).
  - SR: ❓ ověřit.
  - Do vyjasnění: forex v daňovém modulu **jen informativně** (bez započtení do základu daně), v deníku plně.

## 7. Otevřené otázky ❓
Žádné otevřené produktové otázky. Zbývá **ověření daňových bodů označených ❓** (forex, dluhopisy, SR zdravotní odvody, 100k limit vs. časový test) – proběhne v milníku M4/M5 (viz `ARCHITEKTURA.md`).

### 7.1 Stav ověření daňových bodů (M4)
| Bod | Stav |
|---|---|
| Jednotný kurz = průměr kurzů ČNB k poslednímu dni měsíce | ✅ ověřeno (2024 EUR 25,16 / USD 23,28; 2025 EUR 24,66 / USD 21,84) |
| Strop 40 mil. Kč pro CP | ✅ 2025 platí, od 2026 zrušen |
| Limit 100 000 Kč – hrubé příjmy, ne zisk | ✅ |
| Započítávají se do limitu 100 000 Kč i prodeje osvobozené časovým testem? | ❓ zdroje nejednotné – přepínač v pravidlech, výchozí „ano“ (opatrnější) |
| Tuzemské dividendy přes zahraničního brokera sražené 35 % | ❓ do DAP nevstupují; vrácení rozdílu konzultovat s poradcem |
| Hranice 23 % pro 2026 (1 762 812 Kč) | ❓ ověřit |
| Čísla řádků Přílohy 3 | ❓ ověřit dle aktuálního tiskopisu (aplikace uvádí jen popisy) |
| SR: 1 rok + regulovaný trh, 500 € z (príjmy − výdavky), strata sa neuznáva, oslobodené sa nezapočítavajú | ✅ Finančná správa |
| SR: sadzby dividend 7 % / 10 % podľa roku zisku, zápočet do zmluvnej sadzby | ✅ Finančná správa |
| SR: pásma 2026 (19/25/30/35 %) – vzťahujú sa aj na § 8? | ❓ |
| SR: zdravotné poistenie z § 8 (14 % 2024, 16 % 2025+) | ❓ overiť u poisťovne |
| SR: kurz ECB – deň transakcie vs. predchádzajúci deň | ❓ nastavenie `fx.rate_day` |
| SR: 500 € – spoločné s inými § 8 príjmami | ❓ prepínač v UI |

## 8. Zdroje (k ověření při implementaci)
- IBKR – Flex Queries / Activity Statements (Client Portal → Performance & Reports)
- ČR: [e15 – zdanění akcií a dividend 2026](https://www.e15.cz/zdaneni-akcii-dividend-danove-priznani-2026), [Pohoda – změny osvobození od 2026](https://portal.pohoda.cz/dane-ucetnictvi-mzdy/dan-z-prijmu/zmeny-v-osvobozeni-prijmu-z-prodeje-cennych-papiru-a-obchodnich-podilu-od-roku-2026/), [ARROWS – zrušení limitu 40 mil.](https://arws.cz/en/news-at-arrows/czech-full-tax-2026-exemption-on-share-sales-after-czk-40m-cap-ends)
- SR: [Finančná správa – príjmy FO z predaja CP](https://podpora.financnasprava.sk/575795-Pr%C3%ADjmy-fyzickej-osoby-z-predaja-cenn%C3%BDch-papierov), [Finančná správa – dividendy zo zahraničia](https://podpora.financnasprava.sk/830591-Pr%C3%ADjem-charakteru-dividend-podielov-na-zisku-zo-zahrani%C4%8Dia), [Poradca – sadzby dane z dividend 2025](https://www.poradca.sk/novinky/sadzby-dane-pre-dividendy-vyplatene-fo-a-po-v-roku-2025/14)
