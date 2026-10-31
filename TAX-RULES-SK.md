# Slovenská daňová pravidla 2021–2026 – přehled, zdroje a kontrola

Popis pravidel v souborech `2021.yaml` … `2026.yaml` v této složce: co aplikace počítá, podle čeho a
nakolik je to ověřené.

**Poslední kontrola:** 31. 10. 2026 – porovnání pravidel s veřejnými zdroji (Finanční správa SR,
zdravotní pojišťovny, odborné články). Konečné znění zákona č. 595/2003 Z. z. (o dani z príjmov)
a č. 580/2004 Z. z. (o zdravotnom poistení) nebylo přímo čteno.

Aplikace je kalkulačka podkladů, ne daňové poradenství. Před podáním přiznání ověřte aktuální
znění zákona a tiskopisu DP typ B.

## Výsledek kontroly v kostce

| Oblast | Stav |
|---|---|
| Sazby a pásma daně 2021–2026 | ✓ sedí |
| Osvobození po 1 roce na regulovaném trhu | ✓ sedí (s jedním zjednodušením, viz níže) |
| Osvobození 500 € | ✓ sedí |
| Ztráty | ✓ sedí |
| Dividendy podle roku zisku, zápočet zahraniční daně | ✓ sedí |
| **Zdravotní odvody z § 8** | ✗ **2024 a 2025 chybně** – viz [Nalezené chyby](#nalezené-chyby) |
| Přepočet měn | ≈ přípustné, ale zjednodušené |

## Pravidla

### 1. Sazby daně z příjmů (§ 15) – zisk z prodeje CP patří do obecného základu daně

Zisk z prodeje CP (§ 8 ods. 1 písm. e) se zdaňuje v obecném základu daně, takže platí
progresivní pásma (ne samostatný základ jako u dividend).

| Rok | Pásma | Hranice | Výpočet | Kontrola |
|---|---|---|---|---|
| 2021 | 19 % / 25 % | 37 981,94 € | 176,8 × ŽM 214,83 € (platné od 1. 7. 2020) | ✓ |
| 2022 | 19 % / 25 % | 38 553,01 € | 176,8 × ŽM 218,06 € (od 1. 7. 2021) | ✓ |
| 2023 | 19 % / 25 % | 41 445,46 € | 176,8 × ŽM 234,42 € (od 1. 7. 2022) | ✓ |
| 2024 | 19 % / 25 % | 47 537,98 € | 176,8 × ŽM 268,88 € | ✓ |
| 2025 | 19 % / 25 % | 48 441,43 € | 176,8 × ŽM 273,99 € | ✓ |
| 2026 | 19 % / 25 % / 30 % / 35 % | 43 983,32 / 60 349,21 / 75 010,32 € | 154,8× / 212,4× / 264× ŽM 284,13 € | ✓ |

- Hranice se počítá ze životního minima (ŽM) platného k 1. 1. zdaňovacího období.
- Sazby se uplatní po pásmech, tj. vyšší sazbou se daní jen část základu nad hranicí.
- Pásma 2026 se podle zdrojů (např. Tatra banka) vztahují i na zisk z prodeje akcií a ETF.
  Poznámku ❓ v `2026.yaml` lze proto odstranit.
- Aplikace počítá daň jen ze základu z investic. Se mzdou a dalšími příjmy může být sazba vyšší;
  aplikace na to upozorňuje.

### 2. Osvobození prodeje CP po 1 roce (§ 9 ods. 1 písm. k)

Příjem z prodeje je osvobozen **v plné výši**, pokud:
- CP je přijat na **regulovaný trh** (i zahraniční obdobný),
- mezi **nabytím a prodejem** uplyne více než 1 rok,
- mezi **přijetím na regulovaný trh a prodejem** uplyne více než 1 rok,
- CP není zahrnut v obchodním majetku,
- od 1. 1. 2024: CP nebyl nabyt jako nepeněžní plnění (zaměstnanecké akcie) po 31. 12. 2023.

| Rok | V pravidlech | Kontrola |
|---|---|---|
| 2021–2026 | `time_test_years: 1`, `require_regulated_market: true` | ✓ |

Změny 2024–2026 se drobného investora netýkají: konsolidace 2024 vyřadila jen CP nabyté jako
nepeněžní plnění a CP v obchodním majetku. Tvrzení jednoho webu, že od roku 2026 platí roční
osvobození jen do 500 €, jiný zdroj nepotvrzuje; jde zřejmě o záměnu s českou novelou 2026.

### 3. Osvobození 500 € (§ 9 ods. 1 písm. i)

- Osvobozen je úhrn příjmů z prodeje CP **snížený o výdaje** do 500 € za rok.
- Je-li vyšší, zdaní se **jen rozdíl nad 500 €**.
- 500 € se dělí s dalšími příjmy podle § 8 (např. příležitostná činnost).
- Od 2024 se nevztahuje na CP z obchodního majetku ani na CP nabyté jako nepeněžní plnění
  po 31. 12. 2023.

| Rok | V pravidlech | Kontrola |
|---|---|---|
| 2021–2026 | `exemption: 500` (z rozdílu příjmy − výdaje, zdaní se přebytek) | ✓ |

### 4. Ztráty

- Ztrátu z prodeje CP nelze vykázat a nelze ji započíst proti jiným příjmům ani převést do dalších
  let.
- V rámci roku se zisky a ztráty ze zdanitelných prodejů sčítají.
- Ztráta z prodeje osvobozených CP se nezapočítává proti zisku z jiných CP.

Aplikace: zdanitelné prodeje sečte, záporný výsledek bere jako 0 a osvobozené prodeje nezapočítává. ✓

### 5. Zdravotní odvody z § 8 (odhad)

- Ze zdanitelného zisku z prodeje CP se platí zdravotní pojištění v ročním zúčtování (vyměří
  pojišťovna podle údajů z daňového přiznání).
- Osvobozený zisk (po 1 roce nebo do 500 €) do vyměřovacího základu **nevstupuje**.
- Z dividend podle § 51e se od roku 2018 zdravotní pojištění neplatí; aplikace je nepočítá. ✓

| Rok | V pravidlech | Podle zdrojů | Kontrola |
|---|---|---|---|
| 2021 | 14 % | 14 % | ✓ |
| 2022 | 14 % | 14 % | ✓ |
| 2023 | 14 % | 14 % | ✓ |
| **2024** | **14 %** | **15 %** (zvýšení 14 → 15 % od 1. 1. 2024) | ✗ |
| **2025** | **16 %** | **15 %** (v roce 2025 beze změny) | ✗ |
| 2026 | 16 % | 16 % (zvýšení 15 → 16 % od 1. 1. 2026, platí do 31. 12. 2027) | ✓ |

Většina zdrojů i VšZP uvádějí, že zdanitelný zisk z CP odvodům podléhá. Menšinový názor
(finami.sk), že nepodléhá, se nepodařilo ověřit.

### 6. Dividendy ze zahraničí (§ 51e, samostatný základ daně)

- Sazba se řídí **zdaňovacím obdobím, za které byl zisk vykázán**, ne rokem výplaty.
- Aplikace bere rok zisku = rok výplaty − 1 (lze přepsat).

| Rok zisku | Sazba | Kontrola |
|---|---|---|
| 2004–2016 | nepodléhá dani | ✓ |
| 2017–2023 | 7 % | ✓ |
| 2024 | 10 % | ✓ |
| 2025 a dál | 7 % | ✓ |
| z nespolupracujícího státu | 35 % | ✓ (sazba), viz zjednodušení 5 |

**Zápočet zahraniční daně:** jen do výše sazby podle smlouvy o zamezení dvojímu zdanění a do výše
slovenské daně z dané dividendy. Ve smlouvách mají AT a NL 10 %, ostatní (např. US, CZ) 15 %. ✓

### 7. Přepočet cizí měny (§ 31 ods. 2)

Fyzická osoba, která nevede účetnictví, si může zvolit:
- kurz ECB/NBS platný v **den přijetí** příjmu (připsání bankou),
- **průměrný měsíční** kurz za měsíc příjmu,
- **roční průměrný** kurz za zdaňovací období.

Pravidlo „kurz dne předcházejícího účetnímu případu“ platí pro účetní jednotky, ne pro
fyzické osoby bez účetnictví.

Aplikace: denní kurz ECB **v den obchodu** (`rate_day: same`). ≈ Přípustné, ale viz zjednodušení 3.

## Nalezené chyby

| Soubor | Hodnota | Má být | Dopad |
|---|---|---|---|
| `2024.yaml` | `health_insurance.rate: 0.14` | `0.15` | odhad odvodů za 2024 zhruba o 7 % nižší |
| `2025.yaml` | `health_insurance.rate: 0.16` | `0.15` | odhad odvodů za 2025 zhruba o 6 % vyšší |

Daň samotnou chyby neovlivňují, jde jen o odhad zdravotních odvodů. **Zatím neopraveno.**

## Zjednodušení aplikace

1. **Přijetí na regulovaný trh.** Rok od přijetí CP na trh se nekontroluje, protože datum přijetí ve
   výpisech není. Týká se jen CP obchodovaných méně než rok (IPO, nová ETF).
2. **ETF.** Podle stanoviska Finanční správy nemusí každé ETF splňovat podmínky osvobození.
   Aplikace bere všechna ETF na regulovaném trhu jako osvobozená.
3. **Kurz.** Používá se den obchodu, zákon mluví o dni přijetí příjmu. Ten je ale den vypořádání,
   obvykle o 1–2 pracovní dny později. Měsíční ani roční průměr aplikace nenabízí.
4. **Sdílené 500 €.** Aplikace umí jen „celé osvobození už použito jinde“, ne částečné rozdělení
   mezi příjmy podle § 8.
5. **Nespolupracující státy.** Seznam (`non_cooperating_states`) je prázdný, sazba 35 % se tedy
   nikdy nepoužije.

## Zdroje

**Finanční správa SR**
- [Príjmy fyzickej osoby z predaja cenných papierov](https://podpora.financnasprava.sk/575795-Pr%C3%ADjmy-fyzickej-osoby-z-predaja-cenn%C3%BDch-papierov) – 500 €, ztráty
- [Oslobodenie príjmu z predaja cenných papierov](https://podpora.financnasprava.sk/927974-Oslobodenie-pr%C3%ADjmu-z-predaja-cenn%C3%BDch-papierov) – podmínky osvobození po 1 roce
- [Oslobodenie príjmov z predaja cenných papierov](https://podpora.financnasprava.sk/798719-Oslobodenie-pr%C3%ADjmov-z-predaja-cenn%C3%BDch-papierov)
- [Príjem charakteru dividend zo zahraničia](https://podpora.financnasprava.sk/830591-Pr%C3%ADjem-charakteru-dividend-podielov-na-zisku-zo-zahrani%C4%8Dia) – sazby podle roku zisku, zápočet

**Sazby a pásma**
- [Progresívna daň 2026 (danovy-poradca.sk)](https://www.danovy-poradca.sk/blog/progresivna-dan-2026)
- [Progresívne zdanenie od roku 2026 (fakturaonline.sk)](https://www.fakturaonline.sk/podnikatelov-sprievodca/dane/dan-z-prijmov/progresivne-zdanenie-prijmov-fyzickych-osob-od-roku-2026)
- [Zdaňovanie príjmov z investovania (Tatra banka)](https://www.tatrabanka.sk/sk/personal/sporenie-investovanie/zdanovanie-prijmov-z-investovania/)
- Životní minimum: [od 1. 7. 2021](https://www.podnikajte.sk/uctovnictvo/zivotne-minimum-od-1-7-2021-do-30-6-2022) ·
  [od 1. 7. 2024](https://www.podnikajte.sk/uctovnictvo/zivotne-minimum-od-1-7-2024-do-30-6-2025) ·
  [od 1. 7. 2025](https://www.podnikajte.sk/uctovnictvo/zivotne-minimum-od-1-7-2025-do-30-6-2026)

**Zdravotní odvody**
- [VšZP – Zmena sadzby poistného od 1. 1. 2026](https://www.vszp.sk/novinky/zmena-sadzby-poistneho-vysky-preddavkov-od-01-01-2026.html)
- [Minimálne odvody SZČO od 1. 1. 2024 (podnikajte.sk)](https://www.podnikajte.sk/socialne-a-zdravotne-odvody/minimalne-odvody-szco-zivnostnikov-od-1-1-2024)
- [Odvody SZČO od 1. 1. 2025 (podnikajte.sk)](https://www.podnikajte.sk/socialne-a-zdravotne-odvody/odvody-szco-od-1-1-2025)
- [Odvody SZČO od 1. 1. 2025 (Daňové centrum)](https://www.danovecentrum.sk/aktuality/odvody-samostatne-zarobkovo-cinnej-osoby-od-1-januara-2025-aktualita-dc-2-2025.htm)
- [Odvody SZČO v roku 2026 (RSM)](https://rsmsk.sk/blog/odvody-szco-v-roku-2026-kompletny-sprievodca-legislativnymi-zmenami)
- [Dane z ETF 2026 (etfstart.sk)](https://www.etfstart.sk/ako-sa-zdanuju-etf-na-slovensku-v-roku-2026-casovy-test-dividendy-a-tri-chyby-ktore-stoja-stovky-eur)
- [Dane z investícií 2026 (finami.sk)](https://finami.sk/blog/2026-06-22-dane-z-investicii-2026-etf-akcie-dividendy-slovensko) – menšinový názor, že se odvody neplatí

**Přepočet měn (§ 31)**
- [Ako prepočítať kurz zahraničnej meny v daňovom priznaní (mojedane.sk)](https://www.mojedane.sk/blog/ako-prepocitat-kurz-zahranicnej-meny-na-eura-do-danoveho-priznania)
- [Komentár k ZDP § 31 (uad.sk)](https://www.uad.sk/33/komentar-k-zdp-31-prepocitaci-kurz-uniqueidmRRWSbk196FPkyDafLfWAE1d2WUUfDAbzVrTtTRqqfShMfAkYY5hNgw7pWV-1AwW/)

**Změny 2024–2026**
- [Zdaňovanie CP po prijatí konsolidačného balíčka (ekopossplus.sk)](https://ekopossplus.sk/blog-zdanovanie-cennych-papierov-po-prijati-konsolidacneho-balicka)
- [Daň z predaja cenných papierov (rulecalc.com)](https://rulecalc.com/sk/dan/dan-z-predaja-cennych-papierov) – nepotvrzené tvrzení o omezení osvobození od 2026

## Historie kontrol

| Datum | Rozsah | Výsledek |
|---|---|---|
| 2026-10-31 | roky 2021–2026, všechna pravidla výše | 2 chyby (zdravotní odvody 2024, 2025), 5 zjednodušení; neopraveno |
