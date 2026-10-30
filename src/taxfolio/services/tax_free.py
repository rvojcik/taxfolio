"""Holdings that can be sold today without tax: the lots that already passed the time test.

Sales are matched FIFO (oldest purchase first) and the time test depends only on the purchase
date, so the exempt lots of a position are always its oldest ones – selling up to the exempt
quantity consumes nothing else. Works for both countries: CZ passes every lot (3 years),
SK only lots on a regulated market (1 year).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine

from taxfolio.engine.lots import Lot
from taxfolio.services import realized
from taxfolio.tax.cz import time_test_date
from taxfolio.tax.rules_loader import MissingRulesError, load_cz, load_sk

ZERO = Decimal(0)


@dataclass(frozen=True)
class CalendarLot:
    lot: Lot
    description: str
    exempt_from: date
    eligible: bool = True  # SK: on a regulated market (otherwise never exempt)


@dataclass(frozen=True)
class TaxFreePosition:
    key: str
    symbol: str
    description: str
    currency: str
    quantity: Decimal  # can be sold tax-free today
    held: Decimal  # the whole position
    exempt_since: date  # the latest of the exempt lots passed the test on this day
    cost: Decimal  # of the tax-free quantity, incl. buy commissions, in ``currency``
    price: Decimal | None = None  # last known market price (statement open positions)
    price_date: date | None = None
    next_date: date | None = None  # when the next lot passes the test
    next_quantity: Decimal = ZERO

    @property
    def value(self) -> Decimal | None:
        return None if self.price is None else self.quantity * self.price

    @property
    def gain(self) -> Decimal | None:
        """Gain that a sale at the last price would realise without tax."""
        return None if self.value is None else self.value - self.cost

    @property
    def partial(self) -> bool:
        return self.quantity < self.held


def tax_free_positions(
    calendar: Iterable[CalendarLot],
    prices: dict[str, tuple[date, Decimal]] | None = None,
    today: date | None = None,
) -> list[TaxFreePosition]:
    """One row per position with at least one exempt lot; largest tax-free gain first."""
    today = today or date.today()
    prices = prices or {}
    by_key: dict[str, list[CalendarLot]] = {}
    for item in calendar:
        by_key.setdefault(item.lot.key, []).append(item)

    out = []
    for key, items in by_key.items():
        exempt = [i for i in items if i.eligible and i.exempt_from <= today]
        if not exempt:
            continue
        waiting = sorted(
            (i for i in items if i.eligible and i.exempt_from > today), key=lambda i: i.exempt_from
        )
        first = items[0].lot
        price_date, price = prices.get(key, (None, None))
        next_date = waiting[0].exempt_from if waiting else None
        out.append(
            TaxFreePosition(
                key=key,
                symbol=first.symbol,
                description=items[0].description,
                currency=first.currency,
                quantity=sum((i.lot.quantity for i in exempt), ZERO),
                held=sum((i.lot.quantity for i in items), ZERO),
                exempt_since=max(i.exempt_from for i in exempt),
                cost=sum((i.lot.cost for i in exempt), ZERO),
                price=price,
                price_date=price_date,
                next_date=next_date,
                next_quantity=sum((i.lot.quantity for i in waiting if i.exempt_from == next_date), ZERO),
            )
        )
    return sorted(out, key=lambda p: (p.gain is None, -(p.gain or ZERO), p.symbol))


def _latest_rules(load, year: int):  # type: ignore[no-untyped-def]
    """Rules of ``year`` or of the latest earlier year that has them (time tests rarely change)."""
    for candidate in range(year, year - 5, -1):
        try:
            return load(candidate)
        except MissingRulesError:
            continue
    return load(year)


def cz_tax_free(
    engine: Engine, account_id: str | None = None, today: date | None = None
) -> list[TaxFreePosition]:
    """Positions with lots held longer than the Czech time test (3 years)."""
    from taxfolio.services.simulator import last_prices

    today = today or date.today()
    years = _latest_rules(load_cz, today.year).time_test_years
    fifo = realized.compute_fifo(engine, account_id)
    calendar = [
        CalendarLot(lot, fifo.descriptions.get(lot.key, ""), time_test_date(lot.open_datetime.date(), years))
        for lot in fifo.result.open_lots
    ]
    return tax_free_positions(calendar, last_prices(engine), today)


def sk_tax_free(
    engine: Engine, account_id: str | None = None, today: date | None = None
) -> list[TaxFreePosition]:
    """Positions with lots held longer than 1 year on a regulated market (Slovakia)."""
    from taxfolio.services.simulator import last_prices
    from taxfolio.services.tax_sk import listing_exchanges

    today = today or date.today()
    rules = _latest_rules(load_sk, today.year)
    exchanges = listing_exchanges(engine)
    fifo = realized.compute_fifo(engine, account_id)
    calendar = [
        CalendarLot(
            lot,
            fifo.descriptions.get(lot.key, ""),
            time_test_date(lot.open_datetime.date(), rules.time_test_years),
            (exchanges.get(lot.key) or "").upper() in rules.regulated_exchanges,
        )
        for lot in fifo.result.open_lots
    ]
    return tax_free_positions(calendar, last_prices(engine), today)
