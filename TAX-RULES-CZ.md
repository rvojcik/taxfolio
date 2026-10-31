# Česká daňová pravidla 2021–2026 – přehled, zdroje a kontrola

Popis pravidel v souborech `2021.yaml` … `2026.yaml` v této složce: co aplikace počítá, podle čeho a
nakolik je to ověřené.

**Poslední kontrola:** 31. 10. 2026 – porovnání pravidel s veřejnými zdroji: znění zákona
č. 586/1992 Sb. na zakonyprolidi.cz (verze 157, účinná od 1. 8. 2026), pokyny GFŘ a odborné
články. Jednotné kurzy byly přepočítány aplikací a porovnány s pokyny GFŘ.

Aplikace je kalkulačka podkladů, ne daňové poradenství. Před podáním přiznání ověřte aktuální
znění zákona a tiskopisu DAP FO.

## Výsledek kontroly v kostce

| Oblast | Stav |
|---|---|
| Sazby 15 % / 23 % a hranice 2021–2026 | ✓ sedí |
| Časový test 3 roky | ✓ sedí |
| Limit 100 000 Kč | ✓ sedí (zákon není jednoznačný, aplikace volí opatrnější výklad) |
| Strop 40 mil. Kč (jen 2025) | ✓ sedí, aplikace jen upozorní |
| Ztráty | ✓ sedí |
| Dividendy, samostatný základ § 16a, zápočet daně | ✓ sedí |
| Jednotné kurzy 2021–2025 | ✓ sedí na haléř s pokyny GFŘ |
| Oznámení osvobozených příjmů (§ 38v) | ≈ aplikace upozorní opatrněji, než zákon vyžaduje |
| Tuzemské dividendy sražené 35 % | ❓ postup vrácení rozdílu neověřen |

**Chyby v hodnotách pravidel: žádné.** Jen drobnosti v dokumentaci, viz
[Drobnosti k úpravě](#drobnosti-k-úpravě).

## Pravidla

### 1. Sazby daně z příjmů (§ 16)

15 % ze základu daně do hranice, 23 % z části nad hranicí. Hranice platí pro **celkový** základ daně
včetně mzdy, zisku z prodeje CP (§ 10) a dividend v obecném základu (§ 8).

| Rok | Hranice pro 23 % | Výpočet | Kontrola |
|---|---|---|---|
| 2021 | 1 701 168 Kč | 48 × průměrná mzda 35 441 Kč | ✓ |
| 2022 | 1 867 728 Kč | 48 × 38 911 Kč | ✓ |
| 2023 | 1 935 552 Kč | 48 × 40 324 Kč | ✓ |
| 2024 | 1 582 812 Kč | **36** × 43 967 Kč (od 2024 36násobek místo 48násobku) | ✓ |
| 2025 | 1 676 052 Kč | 36 × 46 557 Kč | ✓ |
| 2026 | 1 762 812 Kč | 36 × 48 967 Kč (nařízení vlády č. 365/2025 Sb.) | ✓ – poznámku ❓ v `2026.yaml` lze odstranit |

Aplikace zná jen příjmy z investic. Ukazuje proto dva odhady: 15 % a 23 % (jako by celý základ byl
nad hranicí, např. kvůli vysoké mzdě).

### 2. Osvobození – časový test 3 roky (§ 4 odst. 1 písm. u)

Příjem z prodeje CP je osvobozen, **přesáhne-li doba mezi nabytím a prodejem 3 roky**. Neplatí to
pro CP v obchodním majetku do 3 let od jeho vyřazení.

- Test se posuzuje u **každého nákupu (lotu) zvlášť**; prodej se páruje metodou FIFO.
- U zděděných CP se započítává i doba držby zůstavitele (příbuzný v řadě přímé nebo manžel).
- Výměna akcií nebo fúze podle § 23b/23c dobu nepřerušuje.
- Platí beze změny po celé období 2014–2026.

| Rok | V pravidlech | Kontrola |
|---|---|---|
| 2021–2026 | `time_test_years: 3`, osvobozeno od dne po 3. výročí | ✓ |

Starší pokyny GFŘ (např. D-59) uvádějí časový test pod písm. x) a limit pod písm. w); v současném
znění je to písm. u) a t). Aplikace cituje současné znění.

### 3. Osvobození – limit 100 000 Kč (§ 4 odst. 1 písm. t)

Osvobozeny jsou příjmy z prodeje CP, **pokud jejich úhrn nepřesáhne ve zdaňovacím období
100 000 Kč**.

- Posuzuje se **příjem** (prodejní cena), ne zisk.
- Překročí-li úhrn limit, neosvobodí se ani část pod limitem; pak rozhoduje časový test u
  jednotlivých prodejů.
- **Započítávají se do úhrnu i prodeje splňující časový test?** Zákon to výslovně neříká.
  Zdroje se shodují, že osvobození **nelze kombinovat**: prodeje po časovém testu nelze odečíst,
  aby se úhrn vešel pod limit. Aplikace je proto ve výchozím stavu započítává
  (`limit_includes_time_tested: true`, opatrnější výklad); v pravidlech lze výklad přepnout.

| Rok | V pravidlech | Kontrola |
|---|---|---|
| 2021–2026 | `gross_income_limit: 100000`, `limit_includes_time_tested: true` | ✓ |

### 4. Strop 40 mil. Kč pro osvobození časovým testem (§ 4 odst. 3)

| Rok | Pravidlo | V pravidlech | Kontrola |
|---|---|---|---|
| 2021–2024 | strop neexistuje | `time_test_cap: null` | ✓ |
| 2025 | osvobozeno jen do 40 mil. Kč příjmů ročně (CP, podíly, kryptoaktiva) | `time_test_cap: 40000000` | ✓ |
| 2026 | strop pro CP a podíly zrušen, zůstává jen pro kryptoaktiva | `time_test_cap: null` | ✓ |

V roce 2025 aplikace při překročení stropu jen upozorní, část nad stropem nedaní (viz
zjednodušení 2).

### 5. Ztráty (§ 10 odst. 4)

- Zisky a ztráty ze zdanitelných prodejů CP se v rámci roku sčítají.
- Celková ztráta se uvádí jako 0: nesnižuje jiné příjmy a nepřevádí se do dalších let.
- Prodeje osvobozené časovým testem nebo limitem do výpočtu nevstupují.

Aplikace: přesně tak (`loss_carry_forward: false`). ✓

### 6. Dividendy

**Zahraniční dividendy:**
- Uvádějí se v hrubé výši (před zahraniční srážkou) jako příjem podle § 8 na **ř. 38**.
- Případně je lze zahrnout do **samostatného základu daně podle § 16a** (Příloha 4, od 2021); ten se
  daní vždy 15 % bez ohledu na hranici pro 23 %.
- Zahraniční daň se započte metodou prostého zápočtu (§ 38f, **Příloha 3**), a to nejvýše do
  sazby podle smlouvy o zamezení dvojímu zdanění (portfoliové dividendy obvykle 15 %) a nejvýše do
  výše české daně z dané dividendy.
- Přebytek srážky (např. Německo 26,375 %) se nezapočte; lze o něj žádat ve státě zdroje.

**Tuzemské dividendy:**
- Srážková daň 15 % u zdroje je konečná; dividenda do přiznání nevstupuje.
- Při srážce 35 % (např. zahraniční broker bez doložení rezidence) aplikace upozorní; postup vrácení
  rozdílu není ověřen (viz zjednodušení 5).

| Rok | V pravidlech | Kontrola |
|---|---|---|
| 2021–2026 | `domestic_rate: 0.15`, `treaty_rates.default: 0.15`, zápočet min(srážka, smluvní sazba, česká daň) po státech | ✓ |

### 7. Přepočet cizí měny (§ 38)

Fyzická osoba, která nevede účetnictví, si může zvolit:
- **jednotný kurz** za zdaňovací období (pokyn GFŘ; průměr kurzů ČNB k poslednímu dni měsíců), nebo
- **denní kurz ČNB** ke dni uskutečnění příjmu či výdaje.

Výdaj (nákup) z dřívějšího roku se přepočte kurzem platným **v době nákupu**, tj. při jednotném
kurzu kurzem roku nákupu (rozsudek NSS 2 Afs 42/2019-35).

Aplikace umí obě metody (zvolí se v Nastavení), výdaje přepočítává ke dni nákupu a upozorní při
míchání zdrojů kurzů. Jednotné kurzy počítá sama z kurzů ČNB a výsledky souhlasí s pokyny GFŘ:

| Rok | Pokyn GFŘ | EUR | USD | Aplikace |
|---|---|---|---|---|
| 2021 | GFŘ-D-54 | 25,65 | 21,72 | ✓ ✓ |
| 2022 | GFŘ-D-60 | 24,54 | 23,41 | ✓ ✓ |
| 2023 | GFŘ-D-63 | 23,97 | 22,14 | ✓ ✓ |
| 2024 | GFŘ-D-66 (nahradil D-65) | 25,16 | 23,28 | ✓ ✓ |
| 2025 | GFŘ-D-75 | 24,66 | 21,84 | ✓ ✓ |

### 8. Oznámení osvobozených příjmů (§ 38v)

- Osvobozený příjem **nad 5 000 000 Kč** je nutné oznámit finančnímu úřadu do konce lhůty pro
  podání přiznání, a to i bez povinnosti podat přiznání.
- Limit se posuzuje **u každého příjmu zvlášť**.
- Pokuta podle § 38w je 0,1 % (oznámeno pozdě bez výzvy), 10 % (po výzvě) a 15 % (neoznámeno)
  neoznámeného příjmu.

| Rok | V pravidlech | Kontrola |
|---|---|---|
| 2021–2026 | `exempt_notification_limit: 5000000` | ✓ hodnota; aplikace ji ale porovnává se **součtem** osvobozených prodejů (viz zjednodušení 3) |

### 9. Řádky přiznání

| Údaj | Místo v DAP FO | Kontrola |
|---|---|---|
| Zahraniční dividendy | ř. 38 (§ 8), zápočet v Příloze 3; alternativně Příloha 4 (§ 16a) | ✓ podle zdrojů |
| Zisk z prodeje CP | Příloha 2, oddíl 2 (ostatní příjmy § 10) → ř. 40 | ✓ podle struktury tiskopisu |

Čísla řádků se mohou s novým tiskopisem měnit – ověřte aktuální verzi tiskopisu.

## Drobnosti k úpravě

Neovlivňují výpočet, týkají se jen popisu v souborech pravidel. **Zatím neupraveno.**

| Soubor | Co | Návrh |
|---|---|---|
| `2026.yaml` | poznámka „❓ ověřit“ u `higher_rate_threshold` | odstranit – hodnota 1 762 812 Kč je potvrzená |
| `2021.yaml`–`2023.yaml` | zdroj „Pokyn GFŘ – jednotné kurzy“ bez čísla | doplnit GFŘ-D-54 / D-60 / D-63 |
| `2024.yaml` | „GFŘ-D-65/66“ | upřesnit: platný je GFŘ-D-66 (nahradil D-65) |

## Zjednodušení aplikace

1. **Výklad limitu 100 000 Kč.** Do úhrnu se započítávají i prodeje po časovém testu. Je to
   opatrnější a převažující výklad, zákon to ale výslovně neříká. Přepínač
   `limit_includes_time_tested` v pravidlech umožňuje výklad změnit.
2. **Strop 40 mil. Kč (2025).** Při překročení aplikace jen upozorní; příjmy nad strop nedaní.
3. **Oznámení podle § 38v.** Aplikace upozorní, když **součet** osvobozených prodejů přesáhne
   5 mil. Kč, zákon ale posuzuje každý příjem zvlášť. Upozornění tak může přijít i tam, kde
   povinnost oznámení nevzniká.
4. **Časový test u zděděných CP.** Aplikace počítá držbu od data nabytí na účtu. Doba držby
   zůstavitele se nepřičítá.
5. **Tuzemské dividendy se srážkou 35 %.** Aplikace upozorní a vyčíslí rozdíl proti 15 %. Zda a jak
   lze rozdíl získat zpět (zahrnutím do přiznání nebo přes plátce či brokera), nebylo ověřeno.
6. **Odhad daně 23 %.** Bere celý základ, včetně dividend, jako by byl nad hranicí. Zahraniční
   dividendy v samostatném základu § 16a by zůstaly na 15 %.
7. **Sazby ze smluv.** Pro všechny státy se bere 15 %. Smlouvy s jinou sazbou pro portfoliové
   dividendy se zatím nerozlišují.

## Zdroje

**Zákon a výklad**
- [Zákon č. 586/1992 Sb. o daních z příjmů – aktuální znění (zakonyprolidi.cz)](https://www.zakonyprolidi.cz/cs/1992-586) – § 4 odst. 1 písm. t), u), § 4 odst. 3
- [Pokyn GFŘ-D-59 (financnisprava.gov.cz)](https://financnisprava.gov.cz/assets/cs/prilohy/d-sprava-dani-a-poplatku/Pokyn_GFR-D-59.pdf) – limit a časový test nelze kombinovat
- [Osvobození příjmů z prodeje CP, podílů a kryptoměn (Accace)](https://www.accace.cz/prijmy-z-prodeje-cennych-papiru-a-podilu/)
- [Zdanění cenných papírů pro pokročilé (danesestandou.cz)](https://danesestandou.cz/zdaneni-cennych-papiru-pro-pokrocile/)
- [Jak zdanit příjmy z prodeje akcií a podílových listů (penize.cz)](https://www.penize.cz/dan-z-prijmu-fyzickych-osob/425326-jak-zdanit-prijmy-z-prodeje-akcii-a-podilovych-listu-investice-a-danove-priznani)
- [Ostatní příjmy v daňovém přiznání (finance.cz)](https://www.finance.cz/clanky/461865-ostatni-prijmy-v-danovem-priznani/) – započtení ztráty

**Sazby a hranice**
- [Průměrná mzda 2026 (money.cz)](https://money.cz/novinky-a-tipy/rychle-zpravy/prumerna-mzda-pro-rok-2026/)
- [Průměrná mzda 2026 (behounek.eu)](https://www.behounek.eu/l/prumerna-mzda/)
- [Kdo musí odvádět 23% daň (finance.cz)](https://www.finance.cz/535624-dan-z-prijmu-23-procent/) – hranice 2021–2023
- [Uplatnění progresivní daně v roce 2023 (dauc.cz)](https://www.dauc.cz/clanky/11689/uplatneni-progresivni-dane-u-fyzickych-osob-v-roce-2023-a-jak-se-mu-vyhnout-v-ramci-zakona-o-danich-z-prijmu)

**Strop 40 mil. Kč**
- [Zrušení limitu pro osvobození příjmů (TPA)](https://www.tpa-group.cz/news/zruseni-limitu-pro-osvobozeni-prijmu-z-prodeje-obchodnich-podilu-a-cennych-papiru/)
- [Změny v osvobození příjmů od roku 2026 (Portál POHODA)](https://portal.pohoda.cz/dane-ucetnictvi-mzdy/dan-z-prijmu/zmeny-v-osvobozeni-prijmu-z-prodeje-cennych-papiru-a-obchodnich-podilu-od-roku-2026/)
- [Prodeje firem nad 40 milionů se už danit nebudou (BusinessInfo)](https://www.businessinfo.cz/clanky/prodeje-firem-nad-40-milionu-se-uz-danit-nebudou-pravidla-se-zmeni-od-ledna-2026/)

**Dividendy**
- [Zahraniční dividendy a zamezení dvojího zdanění (taxero.cz)](https://taxero.cz/blog/zahranicni-dividendy-dane)
- [Daň z dividend: jak zdanit zahraniční dividendy (trackly.cz)](https://www.trackly.cz/blog/dan-z-dividend) – ř. 38, Příloha 3 a 4
- [Daňové změny kolem investic s rokem 2025 (kurzy.cz)](https://zpravy.kurzy.cz/791667-danove-zmeny-kolem-investic-s-rokem-2025-casovy-test-prodeje-dividendy/)
- [Zdanění dividend v přiznání (neotax.eu)](https://neotax.eu/cs/blog/zdaneni-dividend-jak-se-uvadi-v-danovem-priznani-ceske-a-zahranicni-dividendy)
- [Dividendy z Česka i ze zahraničí (nikolazitkova.cz)](https://nikolazitkova.cz/dividendy-z-ceska-i-ze-zahranici-kdy-do-danoveho-priznani-patri-a-kdy-ne/)

**Jednotné kurzy a přepočet**
- [Pokyn GFŘ-D-60 – jednotné kurzy 2022 (financnisprava.gov.cz)](https://financnisprava.gov.cz/assets/cs/prilohy/d-sprava-dani-a-poplatku/Pokyn_GFR-D-60_FZ_1-2023.pdf)
- [Pokyn GFŘ-D-63 – jednotné kurzy 2023 (financnisprava.gov.cz)](https://financnisprava.gov.cz/assets/cs/prilohy/d-sprava-dani-a-poplatku/Pokyn_GFR-D-63.pdf)
- [Pokyn GFŘ-D-65 – jednotné kurzy 2024 (financnisprava.gov.cz)](https://financnisprava.gov.cz/assets/cs/prilohy/d-sprava-dani-a-poplatku/Pokyn_GFR-D-65.pdf), nahrazen D-66 ([Finanční zpravodaj 4/2025](https://mf.gov.cz/assets/attachments/2025-01-21_Financni-zpravodaj-cislo-4-2025.pdf))
- [Finanční zpravodaj 2/2026 – GFŘ-D-75, jednotné kurzy 2025 (mf.gov.cz)](https://mf.gov.cz/assets/attachments/2026-01-14_Financni-zpravodaj-cislo-2-2026.pdf)
- Přehledy kurzů: [2021](https://www.conto-servis.cz/jednotne-kurzy-za-rok-2021) · [2022](https://www.conto-servis.cz/jednotne-kurzy-za-rok-2022) · [2023](https://www.conto-servis.cz/jednotne-kurzy-za-rok-2023) · [2024](https://www.conto-servis.cz/jednotne-kurzy-za-rok-2024) · [2025](https://www.conto-servis.cz/jednotne-kurzy-za-rok-2025)
- [Jakým kurzem přepočítávat výdaje z předchozích období – NSS 2 Afs 42/2019 (epravo.cz)](https://www.epravo.cz/top/clanky/polemika-s-rozhodnutim-nejvyssiho-spravniho-soudu-2-afs-42019-35-aneb-jakym-kurzem-prepocitavat-cizomenove-vydaje-vznikle-v-predchozich-zdanovacich-obdobich-110799.html?pdf=1)

**Oznámení osvobozených příjmů**
- [Oznámení o osvobozených příjmech (portal.gov.cz)](https://portal.gov.cz/sluzby-vs/oznameni-o-osvobozenych-prijmech-S20034)
- [Osvobozené příjmy musíte nahlásit (finance.cz)](https://www.finance.cz/clanky/552815-oznameni-prijmu-osvobozenych-od-dane-pokuty)
- [Nad judikaturou k pokutám za neoznámení (dauc.cz)](https://www.dauc.cz/clanky/16221/nad-judikaturou-z-oblasti-pokut-za-neoznameni-osvobozenych-prijmu)

## Historie kontrol

| Datum | Rozsah | Výsledek |
|---|---|---|
| 2026-10-31 | roky 2021–2026, všechna pravidla výše; jednotné kurzy přepočítány aplikací | 0 chyb v hodnotách, 3 drobnosti v popisu, 7 zjednodušení; neopraveno |
