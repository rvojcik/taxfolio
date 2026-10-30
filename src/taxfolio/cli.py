"""Command line interface: ``taxfolio import|batches|undo|trades|status``."""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine

from taxfolio import __version__
from taxfolio.fx.converter import CzkMethod
from taxfolio.services import import_service, queries, rates_service, realized
from taxfolio.storage.db import default_db_path, open_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="taxfolio")
    parser.add_argument("--db", type=Path, default=None, help=f"databáze (výchozí {default_db_path()})")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_import = sub.add_parser("import", help="importovat soubory z IBKR")
    p_import.add_argument("files", nargs="+", type=Path)
    sub.add_parser("batches", help="historie importů")
    p_undo = sub.add_parser("undo", help="vrátit import(y)")
    p_undo.add_argument("batch_ids", type=int, nargs="+", metavar="batch_id")
    p_trades = sub.add_parser("trades", help="vypsat obchody")
    p_trades.add_argument("--year", type=int)
    p_trades.add_argument("--asset", help="STK, CASH, BOND …")
    sub.add_parser("status", help="počty záznamů v databázi")
    sub.add_parser("sources", help="zdroje dat (nastavují se v aplikaci: Nastavení → Zdroje dat)")
    p_sync = sub.add_parser(
        "sync", aliases=["flex-sync"], help="aktualizovat data ze zdrojů (IBKR Flex Web Service, složky)"
    )
    p_sync.add_argument("--source", help="jen zdroj s tímto názvem (výchozí: všechny zapnuté)")
    p_sync.add_argument(
        "--year",
        nargs="+",
        metavar="ROK",
        help="rok nebo rozsah let (např. 2025, 2023-2026, current = letošní rok); "
        "bez parametru období nastavené ve Flex Query",
    )
    p_tok = sub.add_parser("flex-token", help="uložit/smazat token zdroje IBKR v systémové klíčence")
    p_tok.add_argument("action", choices=["set", "delete", "status"])
    p_tok.add_argument("--source", help="název zdroje IBKR (nutný, je-li jich víc)")
    p_rates = sub.add_parser("rates", help="stáhnout kurzy ČNB a ECB")
    p_rates.add_argument("years", nargs="*", type=int, help="roky (výchozí: roky s obchody)")
    p_real = sub.add_parser("realized", help="realizované zisky/ztráty (FIFO)")
    p_real.add_argument("--year", type=int)
    p_real.add_argument("--czk", choices=[m.value for m in CzkMethod], default=CzkMethod.CNB_DAILY.value)
    p_cz = sub.add_parser("tax-cz", help="podklady pro daňové přiznání v ČR")
    p_cz.add_argument("year", type=int)
    p_cz.add_argument("--czk", choices=[m.value for m in CzkMethod], default=CzkMethod.CNB_DAILY.value)
    p_cz.add_argument("--export", type=Path, help="uložit podklady do .xlsx nebo .pdf")
    p_sk = sub.add_parser("tax-sk", help="podklady pre daňové priznanie v SR")
    p_sk.add_argument("year", type=int)
    p_sk.add_argument(
        "--500-used",
        dest="used_elsewhere",
        action="store_true",
        help="oslobodenie 500 € už uplatnené pri inom § 8 príjme",
    )
    p_sk.add_argument("--export", type=Path, help="uložiť podklady do .xlsx alebo .pdf")

    p_desk = sub.add_parser("desktop", help="přidat/odebrat aplikaci v nabídce aplikací (Linux)")
    p_desk.add_argument("action", choices=["install", "uninstall"])

    sub.add_parser("check-update", help="zjistit, zda je na GitHubu novější verze")

    args = parser.parse_args(argv)
    if args.cmd == "check-update":
        from taxfolio.services import updates

        try:
            release = updates.newer_release()
        except (OSError, ValueError, KeyError) as exc:  # URLError is an OSError
            print(f"CHYBA  Novou verzi se nepodařilo zjistit: {exc}")
            return 1
        if release is None:
            print(f"Používáte nejnovější verzi {__version__}.")
            return 0
        print(f"Je k dispozici nová verze {release.version} (máte {__version__}): {release.url}")
        return 0
    if args.cmd == "desktop":
        from taxfolio import desktop

        try:
            paths = desktop.install() if args.action == "install" else desktop.uninstall()
        except OSError as exc:
            print(f"CHYBA  {exc}")
            return 1
        verb = "Vytvořeno" if args.action == "install" else "Odstraněno"
        for path in paths:
            print(f"{verb}: {path}")
        return 0
    engine = open_db(args.db)

    if args.cmd == "import":
        exit_code = 0
        for path in args.files:
            try:
                res = import_service.import_file(engine, path)
            except ValueError as exc:
                print(f"CHYBA  {exc}")
                exit_code = 1
                continue
            detail = ", ".join(f"{k}: +{v}" for k, v in res.new_rows.items())
            print(
                f"OK     {res.file_name} [{res.source_format}] nové {res.total_new}, "
                f"duplicitní {res.total_duplicate} ({detail})"
            )
            for w in res.warnings:
                print(f"       ⚠ {w}")
        return exit_code
    if args.cmd == "batches":
        for b in queries.list_batches(engine):
            print(
                f"{b.id:>4}  {b.imported_at:%Y-%m-%d %H:%M}  {b.account_id}  {b.source_format:<32} "
                f"{b.period_start}…{b.period_end}  +{b.rows_new}/={b.rows_duplicate}  {b.file_name}"
            )
        return 0
    if args.cmd == "undo":
        import_service.undo_imports(engine, args.batch_ids)
        print(f"Odstraněno importů: {len(args.batch_ids)} ({', '.join(map(str, args.batch_ids))}).")
        return 0
    if args.cmd == "trades":
        for t in queries.list_trades(engine, year=args.year, asset_class=args.asset):
            print(
                f"{t.trade_datetime:%Y-%m-%d %H:%M}  {t.side:<4} {t.symbol:<10} {t.quantity:>14} @ "
                f"{t.price:<14} {t.currency}  P/L {t.realized_pnl or 0:>10}  {t.codes}"
            )
        return 0
    if args.cmd == "rates":
        fetched = rates_service.download_rates(engine, args.years or queries.available_years(engine))
        print("Staženo: " + (", ".join(fetched) or "nic, vše je aktuální"))
        return 0
    if args.cmd == "realized":
        return _realized(engine, args.year, CzkMethod(args.czk))
    if args.cmd == "tax-cz":
        return _tax_cz(engine, args.year, CzkMethod(args.czk), args.export)
    if args.cmd == "tax-sk":
        return _tax_sk(engine, args.year, args.used_elsewhere, args.export)
    if args.cmd == "sources":
        return _sources(engine)
    if args.cmd in ("sync", "flex-sync"):
        return _sync(engine, args.source, args.year)
    if args.cmd == "flex-token":
        return _flex_token(engine, args.action, args.source)
    if args.cmd == "status":
        for name, count in queries.table_counts(engine).items():
            print(f"{name:<18} {count}")
        return 0
    return 2


def _realized(engine: Engine, year: int | None, method: CzkMethod) -> int:
    rates_service.ensure_rates(engine, queries.available_years(engine))
    report = realized.compute_fifo(engine)
    rows = realized.realized_rows(report, rates_service.load_converter(engine), method, year)
    for r in sorted(rows, key=lambda r: r.match.close_datetime):
        m = r.match
        print(
            f"{m.close_datetime:%Y-%m-%d}  {m.symbol:<8} {m.quantity:>8}  nákup {m.open_datetime:%Y-%m-%d} "
            f"({m.holding_days:>4} d)  P/L {m.pnl:>10.2f} {m.currency}  "
            f"{r.pnl_czk:>12.2f} CZK  {r.pnl_eur:>10.2f} EUR"
        )
    gains = sum((r.pnl_czk for r in rows if r.pnl_czk > 0), Decimal(0))
    losses = sum((r.pnl_czk for r in rows if r.pnl_czk < 0), Decimal(0))
    print(f"Zisky {gains:.2f} CZK, ztráty {losses:.2f} CZK, saldo {gains + losses:.2f} CZK ({method.value})")
    issues = realized.check_against_ibkr(engine, report)
    print(f"Kontrola s IBKR: {'OK' if not issues else f'{len(issues)} rozdílů'}")
    for w in [*report.result.warnings, *(f"{d.symbol} {d.close_datetime} {d.detail}" for d in issues)]:
        print(f"  ⚠ {w}")
    return 0 if not issues else 1


def _tax_cz(engine: Engine, year: int, method: CzkMethod, export_to: Path | None) -> int:
    from taxfolio.reports.export import export
    from taxfolio.reports.tax_documents import cz_document
    from taxfolio.services.tax_cz import build_cz_report

    report, calendar = build_cz_report(engine, year, method)
    if export_to:
        export(cz_document(report, calendar), export_to)
        print(f"Podklady uloženy do {export_to}")
    print(f"Daň z příjmů FO {year} – ČR ({method.value})")
    for line in report.form_lines():
        print(f"  {line.form:<26} {line.label:<52} {line.value:>14,.2f}  {line.note}")
    print(f"  Odhad daně {report.rules.rate:.0%}: {report.tax_total:,.2f} Kč")
    print(
        f"  Odhad daně {report.rules.higher_rate:.0%} (celý základ nad {report.rules.higher_rate_threshold:,.0f} Kč): "
        f"{report.tax_total_higher:,.2f} Kč"
    )
    for w in report.warnings:
        print(f"  ⚠ {w}")
    return 0


def _tax_sk(engine: Engine, year: int, used_elsewhere: bool, export_to: Path | None) -> int:
    from taxfolio.reports.export import export
    from taxfolio.reports.tax_documents import sk_document
    from taxfolio.services.tax_sk import build_sk_report

    report, calendar = build_sk_report(engine, year, exemption_used_elsewhere=used_elsewhere)
    if export_to:
        export(sk_document(report, calendar), export_to)
        print(f"Podklady uložené do {export_to}")
    print(f"Daň z príjmov FO {year} – SR")
    for line in report.form_lines():
        print(f"  {line.form:<44} {line.label:<40} {line.value:>12,.2f}  {line.note}")
    print(
        f"  Odhad dane: {report.tax_total:,.2f} €, "
        f"zdravotné poistenie (odhad): {report.health_insurance:,.2f} €"
    )
    for w in report.warnings:
        print(f"  ⚠ {w}")
    return 0


def _parse_years(values: list[str]) -> list[tuple[int, int]]:
    """'2025', '2023-2026', 'current' → (first, last) year ranges."""
    current = date.today().year
    out = []
    for value in values:
        first, _sep, last = value.replace("current", str(current)).partition("-")
        out.append((int(first), int(last or first)))
    return out


def _sources(engine: Engine) -> int:
    from taxfolio.services.sources import load_sources

    sources = load_sources(engine)
    if not sources:
        print("Žádné zdroje dat – přidejte je v aplikaci: Nastavení → Zdroje dat.")
    for s in sources:
        missing = ", ".join(f.label for f in s.missing())
        state = f"chybí: {missing}" if missing else "připraveno"
        print(f"{'✔' if s.enabled else '–'} {s.name:<24} {s.spec.title:<30} {state}")
    return 0


def _sync(engine: Engine, source_name: str | None, years: list[str] | None = None) -> int:
    from taxfolio.services import flex_sync, source_sync
    from taxfolio.services.sources import load_sources

    sources = [s for s in load_sources(engine) if s.enabled and source_name in (None, s.name)]
    if not sources:
        print("Žádný zdroj dat – přidejte ho v aplikaci: Nastavení → Zdroje dat.")
        return 2
    try:
        periods = (
            [flex_sync.years_period(a, b) for a, b in _parse_years(years)]
            if years
            else [flex_sync.QUERY_PERIOD]
        )
    except ValueError as exc:
        print(f"CHYBA  {exc}")
        return 2
    failed = False
    for period in periods:
        for r in source_sync.sync_all(engine, sources, period, progress=print):
            failed |= bool(r.error or r.import_errors)
            if r.error:
                print(f"CHYBA  {r.source.name}: {r.error}")
            for res in r.imports:
                print(
                    f"OK     {r.source.name}: {res.file_name}: nové {res.total_new}, duplicitní {res.total_duplicate}"
                )
                for w in res.warnings:
                    print(f"       ⚠ {w}")
            for name, error in r.import_errors:
                print(f"CHYBA  {name}: {error}")
    return 1 if failed else 0


def _flex_token(engine: Engine, action: str, source_name: str | None) -> int:
    import getpass

    from taxfolio.services import secrets
    from taxfolio.services.sources import SourceType, load_sources

    candidates = [
        s for s in load_sources(engine) if s.type is SourceType.IBKR_FLEX and source_name in (None, s.name)
    ]
    if len(candidates) != 1:
        print(
            "Zadejte --source s názvem zdroje IBKR (taxfolio sources)." if candidates else "Žádný zdroj IBKR."
        )
        return 2
    (source,) = candidates
    if action == "set":
        secrets.set_secret(source.id, "token", getpass.getpass(f"Token Flex Web Service ({source.name}): "))
        print("Token uložen do systémové klíčenky.")
    elif action == "delete":
        secrets.delete_secret(source.id, "token")
        print("Token smazán.")
    else:
        print("Token je uložen." if secrets.get_secret(source.id, "token") else "Token není uložen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
