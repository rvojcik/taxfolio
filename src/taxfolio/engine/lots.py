"""FIFO lot matching with stock splits.

Pure computation: no database, no currency conversion. Amounts stay in the trade currency.
Instruments are keyed by ISIN (stable across symbol changes; a reverse split that issues a new
ISIN is followed through the corporate action). Buy commissions are part of the lot cost, sell
commissions reduce the proceeds – the same convention IBKR uses for ``fifoPnlRealized``.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal

from taxfolio.i18n import _


@dataclass(frozen=True)
class TradeInput:
    ref: int  # database id of the execution
    key: str  # instrument key (ISIN, or symbol when unknown)
    symbol: str
    currency: str
    trade_datetime: datetime
    quantity: Decimal  # + buy, - sell
    proceeds: Decimal  # - paid, + received (trade currency)
    commission: Decimal  # negative = paid
    commission_currency: str


@dataclass(frozen=True)
class SplitInput:
    action_datetime: datetime
    old_key: str
    new_key: str
    ratio: Decimal  # new shares per old share (10 for "10 for 1", 0.1 for "1 for 10")
    description: str = ""


@dataclass(frozen=True)
class Lot:
    key: str
    symbol: str
    currency: str
    open_ref: int
    open_datetime: datetime
    quantity: Decimal
    cost: Decimal  # total cost of the remaining quantity incl. buy commission

    @property
    def unit_cost(self) -> Decimal:
        return self.cost / self.quantity


@dataclass(frozen=True)
class LotMatch:
    key: str
    symbol: str
    currency: str
    open_ref: int
    close_ref: int
    open_datetime: datetime
    close_datetime: datetime
    quantity: Decimal
    cost: Decimal
    proceeds: Decimal  # net of the proportional sell commission
    sell_commission: Decimal = Decimal(0)  # proportional share, negative = paid

    @property
    def gross_proceeds(self) -> Decimal:
        """Sale price before the sell commission (tax 'příjem')."""
        return self.proceeds - self.sell_commission

    @property
    def pnl(self) -> Decimal:
        return self.proceeds - self.cost

    @property
    def holding_days(self) -> int:
        return (self.close_datetime.date() - self.open_datetime.date()).days


@dataclass
class FifoResult:
    matches: list[LotMatch] = field(default_factory=list)
    open_lots: list[Lot] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


_SPLIT_RE = re.compile(r"SPLIT\s+(\d+(?:\.\d+)?)\s+FOR\s+(\d+(?:\.\d+)?)", re.IGNORECASE)


def split_ratio(description: str) -> Decimal | None:
    m = _SPLIT_RE.search(description)
    return Decimal(m.group(1)) / Decimal(m.group(2)) if m else None


def match_fifo(trades: Iterable[TradeInput], splits: Sequence[SplitInput] = ()) -> FifoResult:
    result = FifoResult()
    lots: dict[str, deque[Lot]] = defaultdict(deque)

    # Splits are effective after the close of their day, trades of the same timestamp go first.
    events: list[tuple[datetime, int, TradeInput | SplitInput]] = [
        (t.trade_datetime, 0, t) for t in trades
    ] + [(s.action_datetime, 1, s) for s in splits]
    events.sort(key=lambda e: (e[0], e[1]))  # stable: equal timestamps keep the input order

    for _when, _order, ev in events:
        if isinstance(ev, SplitInput):
            _apply_split(lots, ev, result)
            continue
        if ev.commission and ev.commission_currency != ev.currency:
            result.warnings.append(
                _("{symbol} {day}: poplatek v {fee_currency} (obchod v {currency}) není započten").format(
                    symbol=ev.symbol,
                    day=f"{ev.trade_datetime:%Y-%m-%d}",
                    fee_currency=ev.commission_currency,
                    currency=ev.currency,
                )
            )
        commission = ev.commission if ev.commission_currency == ev.currency else Decimal(0)
        if ev.quantity > 0:
            lots[ev.key].append(
                Lot(
                    key=ev.key,
                    symbol=ev.symbol,
                    currency=ev.currency,
                    open_ref=ev.ref,
                    open_datetime=ev.trade_datetime,
                    quantity=ev.quantity,
                    cost=-(ev.proceeds + commission),
                )
            )
        elif ev.quantity < 0:
            _close(lots[ev.key], ev, ev.proceeds, commission, result)

    result.open_lots = [lot for queue in lots.values() for lot in queue]
    return result


def _close(
    queue: deque[Lot], ev: TradeInput, gross: Decimal, commission: Decimal, result: FifoResult
) -> None:
    to_sell = -ev.quantity
    sold_total = to_sell
    while to_sell > 0 and queue:
        lot = queue[0]
        qty = min(lot.quantity, to_sell)
        cost = lot.cost if qty == lot.quantity else lot.unit_cost * qty
        result.matches.append(
            LotMatch(
                key=ev.key,
                symbol=ev.symbol,
                currency=ev.currency,
                open_ref=lot.open_ref,
                close_ref=ev.ref,
                open_datetime=lot.open_datetime,
                close_datetime=ev.trade_datetime,
                quantity=qty,
                cost=cost,
                proceeds=(gross + commission) * qty / sold_total,
                sell_commission=commission * qty / sold_total,
            )
        )
        if qty == lot.quantity:
            queue.popleft()
        else:
            queue[0] = replace(lot, quantity=lot.quantity - qty, cost=lot.cost - cost)
        to_sell -= qty
    if to_sell > 0:
        result.warnings.append(
            _(
                "{symbol} {day}: prodej {quantity} ks bez nákupu v datech (chybí historie nebo jde o short)"
            ).format(symbol=ev.symbol, day=f"{ev.trade_datetime:%Y-%m-%d}", quantity=to_sell)
        )


def _apply_split(lots: dict[str, deque[Lot]], s: SplitInput, result: FifoResult) -> None:
    old = lots.pop(s.old_key, deque())
    if not old:
        result.warnings.append(
            _("Split {split}: žádné otevřené loty").format(split=s.description or s.old_key)
        )
        return
    # Cost and holding period carry over; only the share count changes.
    converted = [replace(lot, key=s.new_key, quantity=lot.quantity * s.ratio) for lot in old]
    merged = sorted([*lots[s.new_key], *converted], key=lambda lot: lot.open_datetime)
    lots[s.new_key] = deque(merged)
