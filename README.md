# Taxfolio

**Obchodní deník a daně z investic pro ČR a SR.** Desktopová aplikace pro přehled obchodů
z Interactive Brokers a XTB a podklady k daňovému přiznání v České a Slovenské republice.
Zadání: [ZADANI.md](ZADANI.md), architektura a plán: [ARCHITEKTURA.md](ARCHITEKTURA.md).

Data zůstávají lokálně v SQLite (`~/.local/share/taxfolio/` na Linuxu, odpovídající uživatelský
adresář na Windows/macOS).

## Instalace

Hotové instalátory jsou na stránce **[Releases](https://github.com/rvojcik/taxfolio/releases/latest)**.
Python ani nic dalšího není potřeba instalovat.

| Systém | Soubor | Postup |
|---|---|---|
| **Windows 10/11** (64bit) | `Taxfolio-<verze>-Setup.exe` | spustit, projít průvodce; aplikace je pak v nabídce Start. Instaluje se jen pro aktuálního uživatele (bez práv správce). |
| **macOS** (Apple Silicon M1 a novější) | `Taxfolio-<verze>-macOS.dmg` | otevřít a přetáhnout aplikaci do složky Aplikace |
| **Linux** (x86_64; Ubuntu 24.04, Debian 13, Fedora 40 a novější) | `Taxfolio-<verze>-x86_64.AppImage` | povolit spuštění (`chmod +x` nebo Vlastnosti → Spustitelný) a spustit |

**Instalátory zatím nejsou digitálně podepsané**, systém proto při prvním spuštění varuje:
- **Windows:** „Systém Windows ochránil váš počítač“ → *Další informace* → *Přesto spustit*.
- **macOS:** aplikaci poprvé otevřete pravým tlačítkem → *Otevřít* → *Otevřít*
  (nebo Nastavení systému → Soukromí a zabezpečení → *Přesto otevřít*).
- **Linux:** bez varování. Pokud AppImage nejde spustit, chybí knihovna FUSE (`sudo apt install libfuse2`).

**Nové verze:** aplikace jednou denně ověří na GitHubu, zda je k dispozici novější verze, a v dolní liště
nabídne odkaz ke stažení (lze vypnout v Nastavení → Obecné; tam je i aktuální verze a tlačítko
*Zkontrolovat teď*). Novou verzi stačí nainstalovat přes starou – **data zůstávají** v uživatelském
adresáři a instalace ani odinstalace je nemaže.

### Z kódu (Linux, pro vývojáře)

Předpoklad: [uv](https://docs.astral.sh/uv/) a složka `~/.local/bin` v `PATH`.

```bash
uv tool install --editable .     # příkazy taxfolio a taxfolio-gui do ~/.local/bin
taxfolio desktop install         # zástupce v nabídce aplikací s ikonou
```

- Aplikace se pak najde v nabídce aplikací jako **„Taxfolio“** a lze ji připnout do docku.
- Díky `--editable` spouští zástupce vždy aktuální kód z této složky. Jen při změně závislostí:
  `uv tool install --editable --reinstall .`
- Odinstalace: `taxfolio desktop uninstall` a `uv tool uninstall taxfolio`.

### Ukončení z konzole

Aplikaci spuštěnou z terminálu lze ukončit **Ctrl+C** nebo signálem **SIGTERM** (`kill <pid>`);
okno se zavře do zlomku sekundy (návratový kód 130, resp. 143).

## Spuštění (vývoj)

```bash
uv sync
uv run taxfolio-gui                      # desktop aplikace
uv run taxfolio import data/*.csv        # import z příkazové řádky
uv run taxfolio batches | trades --year 2025 | status
```

## Podporované exporty z IBKR

| Export | Kde v IBKR | Co přináší |
|---|---|---|
| **Flex Query XML** (doporučeno) | Performance & Reports → Flex Queries → `taxfolio_full` | vše z Activity Statementu na úrovni exekucí + typ příkazu, čas zadání, ID, uzavřené loty s datem nákupu, kurzy |
| Activity Statement (CSV) | Performance & Reports → Statements → Activity, roční, formát CSV | obchody, dividendy, srážková daň, poplatky, vklady, korporátní akce, otevřené pozice, instrumenty |
| Dividend Report (CSV) | Performance & Reports → Tax Documents → Dividend Report | země zdroje dividendy, rozpad srážkové daně |
| FX Income Worksheet (CSV) | Performance & Reports → Tax Documents → FX Income | kurzové zisky/ztráty z držby měn (dle IBKR) |

Pokud jsou pro stejné období načtena data z Flex Query i z Activity Statementu, použijí se
Flex data (Activity Statement nemá typ příkazu ani ID obchodu).

### Nastavení Flex Query `taxfolio_full`
Activity Flex Query, formát **XML**, Date `yyyyMMdd`, Time `HHmmss`, oddělovač `;`.
Sekce (u každé *Select All* polí a **Save**): Account Information, Trades (Execution, Closed Lots,
Orders), Cash Transactions (Detail), Corporate Actions, Open Positions (Summary + Lot),
Financial Instrument Information, Transfers, Change in Dividend Accruals, Conversion Rates.
Jeden běh pokryje max. 365 dní – spouštějte po kalendářních letech.

### Důvod obchodu
Odvozuje se z typu příkazu (Flex Query): `STP`/`TRAIL` → stop-loss; limitní příkaz čekající ≥ 5 min
a uzavřený v zisku → take-profit; ostatní uzavírací příkazy → ruční výstup. Klíčová slova
`SL`/`TP` v poli Order Reference (TWS) mají přednost.

## Zdroje dat a aktualizace

Data se aktualizují **jedním tlačítkem** ze zdrojů nastavených v **Nastavení → Zdroje dat**
(*Přidat… / Upravit… / Odebrat*). Každý zdroj má typ, název, nastavení a přepínač *Zahrnout do aktualizace*;
tabulka ukazuje, zda je zdroj připravený, nebo co chybí.

| Typ zdroje | Nastavení | Co dělá při aktualizaci |
|---|---|---|
| **IBKR – Flex Web Service** | Query ID (číslo dotazu `taxfolio_full`), token | stáhne výpis za zvolené období a naimportuje ho |
| **Složka s exporty (IBKR, XTB)** | složka, masky souborů (výchozí `*.csv *.xml *.xlsx`) | naimportuje soubory, které ještě nebyly importovány (podle obsahu) |

Zdrojů může být víc (např. dva účty IBKR a složka s exporty z XTB). **Tokeny se ukládají jen do systémové
klíčenky** (pod id zdroje), nikdy do databáze; odebráním zdroje se smaže i jeho token. Nastavení z dřívějších
verzí (jedno Query ID + token) se při prvním spuštění převede na zdroj „IBKR“.

**Import → Aktualizovat ze zdrojů**
- *Zdroj:* všechny zapnuté, nebo jen jeden.
- *Období* (pro IBKR): **letošní rok** (výchozí, do včerejška), jednotlivý starší rok, **všechny roky**
  od nejstaršího importovaného, nebo *podle nastavení Flex Query*. IBKR dovolí max. 365 dní na požadavek,
  proto se stahuje po jednom výpisu na rok (přestupný rok ve dvou částech) – překryvy se deduplikují.
- Složky období nepoužívají – berou všechny nové soubory.
- Chyba jednoho zdroje (např. chybí token) nezastaví ostatní; výsledek každého zdroje je v logu.
- Během aktualizace se tlačítko změní na **Zastavit** – okno je ihned volné, rozpracovaný požadavek se ukončí
  nejpozději po 30 s (časový limit spojení). Stahování běží na pozadí, okno nezamrzá.
- Kurzy ČNB a ECB se stahují **na pozadí** (při spuštění, po importu a tlačítkem v Nastavení); stav je
  v dolní liště. Přehledy a daně používají uložené kurzy, takže výpadek sítě okno nezablokuje; při chybě
  se stahování zopakuje za 5 minut.
- Stažené výpisy IBKR se ukládají do `flex-downloads/` vedle databáze.

Jednotlivé soubory lze dál přidat ručně (*Přidat soubory…*) nebo přetáhnout do okna.
Importy v historii lze **vybrat po více** (Ctrl / Shift) a smazat tlačítkem *Smazat vybrané importy* nebo klávesou Delete
– odstraní se i záznamy, které přinesly.

### IBKR Flex Web Service – první nastavení
1. Client Portal → Settings → **Flex Web Service**: zapnout a vygenerovat token.
2. V aplikaci: Nastavení → Zdroje dat → *Přidat…* → typ *IBKR – Flex Web Service*, Query ID a token.
3. Import → *Aktualizovat ze zdrojů*.

### Příkazová řádka
```bash
taxfolio sources                          # zdroje a jejich stav
taxfolio sync                             # aktualizovat ze všech zapnutých zdrojů (období podle Flex Query)
taxfolio sync --year current              # letošní rok
taxfolio sync --year 2023-2026 --source "IBKR hlavní účet"
taxfolio flex-token set --source "IBKR hlavní účet"   # uložit token zdroje IBKR do klíčenky
taxfolio undo 12 13 14                    # smazat importy podle čísla (taxfolio batches)
```
Token lze předat i proměnnou `IBKR_FLEX_TOKEN` (použije se pro zdroje IBKR bez uloženého tokenu).

## Podporované exporty z XTB

| Export | Kde v xStation 5 | Stav |
|---|---|---|
| **Peněžní operace – CSV** (starší formát `ID;Type;Time;Symbol;Comment;Amount`) | Historie účtu → Peněžní operace → Export → CSV | podporováno |
| **Peněžní operace – CSV** (novější formát `Type;Ticker;Instrument;Time;Amount;ID;Comment;Product` s hlavičkou účtu) | Historie účtu → Peněžní operace → Export | podporováno (`;` + desetinná čárka i `,` + tečka) |
| **Výpis v Excelu (XLSX)** – list „Cash Operations“ | Historie účtu → export do Excelu | podporováno (ostatní listy se nečtou) |
| Export (new) – ZIP | Historie účtu → Peněžní operace → Export (new) | zatím ne – formát neověřen, rozbalte a zkuste CSV uvnitř |
| Uzavřené / otevřené pozice (listy „Closed/Open Positions“) | Historie účtu | ne – obchody se berou z peněžních operací |

Soubor stačí přidat v záložce **Import** stejně jako výpisy z IBKR – formát se pozná automaticky.

**Co se načte**

| Operace v XTB | V aplikaci |
|---|---|
| Nákup / prodej akcie nebo ETF (`Stocks/ETF purchase/sale`, komentář `OPEN BUY 10 @ 50.00`, dílčí plnění `34/42.5658`) | obchod – FIFO, časový test, daně ČR i SR, deník |
| Poplatky k obchodu (`Commission`, `SEC fee`, `Tax IFTT`) | připočtou se k obchodu se stejným symbolem a časem (výdaj), jinak jako poplatek |
| Dividenda (`Dividend`) a srážková daň (`Withholding tax`) | dividenda se zápočtem srážky; spárují se podle symbolu a času výplaty |
| Úroky z volných prostředků a jejich daň | úrok / srážková daň z úroku |
| Vklady a výběry | čisté vklady v Přehledu |
| Převody mezi účty XTB | uloží se, do vkladů se nepočítají |

**Co se nenačte** (import na to upozorní)

- CFD a forex (`Profit/Loss (FX/CFD)`, `Swap`, `Rollover`, `Close trade`) včetně dividendových úprav indexových CFD (`US30.cash`).
- Spin-offy (`Spin off`) – je potřeba je doplnit ručně.
- Nákupy na krátko (`OPEN SELL`).

**Na co pamatovat**

- **Měna:** XTB uvádí částky v měně účtu, už včetně poplatku za konverzi měny (0,5 %). Obchody se proto
  ukládají v měně účtu a cena v deníku je přepočtená (např. akcie z USA na EUR účtu má cenu v EUR).
- **Měna účtu** se bere z hlavičky souboru, z názvu souboru (např. `EUR_cash.csv`) nebo se odvodí
  z obchodů na burze v měně účtu. Když nejde zjistit, import požádá o přejmenování souboru.
- **Účet** se jmenuje `XTB-<číslo účtu>` (číslo z hlavičky nebo z názvu souboru `account_51234567_…`);
  pokud číslo chybí, `XTB-<měna>`. Pozice z IBKR a XTB se v FIFO nepárují dohromady.
- **Bez ISIN:** stát zdroje dividendy se odhaduje podle přípony symbolu (`.US` → USA, `.DE` → Německo,
  `.UK`, `.PL`, `.CZ`…). U ETF je to často špatně (ETF na německé burze bývá irské) – import upozorní,
  zkontrolujte to.
- **SR:** burzy XTB (podle přípony symbolu) se považují za regulované trhy, takže platí osvobození po 1 roce.
- Opakovaný import stejného nebo překrývajícího se souboru nic nezdvojí.
- Formát byl ověřen jen na veřejném anonymizovaném vzorku a syntetických testech; při prvním importu
  vlastních dat zkontrolujte upozornění.

## Funkce

| Záložka | Co dělá |
|---|---|
| Přehled | klíčová čísla (hodnota portfolia, nerealizovaný a realizovaný P/L, úspěšnost, dividendy, poplatky, vklady), grafy P/L a dividend po měsících, P/L podle titulu, složení portfolia, dividendy podle společnosti (graf + tabulka), výsledky podle důvodu výstupu; měna CZK / EUR / USD |
| Obchodní deník | všechny exekuce, důvod obchodu (vstup / stop-loss / take-profit / ruční výstup), filtry, hledání |
| Realizace (FIFO) | spárované prodeje s nákupy, P/L v měně, CZK (ČNB denní / jednotný kurz) a EUR (ECB), kontrola proti IBKR |
| Daně | výběr země (ČR / SR). ČR: ř. 38, ř. 40, Příloha 2 a 3, časový test 3 roky, limit 100 000 Kč, zápočet daně. SR: DP typ B, 1 rok + regulovaný trh, 500 €, dividendy dle roku zisku, zdravotné (odhad). Záložka **Lze prodat bez daně**: tituly, které už splňují časový test – kolik kusů, od kdy, nezdaněný zisk podle poslední ceny, kdy se osvobodí další kusy. Export XLSX/PDF |
| Simulace prodeje | daňový dopad prodeje k danému dni v ČR i SR, kdy bude prodej osvobozen; grafy daně bez / s prodejem (žlutě zvýšení, zeleně úspora) a dopadu stejného prodeje v pozdějších dnech (časové testy, nový rok) |
| Import | stažení přes Flex Web Service, soubory z IBKR (dialog / přetažení), historie, vrácení importu |
| Nastavení | jazyk (čeština, slovenčina, English); výchozí země zdanění; Flex Query ID a token (systémová klíčenka); zdroj kurzu pro každou měnu (ČNB denní, jednotný kurz GFŘ, ECB, IBKR, pevný kurz) s náhledem aktuální hodnoty |

```bash
uv run taxfolio tax-cz 2025 --czk GFR_ANNUAL --export podklady-2025.pdf
uv run taxfolio tax-sk 2025 --export podklady-2025.xlsx
```

## Vzhled

Moderní jednotný vzhled (Qt styl Fusion + vlastní styl v `ui/theme.py`): karty se zaoblenými rohy, ploché
záložky, zvýrazněné hlavní tlačítko na každé obrazovce, čisté tabulky a tenké posuvníky. Barvy grafů
a rozhraní vycházejí z jedné palety.

**Nastavení → Obecné → Vzhled:** *Podle systému* (výchozí), *Světlý* nebo *Tmavý*. Po uložení se okno
přestaví v nových barvách.

## Jazyky

Zdrojovým jazykem je čeština: texty v kódu jsou česky a obalené `_()` (resp. `N_()` v tabulkách
na úrovni modulu). Překlady jsou v `src/taxfolio/i18n/sk.py` a `en.py` (klíč = český text).

```bash
uv run python tools/i18n_extract.py --missing en   # texty bez anglického překladu
```

Test `tests/test_i18n.py` hlídá úplnost katalogů, zbytečné položky a shodu `{zástupných}` hodnot.
CLI zůstává česky.

## Vývoj

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

`data_examples/` je v `.gitignore` – obsahuje reálná data účtu a nesmí se commitnout.
Test `tests/test_real_exports.py` je použije, pokud jsou lokálně k dispozici.

### Verze a vydání

Verze se řídí [semantickým verzováním](https://semver.org/) a je uvedena **jen v `pyproject.toml`**
(aplikace ji čte odtud; `taxfolio --version`). Postup vydání:

1. Zvýšit `version` v `pyproject.toml` a doplnit sekci do `CHANGELOG.md`.
2. Commit a tag: `git tag v0.2.0 && git push origin main v0.2.0`.
3. GitHub Actions (`.github/workflows/release.yml`) ověří, že tag odpovídá verzi, spustí testy,
   sestaví instalátory pro Windows, macOS a Linux a zveřejní je jako GitHub Release s poznámkami
   z `CHANGELOG.md`. Uživatelům se nová verze nabídne při příští kontrole.

Zkušební sestavení bez zveřejnění: v GitHubu Actions → *Release* → *Run workflow* (instalátory jsou
v artefaktech běhu). Lokálně: `uv run --group build python packaging/build.py`
(`--bundle-only` jen složka aplikace bez instalátoru).

`test_data/` obsahuje fiktivní portfolio (IBKR 2021–2025 + účet XTB) se scénáři pro ověření daní
a zobrazení více účtů – popis a očekávané výsledky v [test_data/README.md](test_data/README.md),
automaticky ověřuje `tests/test_scenarios.py`.

## Licence

[MIT](LICENSE) © 2026 Robert Vojcik. Přibalené knihovny mají vlastní licence – viz
[packaging/THIRD_PARTY_NOTICES.md](packaging/THIRD_PARTY_NOTICES.md) (Qt / PySide6 je pod LGPL-3.0).

Aplikace je kalkulačka podkladů, ne daňové poradenství; výsledky ověřte před podáním přiznání.
