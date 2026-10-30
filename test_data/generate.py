"""Generate fictional IBKR Flex Query statements for testing the tax calculations.

Run from the project root:  uv run python test_data/generate.py
Writes test_data/flex_<year>.xml (one statement per calendar year, like real IBKR exports) and
test_data/expected_cz.json with the Czech results computed here, independently of the app.

Everything is invented: account, companies, ISINs, prices. Scenarios: test_data/README.md.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import quoteattr

OUT = Path(__file__).parent
ACCOUNT = "U9999001"
FEE = Decimal(50)  # CZK commission per trade (USD trades: 1 USD)
D = Decimal


@dataclass(frozen=True)
class Company:
    symbol: str
    name: str
    isin: str
    currency: str = "CZK"
    exchange: str = "PRA"  # Prague Stock Exchange – a regulated market
    country: str = "CZ"


def cz(symbol: str, name: str, n: int) -> Company:
    return Company(symbol, name, f"CZ{9000000000 + n:010d}")


# Year 1 (2021): ten companies
A = [
    cz("ALFA", "ALFA STROJIRNY AS", 1),
    cz("BRIZ", "BRIZOLA POTRAVINY AS", 2),
    cz("CEDR", "CEDR DREVOZPRACUJICI AS", 3),
    cz("DUNA", "DUNA ENERGIE AS", 4),
    cz("EMIL", "EMIL LOGISTIKA AS", 5),
    cz("FAZE", "FAZE ELEKTRO AS", 6),
    cz("GRAN", "GRANIT STAVBY AS", 7),
    cz("HROM", "HROM TELEKOMUNIKACE AS", 8),
    cz("IRIS", "IRIS OPTIKA AS", 9),
    cz("JASM", "JASMIN KOSMETIKA AS", 10),
]
# Year 2 (2022): twenty other companies
B = [
    cz(sym, name, 100 + i)
    for i, (sym, name) in enumerate(
        [
            ("KAMN", "KAMENOLOMY KRAL AS"),
            ("LIPA", "LIPA NABYTEK AS"),
            ("MOST", "MOSTARNA OSTRAVA AS"),
            ("NOVA", "NOVA MEDIA AS"),
            ("ORLI", "ORLICE TEXTIL AS"),
            ("PRAM", "PRAMEN NAPOJE AS"),
            ("RYBA", "RYBNIKARSTVI JIH AS"),
            ("SOVA", "SOVA SOFTWARE AS"),
            ("TRAM", "TRAMVAJE VYROBA AS"),
            ("UHEL", "UHELNE DOLY SEVER AS"),
            ("VRBA", "VRBA ZAHRADNICTVI AS"),
            ("ZLAT", "ZLATNICTVI PRAHA AS"),
            ("BOBR", "BOBR STAVEBNINY AS"),
            ("CIPR", "CIPRIS FARMACIE AS"),
            ("DRAK", "DRAK HRACKY AS"),
            ("EKOL", "EKOLOGIE RECYKLACE AS"),
            ("FLOR", "FLORA KVETINY AS"),
            ("GOLF", "GOLF RESORTY AS"),
            ("HUSA", "HUSA DRUBEZ AS"),
            ("ILKA", "ILKA OBUV AS"),
        ],
        start=1,
    )
]
# Extra scenarios
GAMMA = Company("GAMR", "GAMMA ROBOTICS INC", "US9999990001", "USD", "NASDAQ", "US")
ZETA = Company("ZETM", "ZETA MINING CORP", "US9999990002", "USD", "PINK", "US")  # OTC, not regulated
DELTA = Company("DLCH", "DELTA CHEMIE AG", "DE9999990003", "EUR", "IBIS", "DE")
EPSI = Company("EPSI", "EPSILON SOLAR AS", "CZ9000000200")
COMPANIES = {c.symbol: c for c in [*A, *B, GAMMA, ZETA, DELTA, EPSI]}


@dataclass(frozen=True)
class Trade:
    when: datetime
    symbol: str
    quantity: Decimal  # + buy, - sell
    price: Decimal
    note: str  # scenario id from README.md

    @property
    def company(self) -> Company:
        return COMPANIES[self.symbol]

    @property
    def fee(self) -> Decimal:
        return FEE if self.company.currency == "CZK" else D(1)

    @property
    def proceeds(self) -> Decimal:
        return -self.quantity * self.price


def t(day: str, symbol: str, qty: int | str, price: int | str, note: str, hour: str = "10:00:00") -> Trade:
    return Trade(datetime.fromisoformat(f"{day} {hour}"), symbol, D(qty), D(price), note)


TRADES: list[Trade] = [
    # --- 2021: ten buys, 50 shares each (S1)
    *[t(f"2021-{m:02d}-15", c.symbol, 50, 180, "S1") for m, c in zip(range(2, 12), A, strict=True)],
    # --- 2022: twenty buys, 100 shares each (S2); the last three late in the year
    *[t(f"2022-{(i % 9) + 2:02d}-{10 + i:02d}", c.symbol, 100, 90, "S2") for i, c in enumerate(B[:17])],
    t("2022-10-12", "HUSA", 100, 90, "S2"),
    t("2022-11-15", "ILKA", 100, 90, "S2"),
    t("2022-12-07", "GOLF", 100, 90, "S2"),
    # extra buys
    t("2022-12-01", "ALFA", 50, 200, "E1"),  # second lot of ALFA → split sale in 2025
    t("2022-09-15", "GAMR", 10, 50, "E2"),  # USD stock, NASDAQ
    t("2022-05-16", "ZETM", 1000, 2, "E3"),  # USD stock, OTC (not a regulated market)
    t("2022-04-20", "DLCH", 20, 80, "E5"),  # EUR stock (German dividend)
    # --- 2024: one small sale → all exempt thanks to the 100 000 Kč limit (E6)
    t("2024-06-03", "KAMN", -100, 150, "E6"),
    # --- 2025: the five sales of the main scenario (S3)
    t("2025-04-10", "CEDR", -50, 400, "S3"),  # bought 2021-04-15 → > 3 years, exempt (CZ)
    t("2025-05-12", "DUNA", -50, 300, "S3"),  # bought 2021-05-15 → > 3 years, exempt (CZ)
    t("2025-03-14", "HUSA", -100, 400, "S3"),  # bought 2022-10-12 → < 3 years, taxable gain
    t("2025-06-16", "ILKA", -100, 250, "S3"),  # bought 2022-11-15 → < 3 years, taxable gain
    t("2025-07-15", "GOLF", -100, 50, "S3"),  # bought 2022-12-07 → < 3 years, taxable LOSS
    # extra sales in 2025
    t("2025-08-20", "ALFA", -75, 220, "E1"),  # FIFO: 50 from 2021 (exempt) + 25 from 2022 (taxable)
    t("2025-03-20", "GAMR", -10, 80, "E2"),  # USD, < 3 years, taxable; converted at the CNB rate
    t("2025-04-22", "ZETM", -1000, 5, "E3"),  # CZ taxable (< 3 y); SK taxable although > 1 y (OTC)
    t("2025-02-03", "EPSI", 100, 100, "E4"),  # short-term trade within 2025
    t("2025-09-15", "EPSI", -100, 160, "E4"),
]

DEPOSITS = [("2021-01-15", D(100_000)), ("2022-01-10", D(200_000))]

# Year-end market prices (Open Positions): every stock gains 12 % a year since its first purchase
YEARLY_GROWTH = D("1.12")

# (date, symbol, currency, gross, withheld, scenario)
DIVIDENDS = [
    ("2025-05-20", "BRIZ", "CZK", D(1000), D(350), "E7"),  # domestic, 35 % withheld (foreign broker)
    ("2025-06-12", "GAMR", "USD", D(20), D(3), "E7"),  # US, 15 % → fully creditable
    ("2025-05-08", "DLCH", "EUR", D(100), D("26.38"), "E7"),  # DE, 26.375 % → only 15 % creditable
]


# ------------------------------------------------------------------ independent FIFO


@dataclass
class Lot:
    opened: datetime
    quantity: Decimal
    cost: Decimal  # incl. buy fee, in the trade currency
    transaction_id: int


@dataclass
class Sale:
    trade: Trade
    lot_opened: datetime
    quantity: Decimal
    cost: Decimal  # share of the lot cost incl. buy fee
    income: Decimal  # gross sale price share (fee excluded)
    sell_fee: Decimal
    lot_transaction_id: int

    @property
    def held_over_3_years(self) -> bool:
        o, c = self.lot_opened.date(), self.trade.when.date()
        try:
            anniversary = o.replace(year=o.year + 3)
        except ValueError:
            anniversary = o.replace(year=o.year + 3, day=28)
        return c > anniversary


def fifo(trades: list[Trade]) -> tuple[list[Sale], dict[int, int], dict[str, deque[Lot]]]:
    """Sales matched to lots, transaction ids, and the lots still open after the last trade."""
    lots: dict[str, deque[Lot]] = defaultdict(deque)
    sales: list[Sale] = []
    ids: dict[int, int] = {}
    for n, tr in enumerate(sorted(trades, key=lambda x: x.when), start=1):
        ids[id(tr)] = 70000 + n
        if tr.quantity > 0:
            lots[tr.symbol].append(Lot(tr.when, tr.quantity, tr.quantity * tr.price + tr.fee, 70000 + n))
            continue
        left = -tr.quantity
        while left > 0:
            lot = lots[tr.symbol][0]
            take = min(left, lot.quantity)
            share = take / lot.quantity
            cost = (lot.cost * share).quantize(D("0.01"))
            sales.append(
                Sale(
                    tr,
                    lot.opened,
                    take,
                    cost,
                    take * tr.price,
                    (tr.fee * take / -tr.quantity).quantize(D("0.01")),
                    lot.transaction_id,
                )
            )
            lot.quantity -= take
            lot.cost -= cost
            left -= take
            if lot.quantity == 0:
                lots[tr.symbol].popleft()
    return sales, ids, lots


def open_positions(year: int) -> str:
    """Open Positions at 31 Dec of ``year`` (summary per stock), as IBKR reports them."""
    _sales, _ids, lots = fifo([tr for tr in TRADES if tr.when.year <= year])
    rows = []
    for symbol in sorted(lots):
        held = [lot for lot in lots[symbol] if lot.quantity > 0]
        if not held:
            continue
        c = COMPANIES[symbol]
        quantity = sum((lot.quantity for lot in held), D(0))
        cost = sum((lot.cost for lot in held), D(0))
        first = min((tr for tr in TRADES if tr.symbol == symbol and tr.quantity > 0), key=lambda tr: tr.when)
        mark = (first.price * YEARLY_GROWTH ** (year - first.when.year)).quantize(D("0.01"))
        value = quantity * mark
        rows.append(
            "<OpenPosition "
            + a(
                accountId=ACCOUNT,
                currency=c.currency,
                assetCategory="STK",
                symbol=symbol,
                conid=conid(c),
                isin=c.isin,
                reportDate=f"{year}1231",
                position=quantity,
                markPrice=mark,
                positionValue=value,
                costBasisMoney=cost.quantize(D("0.01")),
                fifoPnlUnrealized=(value - cost).quantize(D("0.01")),
                levelOfDetail="SUMMARY",
                openDateTime="",
            )
            + " />"
        )
    return "<OpenPositions>\n" + "\n".join(rows) + "\n</OpenPositions>" if rows else "<OpenPositions />"


# ------------------------------------------------------------------ Flex XML


def a(**attrs: object) -> str:
    return " ".join(f"{k}={quoteattr(str(v))}" for k, v in attrs.items())


def stamp(d: datetime) -> str:
    return d.strftime("%Y%m%d;%H%M%S")


def security(c: Company) -> str:
    return f"<SecurityInfo {a(currency=c.currency, assetCategory='STK', subCategory='COMMON', symbol=c.symbol, description=c.name, conid=conid(c), securityID=c.isin, isin=c.isin, listingExchange=c.exchange, issuerCountryCode=c.country)} />"


def conid(c: Company) -> str:
    return str(900000 + list(COMPANIES).index(c.symbol))


def statement(year: int, sales: list[Sale], ids: dict[int, int]) -> str:
    trades = sorted((tr for tr in TRADES if tr.when.year == year), key=lambda x: x.when)
    rows = []
    for tr in trades:
        c = tr.company
        my_sales = [s for s in sales if s.trade is tr]
        pnl = sum((s.income - s.cost - s.sell_fee for s in my_sales), D(0))
        common = dict(
            accountId=ACCOUNT,
            currency=c.currency,
            fxRateToBase="1" if c.currency == "CZK" else "",
            assetCategory="STK",
            symbol=c.symbol,
            conid=conid(c),
            isin=c.isin,
        )
        rows.append(
            "<Trade "
            + a(
                **common,
                tradeID=ids[id(tr)],
                dateTime=stamp(tr.when),
                quantity=tr.quantity,
                tradePrice=tr.price,
                proceeds=tr.proceeds,
                ibCommission=-tr.fee,
                ibCommissionCurrency=c.currency,
                openCloseIndicator="O" if tr.quantity > 0 else "C",
                notes="",
                cost=(tr.quantity * tr.price + tr.fee) if tr.quantity > 0 else -sum(s.cost for s in my_sales),
                fifoPnlRealized=pnl.quantize(D("0.01")) if my_sales else 0,
                ibOrderID=ids[id(tr)] + 100000,
                transactionID=ids[id(tr)],
                orderReference=tr.note,
                orderTime=stamp(tr.when),
                levelOfDetail="EXECUTION",
                orderType="LMT",
            )
            + " />"
        )
        for s in my_sales:  # IBKR's own lot matching ("Closed Lots") – the app checks against it
            rows.append(
                "<Lot "
                + a(
                    **common,
                    dateTime=stamp(tr.when),
                    quantity=s.quantity,
                    tradePrice=tr.price,
                    openCloseIndicator="C",
                    notes="",
                    cost=s.cost,
                    fifoPnlRealized=(s.income - s.cost - s.sell_fee).quantize(D("0.01")),
                    transactionID=s.lot_transaction_id,
                    openDateTime=stamp(s.lot_opened),
                    levelOfDetail="CLOSED_LOT",
                )
                + " />"
            )

    cash = []
    for n, (day, amount) in enumerate(DEPOSITS):
        if int(day[:4]) == year:
            cash.append(
                "<CashTransaction "
                + a(
                    accountId=ACCOUNT,
                    currency="CZK",
                    fxRateToBase="1",
                    dateTime=day.replace("-", ""),
                    settleDate=day.replace("-", ""),
                    amount=amount,
                    type="Deposits/Withdrawals",
                    description="CASH RECEIPTS / ELECTRONIC FUND TRANSFERS",
                    transactionID=80000 + n,
                    levelOfDetail="DETAIL",
                )
                + " />"
            )
    for n, (day, symbol, ccy, gross, withheld, _note) in enumerate(DIVIDENDS):
        if int(day[:4]) != year:
            continue
        c = COMPANIES[symbol]
        per_share = "1.00"
        base = dict(
            accountId=ACCOUNT,
            currency=ccy,
            fxRateToBase="",
            assetCategory="STK",
            symbol=symbol,
            conid=conid(c),
            isin=c.isin,
            dateTime=f"{day.replace('-', '')};202000",
            settleDate=day.replace("-", ""),
            actionID=81000 + n,
            levelOfDetail="DETAIL",
        )
        desc = f"{symbol}({c.isin}) CASH DIVIDEND {ccy} {per_share} PER SHARE (Ordinary Dividend)"
        cash.append(
            "<CashTransaction "
            + a(
                **base,
                issuerCountryCode=c.country,
                description=desc,
                amount=gross,
                type="Dividends",
                transactionID=82000 + 2 * n,
                exDate=day.replace("-", ""),
            )
            + " />"
        )
        cash.append(
            "<CashTransaction "
            + a(
                **base,
                description=f"{desc} - {c.country} TAX",
                amount=-withheld,
                type="Withholding Tax",
                transactionID=82001 + 2 * n,
            )
            + " />"
        )

    held = {tr.symbol for tr in TRADES if tr.when.year <= year}
    securities = "\n".join(security(COMPANIES[s]) for s in sorted(held))
    return f"""<FlexQueryResponse queryName="taxfolio_full" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="{ACCOUNT}" fromDate="{year}0101" toDate="{year}1231" period="" whenGenerated="{year + 1}0105;080000">
<AccountInformation accountId="{ACCOUNT}" name="Testovaci Ucet" currency="CZK" />
{open_positions(year)}
<Trades>
{chr(10).join(rows)}
</Trades>
<CorporateActions />
<CashTransactions>
{chr(10).join(cash)}
</CashTransactions>
<Transfers />
<SecuritiesInfo>
{securities}
</SecuritiesInfo>
<ConversionRates />
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>
"""


# ------------------------------------------------------------------ expected Czech results


def expected_cz(sales: list[Sale]) -> dict[str, object]:
    """Czech § 10 results per year for the CZK sales; foreign-currency sales listed separately."""
    out: dict[str, object] = {}
    for year in sorted({s.trade.when.year for s in sales}):
        rows = [s for s in sales if s.trade.when.year == year]
        czk = [s for s in rows if s.trade.company.currency == "CZK"]
        foreign = [s for s in rows if s.trade.company.currency != "CZK"]
        gross = sum((s.income for s in czk), D(0))
        exempt = [s for s in czk if s.held_over_3_years]
        taxable = [s for s in czk if not s.held_over_3_years]
        income = sum((s.income for s in taxable), D(0))
        expenses = sum((s.cost + s.sell_fee for s in taxable), D(0))
        out[str(year)] = {
            "czk_gross_income_all_sales": str(gross),
            "czk_exempt_time_test_income": str(sum((s.income for s in exempt), D(0))),
            "czk_taxable_income": str(income),
            "czk_taxable_expenses": str(expenses),
            "czk_taxable_result": str(income - expenses),
            "sales": [
                {
                    "scenario": s.trade.note,
                    "symbol": s.trade.symbol,
                    "sold": s.trade.when.date().isoformat(),
                    "bought": s.lot_opened.date().isoformat(),
                    "quantity": str(s.quantity),
                    "currency": s.trade.company.currency,
                    "income": str(s.income),
                    "expenses": str(s.cost + s.sell_fee),
                    "result": str(s.income - s.cost - s.sell_fee),
                    "cz_time_test_passed": s.held_over_3_years,
                }
                for s in rows
            ],
            "foreign_currency_sales": [s.trade.symbol for s in foreign],
        }
    return out


# ------------------------------------------------------------------ second account: XTB

XTB_ACCOUNT = "51234567"
XTB_FILE = f"xtb_{XTB_ACCOUNT}_cash_operations.csv"

# (time, type, ticker, instrument, amount in EUR, comment, scenario) – amounts in the account
# currency (EUR) incl. XTB's currency conversion, as in real XTB exports
XTB_OPERATIONS = [
    ("2023-03-01 09:00:00", "Deposit", "", "", "5000", "Deposit, id=111", "X1"),
    ("2023-03-02 10:15:00", "Stock purchase", "SAP.DE", "SAP SE", "-1200", "OPEN BUY 10 @ 120.00", "X2"),
    (
        "2023-03-02 15:40:00",
        "Stock purchase",
        "MSFT.US",
        "Microsoft Corp",
        "-1170",
        "OPEN BUY 5 @ 250.00",
        "X3",
    ),
    (
        "2023-06-15 11:00:00",
        "Stock purchase",
        "IUSA.DE",
        "iShares Core S&P 500 UCITS ETF (Dist)",
        "-1000",
        "OPEN BUY 25 @ 40.00",
        "X6",
    ),
    (
        "2023-09-20 14:00:00",
        "Profit/Loss (FX/CFD)",
        "EURUSD",
        "",
        "12,5",
        "Profit of position #685669464",
        "X8",
    ),
    ("2024-01-05 10:00:00", "Free funds interest", "", "", "4,2", "Free-funds Interest 2023-12", "X7"),
    (
        "2024-01-05 10:00:00",
        "Free funds interest tax",
        "",
        "",
        "-0,8",
        "Free-funds Interest Tax 2023-12",
        "X7",
    ),
    ("2024-05-20 11:00:00", "Dividend", "SAP.DE", "SAP SE", "22", "SAP.DE EUR 2.2000/ SHR", "X4"),
    ("2024-05-20 11:00:00", "Withholding tax", "SAP.DE", "SAP SE", "-5,8", "SAP.DE EUR WHT 26.375%", "X4"),
    ("2024-06-13 11:00:00", "Dividend", "MSFT.US", "Microsoft Corp", "3,4", "MSFT.US USD 0.7500/ SHR", "X4"),
    (
        "2024-06-13 11:00:00",
        "Withholding tax",
        "MSFT.US",
        "Microsoft Corp",
        "-0,51",
        "MSFT.US USD WHT 15%",
        "X4",
    ),
    ("2024-09-10 10:30:00", "Stock sale", "SAP.DE", "SAP SE", "900", "CLOSE BUY 5 @ 180.00", "X2"),
    (
        "2024-12-27 11:00:00",
        "Dividend",
        "IUSA.DE",
        "iShares Core S&P 500 UCITS ETF (Dist)",
        "7,5",
        "IUSA.DE USD 0.3000/ SHR",
        "X6",
    ),
    ("2025-01-10 09:30:00", "Stock purchase", "CEZ.CZ", "CEZ", "-800", "OPEN BUY 20 @ 1000.00", "X5"),
    ("2025-03-05 16:00:00", "Stock sale", "MSFT.US", "Microsoft Corp", "1850", "CLOSE BUY 5 @ 400.00", "X3"),
    ("2025-03-05 16:00:00", "Commission", "MSFT.US", "Microsoft Corp", "-3,7", "Commission", "X3"),
    ("2025-06-10 10:00:00", "Stock sale", "CEZ.CZ", "CEZ", "880", "CLOSE BUY 20 @ 1100.00", "X5"),
    ("2025-07-01 08:00:00", "Withdrawal", "", "", "-500", "Withdrawal to bank account", "X1"),
]


def xtb_cash_operations() -> str:
    """XTB 'Cash Operations' export, current layout: metadata rows, ';' and decimal comma."""
    lines = [
        f"Account number;{XTB_ACCOUNT}",
        "Currency;EUR",
        "Date from (UTC);2023-01-01 00:00:00",
        "Date to (UTC);2025-12-31 23:59:59",
        "Type;Ticker;Instrument;Time;Amount;ID;Comment;Product",
    ]
    total = D(0)
    for n, (when, kind, ticker, name, amount, comment, _scenario) in enumerate(XTB_OPERATIONS, start=1):
        lines.append(f"{kind};{ticker};{name};{when};{amount};{600000 + n};{comment};My Trades")
        total += D(amount.replace(",", "."))
    lines.append(f"Total;;;;{str(total).replace('.', ',')};;;")
    return "\n".join(lines) + "\n"


def main() -> None:
    sales, ids, _lots = fifo(TRADES)
    for year in range(2021, 2026):
        (OUT / f"flex_{year}.xml").write_text(statement(year, sales, ids), encoding="utf-8")
    (OUT / "expected_cz.json").write_text(
        json.dumps(expected_cz(sales), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / XTB_FILE).write_text(xtb_cash_operations(), encoding="utf-8")
    print(f"Written to {OUT}: flex_2021.xml … flex_2025.xml, expected_cz.json, {XTB_FILE}")


if __name__ == "__main__":
    main()
