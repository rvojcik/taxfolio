# Architektura: Taxfolio

> Navazuje na `ZADANI.md` (rozhodnutí D1–D12). Stav: **odsouhlaseno, M0 + M1 hotovo** (viz §9).

## 1. Technologický stack

| Oblast | Volba | Důvod |
|---|---|---|
| Jazyk | Python 3.12+ | jeden jazyk pro výpočty i UI |
| UI | PySide6 (Qt 6) – Widgets, `QTableView` + `QSortFilterProxyModel` | nativní na Linux/Win/macOS, rychlé tabulky s tisíci řádků |
| Grafy | QtCharts (součást PySide6) | bez další závislosti |
| Úložiště | SQLite (jeden soubor v uživatelském adresáři) + SQLAlchemy 2.0 + Alembic migrace | lokální, přenositelné, migrace schématu mezi verzemi |
| Čísla | `decimal.Decimal` všude (v DB jako TEXT) | žádné float chyby v daních |
| Parsování | `csv` / `xml.etree` + Pydantic modely pro validaci řádků | čitelné chybové hlášky |
| HTTP | `httpx` | Flex Web Service, kurzy ČNB/ECB |
| Tajemství | `keyring` | Flex token v systémové klíčence |
| Exporty | `openpyxl` (XLSX), `QPdfWriter` (PDF) | |
| Konfigurace pravidel | YAML (`ruamel.yaml`) + JSON Schema validace | daňová pravidla po letech mimo kód |
| Balení | PyInstaller; GitHub Actions matrix (ubuntu, windows, macos) → AppImage/.deb, .msi/.exe, .dmg | D6 |
| Kvalita | pytest, hypothesis (FIFO invarianty), ruff, mypy | |

## 2. Vrstvy a moduly

```
taxfolio/
├── app.py                  # vstupní bod, Qt aplikace
├── domain/                 # čisté datové typy (dataclasses), bez závislostí na DB/UI
│   ├── models.py           # Account, Instrument, Execution, Order, Lot, LotMatch,
│   │                       # CashTransaction, CorporateAction, FxRate, Annotation
│   └── enums.py            # AssetClass, Side, ExitReason, CashType, Country ...
├── importers/
│   ├── detect.py           # rozpozná Flex CSV / Flex XML / Activity Statement CSV
│   ├── flex_csv.py
│   ├── flex_xml.py
│   ├── activity_statement.py
│   ├── flex_web.py         # SendRequest → ReferenceCode → GetStatement, po 365 dnech
│   └── normalize.py        # → doménové objekty, deduplikační klíče
├── fx/
│   ├── cnb.py              # denní kurzy ČNB + jednotný kurz GFŘ (ruční tabulka v YAML)
│   ├── ecb.py              # referenční kurzy ECB (SR)
│   └── converter.py        # convert(amount, ccy, date, target, method)
├── engine/
│   ├── lots.py             # FIFO párování, aplikace splitů/corporate actions
│   ├── positions.py        # round-tripy: vstup → dokupy → výstupy
│   ├── exit_classifier.py  # SL / TP / ruční / likvidace (OrderReference > bracket > typ příkazu)
│   ├── dividends.py        # párování dividenda ↔ srážka ↔ pozdější korekce
│   ├── bonds.py            # AÚV, kupóny, splacení
│   ├── fx_ledger.py        # konverze měn, kurzové rozdíly (informativně)
│   └── stats.py            # win rate, profit factor, P/L dle důvodu výstupu ...
├── tax/
│   ├── rules/              # YAML: cz/2024.yaml, cz/2025.yaml, cz/2026.yaml, sk/2024.yaml ...
│   ├── rules_loader.py     # načtení + validace schématu
│   ├── base.py             # TaxCalculator protokol, TaxReport, TaxLine, Warning
│   ├── cz.py               # § 10, § 8, § 16a, § 38f, časový test, 100k limit, 5M oznámení
│   ├── sk.py               # § 8, osobitný základ (dividendy), 500 €, 1 rok, zdravotné odvody
│   └── simulator.py        # „co když prodám“, kalendář časového testu
├── storage/
│   ├── db.py               # SQLAlchemy engine, session
│   ├── schema.py           # tabulky
│   ├── repositories.py
│   └── migrations/         # Alembic
├── reports/
│   ├── xlsx.py
│   └── pdf.py
└── ui/
    ├── main_window.py      # přepínač účtu, roku, rezidence, zobrazovací měny
    ├── import_view.py      # drag&drop souborů, Flex Web stažení, historie importů
    ├── journal_view.py     # obchodní deník (filtry, fulltext)
    ├── position_detail.py  # časová osa, poznámky, štítky, ruční přeznačení důvodu
    ├── stats_view.py
    ├── tax_view.py         # dividendy dle zemí, zisky/ztráty, „co napsat do přiznání“
    ├── simulator_view.py
    └── settings_view.py    # účty, rezidence po letech, metoda kurzu, Flex token
```

**Pravidlo závislostí:** `ui → (engine, tax, reports) → domain`; `importers, storage → domain`. `engine` a `tax` neznají Qt ani DB → plně testovatelné bez UI.

## 3. Datový model (SQLite)

| Tabulka | Klíčové sloupce | Pozn. |
|---|---|---|
| `account` | id, ibkr_account_id, name, base_ccy | D7 – více účtů |
| `residence_period` | account_id?, country (CZ/SK), year_from, year_to | D3 – rezidence po letech (globální nebo per účet) |
| `instrument` | id, conid, isin, symbol, asset_class, issuer_country, listing_exchange, regulated_market (bool), currency | země z Financial Instrument Info |
| `import_batch` | id, account_id, source (file/flex_web), filename, hash, period_from, period_to, imported_at, row_counts | undo importu |
| `execution` | id, account_id, trade_id (UNIQUE), ib_order_id, instrument_id, datetime, side, open_close, qty, price, proceeds, commission, ccy, notes_codes, ibkr_fifo_pnl, batch_id | |
| `order` | ib_order_id, order_type, order_reference, parent_id, oca_group, order_time | |
| `lot` | id, instrument_id, open_execution_id, open_date, qty_open, qty_remaining, cost_ccy, cost_total, adjusted_by_ca | vzniká výpočtem |
| `lot_match` | id, lot_id, close_execution_id, qty, cost_part, proceeds_part, holding_days | výsledek FIFO |
| `cash_txn` | id, account_id, action_id, type, instrument_id?, datetime, settle_date, amount, ccy, description, linked_to_id, batch_id | dividendy, srážky, úroky, poplatky, vklady |
| `corporate_action` | id, instrument_id, type, ratio, datetime, description | |
| `fx_rate` | source (CNB/ECB/GFR_ANNUAL), ccy, date/year, rate | cache |
| `annotation` | entity (position/execution/cash_txn), entity_id, exit_reason_override, tags, note, sk_dividend_profit_year_override | **import nikdy nepřepíše** |

Odvozené tabulky (`lot`, `lot_match`, pozice) se přepočítají po každém importu – deterministicky z primárních dat.

## 4. Daňová pravidla jako konfigurace (příklad)

```yaml
# tax/rules/cz/2026.yaml
country: CZ
year: 2026
currency: CZK
sources:
  - "ZDP 586/1992 Sb., § 4 odst. 1 písm. w), x)"
securities_sale:
  section: "§10"
  time_test_years: 3
  time_test_cap: null            # 2025: 40000000
  gross_income_exemption_limit: 100000
  lot_method: FIFO
  loss_carry_forward: false
dividends_foreign:
  section: "§8"
  rate: 0.15
  allow_separate_base_16a: true
  credit_method: simple          # prostý zápočet § 38f
income_tax_brackets:
  - { up_to: 1762812, rate: 0.15 }  # ❓ ověřit hranici pro 2026
  - { up_to: null,    rate: 0.23 }
exempt_income_notification_limit: 5000000
fx_methods: [CNB_DAILY, GFR_ANNUAL]
```

Každý rok/země = jeden soubor. Nový rok = zkopírovat a upravit, bez zásahu do kódu. Kalkulačka odmítne počítat rok, pro který chybí pravidla.

## 5. Klíčové algoritmy

1. **FIFO párování** – per účet + instrument, chronologicky; split upraví `qty_remaining` a jednotkovou cenu lotů; short prodej otevře záporný lot (pro akcie výjimečné, ale nesmí spadnout). Kontrola: součet P/L vs. `FifoPnlRealized` z IBKR, rozdíl > tolerance → varování.
2. **Přepočet měn** – nákup kurzem dne nákupu, prodej kurzem dne prodeje (nebo jednotný kurz roku – u ČR pro oba roky, v nichž obchody proběhly); poplatky kurzem dne poplatku.
3. **Klasifikace výstupu** – priorita: ruční anotace > `OrderReference` (mapovatelné klíčová slova v nastavení) > vazba bracket/OCA (child STP = SL, child LMT = TP) > typ příkazu (`STP*`/`TRAIL*` = SL; `LMT` v zisku = TP?, jinak ruční) > `Notes/Codes` (L = likvidace).
4. **Dividendy** – seskupení podle `ActionID` (fallback: ISIN + pay date); srážky/korekce z pozdějších měsíců přiřazeny k původní dividendě a roku; země zdroje z `issuer_country`, ne z měny.
5. **Výpočet ČR** – osvobozené loty (časový test) → test 100k na hrubé příjmy → zdanitelné zisky − ztráty (min. 0) → Příloha 2; dividendy + úroky → § 8 nebo § 16a; zápočet po státech (Příloha 3), limit = česká daň připadající na příjem ze státu.
6. **Výpočet SR** – osvobozené (> 1 rok + regulovaný trh) → úhrn zdanitelných příjmů − výdaje → 500 € (pokud není čerpáno jinde – přepínač v nastavení) → základ § 8, sazba 19/25 %, orientační zdravotné odvody; dividendy v osobitném základe dle D10, zápočet.

## 6. Plán realizace (milníky)

| Milník | Obsah | Výstup / akceptace |
|---|---|---|
| **M0** Kostra | repo, pyproject, ruff/mypy/pytest, prázdné Qt okno, SQLite + Alembic, CI build pro 3 OS | spustitelný balíček na Linux/Win/macOS |
| **M1** Import | detekce formátu, Flex CSV + XML, Activity Statement, deduplikace, historie importů, návod na Flex Query | import vašich exportů 2024–2026 bez chyb, opakovaný import nevytvoří duplicity |
| **M2** Obchodní deník | pozice/round-tripy, klasifikace výstupů, filtry, fulltext, detail, poznámky/štítky, přepínání účtu a měny | vyhledám libovolný obchod a vidím důvod výstupu |
| **M3** Kurzy + FIFO | ČNB/ECB stahování a cache, jednotný kurz, FIFO, corporate actions, kontrola proti IBKR | realizovaný P/L sedí s IBKR (v USD) |
| **M4** Daně ČR | pravidla 2021–2026, Příloha 2/3, § 8/§ 16a, kalendář časového testu, PDF/XLSX příloha; **ověření ❓ bodů** | ručně spočítané referenční příklady = výstup aplikace |
| **M5** Daně SR | pravidla 2021–2026, DP typ B, osobitný základ, 500 €, zdravotné odvody | dtto |
| **M6** Dluhopisy, forex, simulátor | AÚV/kupóny, FX ledger, „co když prodám“, tax-loss harvesting přehled, statistiky | |
| **M7** Flex Web Service | stažení přes token (keyring), plánované „stáhni nová data“, finální balíčky | jedno tlačítko „Aktualizovat“ |

## 7. Testování
- **Unit** – FIFO, převody měn, klasifikátor, daňové kalkulačky (bez UI/DB).
- **Property-based** (hypothesis) – součet spárovaných množství = prodané množství; P/L nezávisí na pořadí importu souborů.
- **Golden files** – anonymizované vzorky IBKR exportů → očekávaný JSON výstup.
- **Referenční daňové případy** – tabulka ručně spočítaných scénářů pro ČR a SR (osvobození časovým testem, překročení 100k, ztráta, DE dividenda 26,375 %, SR dividenda 2025 vs. 2026 …).

## 8. Co potřebuji od uživatele pro M1
- **Vzorek exportu** z vašeho účtu (Flex Query CSV nebo Activity Statement) – ideálně anonymizovaný (číslo účtu lze přepsat), aby parsery seděly na reálná data.
- Potvrzení, že plán milníků vyhovuje, nebo změna priorit (např. daně ČR dřív než deník).

## 9. Stav implementace

### M0 + M1 (hotovo, 2026-10-29)
- Kostra projektu (`uv`, `src/taxfolio`), ruff + mypy + pytest, CI matrix Linux/Windows/macOS s PyInstaller buildem (`.github/workflows/ci.yml`).
- Importéry podle **skutečných exportů uživatele** (`data_examples/`, mimo git):
  - **Activity Statement CSV** – Trades (akcie i forex, dvě hlavičky v sekci), Dividends, Withholding Tax, Fees, Deposits & Withdrawals, Interest, Corporate Actions, Open Positions, Financial Instrument Information (vč. aliasů symbolů, např. `EXSA, EXSAd`).
  - **Dividend Report CSV** – země zdroje (přepisuje odhad země z ISIN), rozpad hrubé částky a srážky.
  - **FX Income Worksheet CSV** – kurzové P/L z pohledu IBKR (informativně).
- SQLite úložiště s deduplikací přes `natural_key` (hash obsahu + pořadí shodných řádků), historie importů a undo.
- Desktop UI: záložka Import (dialog + drag&drop, historie, undo) a Obchodní deník (filtr účet/rok/třída aktiv, fulltext, řazení).
- CLI `taxfolio import|batches|undo|trades|status`.

### Flex Query + klasifikace důvodu (hotovo, 2026-10-29)
- Importér **Flex Query XML** (`importers/flex_xml.py`): exekuce (ne agregované ORDER řádky), closed loty s datem nákupu, cash transakce s `actionID`/`exDate`, corporate actions s typem (FS/RS), open positions na úrovni lotů, kurzy IBKR (`fx_rate`).
- **Přednost Flex dat**: import Flex Query smaže řádky z Activity Statementu pro stejný účet a období; Activity Statement importovaný do období pokrytého Flexem se přeskočí.
- `engine/exit_classifier.py`: vstup / stop-loss / take-profit / ruční výstup / likvidace / auto FX. V datech uživatele 2024–2025: 1× stop-loss (AMD), 1× take-profit (GOOGL), zbytek ruční výstupy; `orderReference` uživatel nevyplňuje.
- Deník: sloupce Důvod, Příkaz, Zadán; filtr podle důvodu.
- Schéma v2; při starší verzi se (pre-release) databáze založí znovu.

### M3 – kurzy + FIFO (hotovo, 2026-10-29)
- `fx/sources.py`: stahování ČNB (roční soubor `rok.txt`) a ECB (`eurofxref-hist.zip`), uloženo v `reference_rate`; minulé roky se stahují jednou, aktuální rok se obnovuje.
- `fx/converter.py`: ČNB denní kurz (víkend/svátek → poslední předchozí fixing), **jednotný kurz počítán jako průměr kurzů ČNB k poslednímu dni měsíců**, zaokrouhleno na 0,01 – ověřeno proti GFŘ-D-65/66 (2024: EUR 25,16, USD 23,28) a GFŘ-D-75 (2025: EUR 24,66, USD 21,84); možnost ručního přepsání. ECB pro SR.
- `engine/lots.py`: FIFO podle ISIN, nákupní poplatek v pořizovací ceně, prodejní snižuje výnos; dopředné i reverzní splity (HOOK 1:10 se změnou ISIN), přenesení data nákupu.
- `services/realized.py`: realizované páry s přepočtem (nákup kurzem dne nákupu, prodej kurzem dne prodeje) a **kontrola proti IBKR** (`fifoPnlRealized` po exekucích + data nákupu z Closed Lots). Na datech uživatele 2024–2025: 38 párování, 0 rozdílů.
- Zjištění: IBKR účtuje poplatek u exekucí jednoho příkazu nerovnoměrně (první exekuce nese celý poplatek) a FIFO řadí exekuce se stejným časem podle `tradeID` – aplikace to dělá stejně.
- UI: záložka „Realizace (FIFO)“ s volbou ČNB denní / jednotný kurz, součty zisků, ztrát a salda v CZK a EUR, stav kontroly s IBKR. CLI: `taxfolio rates`, `taxfolio realized --year --czk`.

### M4 – daně ČR (hotovo, 2026-10-29)
- Pravidla `tax/rules/cz/2024|2025|2026.yaml` (`tax/rules_loader.py`): časový test 3 roky, strop 40 mil. (jen 2025), limit 100 000 Kč, sazby a hranice 23 %, smluvní sazby pro zápočet (výchozí 15 %).
- `tax/cz.py`: časový test po lotech (držba musí *přesáhnout* 3 roky), limit 100 000 Kč z hrubých příjmů (přepínač `limit_includes_time_tested`, výchozí = započítávat i prodeje osvobozené časovým testem ❓), zdanitelné příjmy − výdaje, ztráta = 0; dividendy po státech, zápočet min(sraženo, smluvní sazba, česká daň), tuzemské dividendy mimo DAP; upozornění (35% srážka CZ, nezapočitatelná daň, § 38v, 23 %).
- `services/dividends.py`: dividendy + srážky propojené přes `actionID` (Flex) nebo text (Activity Statement), stát zdroje z Dividend Reportu / `issuerCountryCode`.
- UI „Daně ČR“: Do přiznání (ř. 38, ř. 40, Příloha 2 a 3), Prodeje, Dividendy podle zemí, Časový test. CLI `taxfolio tax-cz 2025 --czk GFR_ANNUAL`.
- Výsledek pro uživatele 2025 (ČNB denní): dílčí základ § 10 120 275 Kč, zahraniční dividendy 6 011 Kč, odhad daně 18 152 Kč; jednotný kurz: 139 649 Kč / 21 061 Kč.

### M5 – dane SR (hotovo, 2026-10-29)
- Pravidlá `tax/rules/sk/2024|2025|2026.yaml`: 1 rok + regulovaný trh (zoznam burz), oslobodenie 500 € z (príjmy − výdavky), pásma sadzieb (2024/2025 19/25 %, 2026 19/25/30/35 %), zdravotné poistenie (❓ 14 % / 16 %), sadzby dividend podľa roku zisku (7 % / 10 %), 35 % nespolupracujúce štáty, zmluvné sadzby (AT, NL 10 %).
- `tax/sk.py`: oslobodené predaje sa nezapočítavajú so zdaniteľnými, strata = 0, 500 € (prepínač „už uplatnené inde“), dividendy v osobitnom základe, rok zisku = rok výplaty − 1 (s možnosťou prepísania), zápočet min(zrazené, zmluvná sadzba, daň SR).
- UI „Dane SR“ (slovensky): Do priznania, Predaje, Dividendy, Časový test (1 rok). CLI `taxfolio tax-sk 2025 [--500-used]`.
- Výsledok 2025: oslobodené 6 679,55 €, základ § 8 2 587,85 €, daň 491,69 € + dividendy 1,89 €, zdravotné ~414 €.
- HOOK po reverznom splite je kótovaný na PINK (OTC) → nie je regulovaný trh, oslobodenie po roku by sa neuplatnilo.

### M6 (část) – export podkladů a simulace prodeje (hotovo, 2026-10-29)
- `reports/`: formátově nezávislý `Document` (souhrn, tabulky, upozornění) → XLSX (`openpyxl`) a PDF (Qt `QTextDocument` + `QPdfWriter`, A4 na šířku). Obsah: hodnoty do přiznání, prodeje s kurzy nákupu/prodeje, dividendy po státech i po jednotlivých výplatách, otevřené pozice s datem osvobození. Tlačítko „Exportovat podklady…“ v záložkách Daně ČR / Dane SR, CLI `tax-cz|tax-sk --export soubor.xlsx|.pdf`.
- `services/simulator.py`: hypotetický prodej se přidá do FIFO jako další obchod; daň z prodejů roku se spočítá s ním a bez něj (ČR i SR vč. zdravotného), po lotech ukáže osvobození a datum, od kdy by byl prodej osvobozen. Výchozí cena = poslední známá cena z výpisu; budoucí datum používá poslední známý kurz. Záložka „Simulace prodeje“.
- Kurzy aktuálního roku se obnovují nejvýš jednou za 12 hodin (dřív při každém otevření záložky). Testy síť nepoužívají (`conftest.no_network`).

### Přehled (hotovo, 2026-10-29)
- `services/overview.py`: klíčová čísla a řady pro grafy v jedné měně zobrazení (CZK kurzem ČNB, EUR/USD kurzem ECB ke dni pohybu); top 10 + „Ostatní“; nad 18 měsíců se osa sčítá po čtvrtletích; chybějící kurz přeskočí jen danou položku s upozorněním.
- `ui/charts.py` (QtCharts): barvy z referenční palety dataviz, ověřené validátorem pro světlý i tmavý režim (zisk modrá #2a78d6/#3987e5 ↔ ztráta červená #e34948/#e66767); jedna řada bez legendy, tooltip na každém sloupci, české oddělovače tisíců na osách.
- `ui/overview_view.py`: dlaždice klíčových čísel, 4 grafy, tabulka výsledků podle důvodu výstupu.

### Nastavení, kurzy, spojená záložka Daně, Flex Web Service (hotovo, 2026-10-29)
- `fx/converter.py`: `RateSource` (ČNB denní, jednotný kurz GFŘ, ECB denní, IBKR z výpisu, pevný) a `RateRule` per (cílová měna CZK/EUR, měna); křížové kurzy přes CZK / EUR / bázovou měnu IBKR. Explicitní `CzkMethod` (CLI `--czk`) má přednost.
- `services/settings.py`: nastavení v tabulce `app_setting` (JSON) – výchozí země, Flex Query ID, pravidla kurzů. Nová tabulka nevyžaduje změnu verze schématu.
- Daňové výpočty upozorní, pokud zdroj kurzu zákon nepřipouští (ČR: ČNB / jednotný; SR: ECB) nebo pokud se v ČR kombinují různé zdroje.
- UI: záložka Nastavení (zdroj + pevný kurz + náhled aktuální hodnoty + daňová přípustnost); Daně ČR a SR spojeny do jedné záložky s výběrem země; přepínače metody v Realizaci, Daních a Simulaci nahrazeny popiskem použitých kurzů.
- `importers/flex_web.py`: SendRequest → GetStatement s čekáním na kódy 1019/1018/1009, srozumitelné chyby (1012, 1014, 1015, 1020). `services/secrets.py`: token v systémové klíčence (`keyring`), alternativně `IBKR_FLEX_TOKEN`. `services/flex_sync.py`: stažení (ve vlákně) + uložení XML + import. CLI `flex-token`, `flex-sync` (nahrazeno zdroji dat, viz níže).
- Parametr pro vlastní rozsah dat ve Flex Web Service se nepodařilo ověřit – stahuje se období nastavené v dotazu.

### Jazyky a dividendy podle společností (hotovo, 2026-10-29)
- `i18n/`: `_()` / `N_()`, katalogy `sk.py`, `en.py` (klíč = český zdrojový text, ~380 textů), jazyk v nastavení (výchozí = jazyk systému); změna jazyka v Nastavení znovu sestaví hlavní okno (`app.Application`). `tools/i18n_extract.py` (AST) najde všechny texty; testy hlídají úplnost a zástupné hodnoty. Slovenské texty daňového modulu převedeny na české zdrojové texty, oficiální znění DP typ B je ve slovenském katalogu.
- Neprekládá se: CLI, vývojářské diagnostiky (schéma DB, chybný soubor pravidel).
- Přehled: dividendy podle společnosti (podle ISIN, aliasy symbolů se nedělí) – graf top 10 + tabulka všech společností (výplaty, hrubě, sraženo, čistě, podíl).
- Ruff: E501 vypnuto kvůli celistvým překladovým textům (formátovač kód dál zalamuje).

### Import XTB (hotovo, 2026-10-29)
- `importers/xtb.py`: peněžní operace xStation 5 – starý CSV (`ID;Type;Time;Symbol;Comment;Amount`), nový export s metadaty (`Type;Ticker;Instrument;Time;Amount;ID;Comment;Product`, `;` + desetinná čárka i `,` + tečka) a list „Cash Operations“ v XLSX. Sloupce podle názvu.
- Obchody z komentáře (`OPEN BUY 34/42.5658 @ 11.748`), v měně účtu (Amount); poplatky (Commission, SEC fee, Tax IFTT) se připojí k obchodu se stejným symbolem a časem. Dividenda a srážka spojeny přes `action_id` (symbol + čas). Účet `XTB-<číslo>`.
- Bez ISIN: klíč `SYM:<symbol>`, conid `XTB:<symbol>`, stát zdroje a burza (`XTB:US`…) z přípony symbolu; burzy XTB zařazeny mezi regulované trhy (SR).
- Ověřeno jen na veřejném vzorku (Export-To-Ghostfolio `samples/xtb-export.csv`) a syntetických testech – chybí reálný export uživatele. Formát „Export (new)“ (ZIP) neověřen.

### Zdroje dat, období stahování, mazání více importů (hotovo, 2026-10-30)
- `services/sources.py`: `InputSource` (id, typ, název, zapnuto, nastavení) v `app_setting.input_sources`; popis typů `SOURCE_TYPES` (pole, tajná pole, zda používá období). Tajná pole jen v klíčence (`services/secrets.py`, `source:<id>:<pole>`). Migrace dřívějšího `flex_query_id` + tokenu na zdroj „IBKR“.
- `services/source_sync.py`: `fetch_all` (bez DB, běží ve vlákně; chyba zdroje nezastaví ostatní), `import_all` (UI vlákno), `sync_all` (CLI). Složka: nové soubory podle SHA-256 proti `import_batch.file_sha256`.
- `services/flex_sync.py` + `importers/flex_web.py`: období přes `fd`/`td` (ověřeno v dokumentaci IBKR, max. 365 dní), dělení po kalendářních letech, přestupný rok na poloviny; letošní rok končí včerejškem.
- UI: Nastavení → Zdroje dat (`ui/sources_view.py`, dialog s poli podle typu), Import → *Aktualizovat ze zdrojů* + výběr zdroje a období; historie importů s vícenásobným výběrem a mazáním (Delete).
- CLI: `sources`, `sync [--year …] [--source …]` (alias `flex-sync`), `flex-token --source`, `undo` více čísel.

### Testovací data, Přehled za všechny roky, pravidla 2021–2023 (hotovo, 2026-10-30)
- `test_data/`: fiktivní portfolio IBKR 2021–2025 (Flex XML vč. otevřených pozic) + účet XTB (EUR), generátor `generate.py`, očekávané výsledky v `test_data/README.md`; ověřuje `tests/test_scenarios.py` (pevné kurzy).
- Přehled: časová osa „Všechny roky“ od první aktivity (vklad, nákup, prodej, dividenda), dlouhá období po letech; nový graf Vklady a výběry; prázdný graf s textem „žádná data“; názvy firem bez ISIN (XTB) podle symbolu.
- Daně při výběru jednoho účtu: upozornění, že limity (100 000 Kč, 500 €) a daň platí jen za všechny účty dohromady.
- Pravidla `cz/2021–2023.yaml` (hranice 23 % = 48násobek průměrné mzdy: 1 701 168 / 1 867 728 / 1 935 552 Kč) a `sk/2021–2023.yaml` (176,8násobek ŽM k 1. 1.: 37 981,94 / 38 553,01 / 41 445,46 €; dividendy 7 %; zdravotné 14 % ❓).

### Zastavení aktualizace, kurzy na pozadí, „Lze prodat bez daně“ (hotovo, 2026-10-30)
- `ui/background.py`: práce čekající na síť běží v daemon vlákně (signály se doručí do UI vlákna); `RatesWorker` stahuje kurzy ČNB/ECB. `rates_service.set_auto_download(False)` v desktopové aplikaci – výpočty používají jen uložené kurzy; CLI stahuje jako dřív. Při chybě nový pokus za 5 min, stav ve status baru.
- Aktualizace ze zdrojů: `source_sync.fetch_all(cancel=Event)` – čekání i další požadavek skončí výjimkou `Cancelled`, odpověď po zastavení se zahodí; HTTP timeout 30 s. Tlačítko Aktualizovat ↔ Zastavit, okno se uvolní okamžitě.
- `services/tax_free.py`: pozice, jejichž nejstarší loty splňují časový test k dnešku (ČR 3 roky; SR 1 rok + regulovaný trh) – množství, pořizovací cena, hodnota a zisk podle poslední ceny z výpisu, další datum osvobození. Díky FIFO jsou osvobozené loty vždy nejstarší. Záložka v Daních (ČR i SR), nezávislá na zvoleném roce.

### Zbývá
- Daň z úroků (Activity Statement 2026 obsahuje připsané úroky se srážkou 20 %) – dosud se nezdaňují.
- Dluhopisy (AÚV, kupóny) a daňový pohled na forex (❓ právní posouzení).
- Ruční anotace (důvod výstupu, poznámky, štítky, rok zisku SK dividendy) → zavést Alembic.
- Rezidence po letech (D3) – nyní jsou vidět obě daňové záložky.
- M7: Flex Web Service, instalační balíčky.

### Odchylky od návrhu
- **Alembic zatím není** – schéma se zakládá přes `create_all`, verze v tabulce `meta`. Alembic se zavede s první změnou schématu po vydání.
- Časy v Activity Statementu jsou v US/Eastern; pro daně rozhoduje datum obchodu.

### Poznatky z dat
- Bázová měna účtu je EUR. Obchoduje se v USD, EUR, GBP, PLN, CZK; IBKR dělá denní mikro-konverze (`AFx`) kvůli poplatkům za custody v CZK.
- Splity NVDA 10:1 (06/2024) a AVGO 10:1 (07/2024) – FIFO v M3 musí aplikovat corporate actions, jinak prodeje „přesahují“ nakoupené množství.
- K 1. 1. 2024 nebyly otevřené žádné pozice → všechny loty jsou dohledatelné (D12 potvrzeno).
