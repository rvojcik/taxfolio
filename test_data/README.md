# Testovací data – fiktivní portfolio 2021–2025

Smyšlený účet **U9999001** („Testovaci Ucet“, bázová měna CZK) s výpisy IBKR Flex Query po letech.
Slouží k ověření, že aplikace správně počítá daně v ČR a SR v různých situacích. Všechny firmy,
ISINy a ceny jsou vymyšlené.

| Soubor | Obsah |
|---|---|
| `flex_2021.xml` … `flex_2025.xml` | účet IBKR **U9999001** (CZK): výpisy Flex Query (formát jako `taxfolio_full`), jeden na rok, včetně otevřených pozic ke konci roku; `flex_2023.xml` je rok bez obchodů |
| `xtb_51234567_cash_operations.csv` | druhý účet **XTB 51234567** (EUR, 2023–2025): peněžní operace v novějším formátu XTB (`;`, desetinná čárka) |
| `expected_cz.json` | očekávané výsledky v ČR pro prodeje v CZK, spočtené generátorem **nezávisle na aplikaci** (vlastní FIFO) |
| `generate.py` | generátor (deterministický – opakované spuštění dá stejné soubory) |

```bash
uv run python test_data/generate.py               # znovu vygenerovat
uv run pytest tests/test_scenarios.py             # automatické ověření scénářů
```

**Nepouštějte je do své skutečné databáze.** Pro ruční vyzkoušení použijte samostatnou:

```bash
taxfolio --db /tmp/test-dane.sqlite import test_data/flex_*.xml test_data/xtb_*.csv
taxfolio --db /tmp/test-dane.sqlite tax-cz 2025
taxfolio --db /tmp/test-dane.sqlite tax-sk 2025
XDG_DATA_HOME=/tmp/test-dane taxfolio-gui         # aplikace s vlastní prázdnou databází (Linux), pak Import
```

Proč 2021–2025 a ne tři roky: český časový test vyžaduje držbu **déle než 3 roky** – v rámci tří
po sobě jdoucích let ho žádný nákup splnit nemůže. Proto jsou nákupy v letech 2021 a 2022 a hlavní
prodeje v roce 2025 (rok 2023 je bez obchodů). Daňová pravidla má aplikace pro roky 2021–2026.

Všechny akcie v CZK se obchodují na pražské burze (`PRA`, regulovaný trh). Poplatek za obchod je 50 Kč
(u USD akcií 1 USD).

## Scénáře

### Hlavní scénář (zadání)

| Id | Kdy | Co | Účel |
|---|---|---|---|
| **S1** | 2021 | vklad **100 000 Kč**; 10 nákupů 10 firem (ALFA … JASM), každý 50 ks × 180 Kč | nákupy s budoucím splněním časového testu |
| **S2** | 2022 | vklad **200 000 Kč**; 20 nákupů 20 jiných firem (KAMN … ILKA), každý 100 ks × 90 Kč; HUSA, ILKA, GOLF až v říjnu–prosinci | nákupy, které v roce 2025 časový test nesplní |
| **S3** | 2025 | prodej **5 firem**: 2 splní časový test, 3 ne (2 se ziskem, 1 se ztrátou) | osvobození vs. zdanění |

S3 podrobně (ČR, Kč):

| Firma | Nákup | Prodej | Příjem | Výdaj | Výsledek | ČR časový test | SR (1 rok + reg. trh) |
|---|---|---|---|---|---|---|---|
| CEDR | 15. 4. 2021 | 10. 4. 2025 | 20 000 | 9 100 | +10 900 | ✔ osvobozeno | osvobozeno |
| DUNA | 15. 5. 2021 | 12. 5. 2025 | 15 000 | 9 100 | +5 900 | ✔ osvobozeno | osvobozeno |
| HUSA | 12. 10. 2022 | 14. 3. 2025 | 40 000 | 9 100 | +30 900 | ✘ zdanitelné | osvobozeno |
| ILKA | 15. 11. 2022 | 16. 6. 2025 | 25 000 | 9 100 | +15 900 | ✘ zdanitelné | osvobozeno |
| GOLF | 7. 12. 2022 | 15. 7. 2025 | 5 000 | 9 100 | −4 100 | ✘ zdanitelné (ztráta snižuje zisky) | osvobozeno |

Výdaj = pořizovací cena 9 000 Kč + poplatek za nákup 50 Kč + poplatek za prodej 50 Kč.

### Doplňkové scénáře

| Id | Obchody | Co se ověřuje |
|---|---|---|
| **E1** | nákup ALFA 2× (2021: 50 ks × 180, 1. 12. 2022: 50 ks × 200); 20. 8. 2025 prodej **75 ks** × 220 | **FIFO přes dva loty**: 50 ks z 2021 (osvobozeno, +1 916,67 Kč) a 25 ks z 2022 (zdanitelné, +458,33 Kč); poplatky poměrně |
| **E2** | GAMR (USA, NASDAQ, **USD**): nákup 15. 9. 2022 10 ks × 50, prodej 20. 3. 2025 × 80 | **přepočet měny** kurzem ČNB ke dni nákupu a prodeje (příjem 800 USD, výdaj 501 + 1 USD) |
| **E3** | ZETM (USA, **OTC/PINK**, USD): nákup 16. 5. 2022 1 000 ks × 2, prodej 22. 4. 2025 × 5 | ČR: zdanitelné (< 3 roky); **SR: zdanitelné i po roce**, protože nejde o regulovaný trh (upozornění) |
| **E4** | EPSI: nákup 3. 2. 2025 100 ks × 100, prodej 15. 9. 2025 × 160 | **krátkodobý obchod** v rámci roku: zdanitelné v ČR i SR (+5 900 Kč) |
| **E5** | DLCH (Německo, **EUR**): nákup 20. 4. 2022 20 ks × 80 | zdroj německé dividendy (E7) |
| **E6** | 3. 6. 2024 prodej KAMN 100 ks × 150 (nákup 2022, < 3 roky, zisk 5 900 Kč) | **limit 100 000 Kč**: příjmy z prodejů v roce ≤ 100 000 Kč → osvobozeno i bez časového testu; SR osvobozeno (> 1 rok) |
| **E7** | dividendy 2025: BRIZ (CZ) 1 000 Kč, sraženo **35 %**; GAMR (US) 20 USD, sraženo **15 %**; DLCH (DE) 100 EUR, sraženo **26,375 %** | ČR: tuzemská dividenda mimo přiznání + upozornění na 35 %; US zápočet v plné výši; DE zápočet jen 15 % + upozornění na nárok na vrácení. SR: všechny tři zahraniční, sazba podle roku zisku (2024 → 10 %) |

Rok 2023 je bez obchodů (prázdný výpis) – ověřuje, že prázdné období nic nerozbije.

### Druhý účet – XTB (EUR)

Ověřuje **více účtů najednou**: přepínač účtů, součty v Přehledu a hlavně to, že se daň počítá za
osobu, ne za účet. Částky jsou v EUR (měna účtu XTB, včetně poplatku za konverzi).

| Id | Operace | Co se ověřuje |
|---|---|---|
| **X1** | vklad 5 000 € (1. 3. 2023), **výběr 500 €** (1. 7. 2025) | graf vkladů a výběrů, čisté vklady za oba účty (IBKR v CZK + XTB v EUR) |
| **X2** | SAP.DE: nákup 2. 3. 2023 10 ks za 1 200 €, prodej 10. 9. 2024 5 ks za 900 € | **částečný prodej** (FIFO poloviny pozice, zisk 300 €); ČR 2024: limit 100 000 Kč se počítá **za oba účty** (IBKR 15 000 Kč + XTB 900 €) → stále osvobozeno |
| **X3** | MSFT.US: nákup 2. 3. 2023 za 1 170 €, prodej 5. 3. 2025 za 1 850 €, **poplatek 3,70 €** | poplatek připojený k prodeji (zisk 676,30 €); ČR zdanitelné (< 3 roky); SR osvobozeno (> 1 rok, burza XTB:US) |
| **X4** | dividendy 2024: SAP.DE 22 € (sraženo 26,375 %), MSFT.US 3,40 € (sraženo 15 %) | párování dividendy a srážky podle symbolu a času; stát podle přípony symbolu |
| **X5** | CEZ.CZ: nákup 10. 1. 2025 za 800 €, prodej 10. 6. 2025 za 880 € | krátkodobý obchod: zdanitelné v ČR i SR (+80 €) |
| **X6** | IUSA.DE (irské ETF na německé burze): nákup 2023, dividenda 7,50 € bez srážky | XTB neuvádí ISIN → stát odhadnut jako **DE** (ve skutečnosti IE); import na to upozorní. Protože se zápočet počítá za stát, srážka SAP (DE) pokryje i tuto dividendu – při ručním opravení státu na IE by vznikla daň 15 % |
| **X7** | úrok z volných prostředků 4,20 € a jeho daň 0,80 € | úroky se načtou, nezdaňují se jako dividenda |
| **X8** | Profit/Loss (FX/CFD) 12,50 € | CFD se přeskočí s upozorněním |

## Očekávané výsledky

Kontrolováno ručně proti výstupu aplikace 30. 10. 2026 (kurzy ČNB / ECB staženy aplikací).

### Česká republika

**2024** – jediný prodej (E6), příjmy 15 000 Kč ≤ 100 000 Kč → **vše osvobozeno**, základ 0, daň 0.

**2025** – úhrn příjmů z prodejů > 100 000 Kč, limit neplatí.

| Položka | Kč | Jak |
|---|---|---|
| Osvobozeno časovým testem | 46 000,00 | CEDR 20 000 + DUNA 15 000 + ALFA (50 ks) 11 000 |
| Zdanitelné příjmy (Příloha 2) | 219 210,60 | CZK 91 500 (HUSA, ILKA, GOLF, ALFA 25 ks, EPSI) + USD 800 × 23,082 + 5 000 × 21,849 |
| Zdanitelné výdaje (Příloha 2) | 102 223,85 | CZK 42 441,67 + USD 501 × 24,542 + 2 001 × 23,709 + poplatky za prodej 1 × 23,082 + 1 × 21,849 |
| **Dílčí základ § 10 (ř. 40)** | **116 986,75** | |
| Zahraniční dividendy (ř. 38) | 2 920,54 | DE 100 EUR × 24,93 = 2 493,00; US 20 USD = 427,54 |
| Zápočet daně (Příloha 3) | 438,08 | DE jen 15 % = 373,95 (sraženo 657,65); US 64,13 (celá srážka) |
| **Odhad daně 15 %** | **17 548,01** | (116 986,75 + 2 920,54) × 15 % − 438,08 |
| Upozornění | | tuzemská dividenda sražena 35 % (rozdíl 200 Kč); DE 283,70 Kč lze žádat zpět v Německu |

Část v CZK (bez kurzů) je i v `expected_cz.json`: zdanitelné příjmy 91 500, výdaje 42 441,67, výsledek 49 058,33 Kč.

### Slovenská republika

**2024** – E6 držen > 1 rok, regulovaný trh → osvobozeno, daň 0.

**2025** – zdanitelné jen **ZETM** (OTC, ne regulovaný trh) a **EPSI** (< 1 rok); vše ostatní osvobozeno.

| Položka | € |
|---|---|
| Příjmy | 5 014,62 |
| Výdaje | 2 320,86 |
| Osvobození § 9 ods. 1 písm. i) | 500,00 |
| **Dílčí základ § 8** | **2 193,76** |
| Daň 19 % | 416,82 |
| Dividendy (zvláštní základ, zisk 2024 → 10 %) | DE 100,00 / CZ 40,13 / US 17,25 – daň 10 % plně kryta zápočtem |
| Zdravotní pojištění (odhad 16 %) | 351,00 |

Kurzy se mění jen u skutečných dat ČNB/ECB; automatický test (`tests/test_scenarios.py`) běží
s pevnými kurzy (1 USD = 22 Kč, 1 EUR = 24,2 Kč = 1,1 USD), aby měl přesné očekávané hodnoty
i pro USD a EUR scénáře.

### Oba účty dohromady (výběr „Všechny účty“)

| | ČR 2024 | ČR 2025 | SR 2025 |
|---|---|---|---|
| Úhrn příjmů z prodejů | 37 549,50 Kč (≤ 100 000 → osvobozeno) | 333 424,25 Kč | – |
| Základ | 0 | **137 558,14 Kč** = 116 986,75 (IBKR) + 18 836,99 (MSFT) + 1 734,40 (CEZ) | **2 273,76 €** = 2 193,76 + 80 (CEZ) – jedno osvobození 500 € pro oba účty |
| Odhad daně | 0 | **20 633,72 Kč** | **432,02 €** |

**Jen účet XTB:** ČR 2025 má úhrn 68 213,65 Kč < 100 000 Kč a ukazoval by osvobození limitem – **to je
chybně**, limit platí za osobu. Aplikace proto při výběru jednoho účtu (a existenci dalších) zobrazí
upozornění, že limity a daň platí jen pro „Všechny účty“.

### Přehled

- „Všechny roky“: časová osa grafů začíná první aktivitou (vklad / nákup) – Q1/21, ne až prvním prodejem.
- Graf **Vklady a výběry**: Q1/21 100 000 Kč, Q1/22 200 000 Kč, Q1/23 vklad XTB, Q3/25 výběr XTB (záporný).
- Hodnota portfolia z otevřených pozic ke konci roku (ceny rostou o 12 % ročně od prvního nákupu).
- Účet XTB samotný (měna EUR): vklady 5 000 €, výběry −500 €; dividendy podle společnosti s názvy
  z exportu XTB (bez ISIN).

## Co scénáře zatím nepokrývají

- Rozdělení akcií (split) a jiné korporátní akce.
- Prodej nakrátko, opce, dluhopisy, forex.
- Časový test přes přestupný den (29. 2.) a prodej přesně v den výročí.
- Starší formát XTB (`ID;Type;Time;Symbol;Comment;Amount`) a výpis XTB v Excelu – pokrývá `tests/test_xtb.py`.
- Nejasnost, zda se do limitu 100 000 Kč počítají i příjmy osvobozené časovým testem
  (`limit_includes_time_tested` v pravidlech) – v roce 2025 jsou zdanitelné příjmy nad limitem v obou variantách.
