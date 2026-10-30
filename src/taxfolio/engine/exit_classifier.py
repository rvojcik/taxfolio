"""Classify why a trade happened: entry, stop-loss, take-profit, manual exit, ...

Priority (ZADANI.md §3.2): user annotation > orderReference keyword > IBKR codes > order type.
A closing limit order that rested in the book for a while and closed in profit is treated as a
take-profit target; one filled right after it was sent (or closed at a loss) is a manual exit.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from taxfolio.i18n import N_


class TradeReason(StrEnum):
    ENTRY = "ENTRY"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    MANUAL_EXIT = "MANUAL_EXIT"
    LIQUIDATION = "LIQUIDATION"
    AUTO_FX = "AUTO_FX"
    UNKNOWN = "UNKNOWN"


# Czech source texts; translate with _() when displayed
REASON_LABELS = {
    TradeReason.ENTRY: N_("Vstup"),
    TradeReason.STOP_LOSS: N_("Stop-loss"),
    TradeReason.TAKE_PROFIT: N_("Take-profit"),
    TradeReason.MANUAL_EXIT: N_("Ruční výstup"),
    TradeReason.LIQUIDATION: N_("Likvidace IB"),
    TradeReason.AUTO_FX: N_("Automatická konverze"),
    TradeReason.UNKNOWN: "",
}

STOP_ORDER_TYPES = frozenset({"STP", "STP LMT", "STPLMT", "TRAIL", "TRAIL LIMIT", "TRAILLMT", "TRAIL LMT"})
LIMIT_ORDER_TYPES = frozenset({"LMT", "MIT", "LIT"})
# A limit order waiting at least this long before the fill was a pre-set target, not a click-to-exit.
RESTING_THRESHOLD = timedelta(minutes=5)

_REF_STOP = re.compile(r"\b(sl|stop|stoploss|stop-loss)\b", re.IGNORECASE)
_REF_TARGET = re.compile(r"\b(tp|target|takeprofit|take-profit|profit)\b", re.IGNORECASE)


def classify(
    *,
    codes: str,
    order_type: str | None,
    order_time: datetime | None,
    trade_datetime: datetime,
    order_reference: str | None = None,
    override: TradeReason | None = None,
    realized_pnl: Decimal | None = None,
) -> TradeReason:
    if override is not None:
        return override
    flags = set(codes.split(";")) if codes else set()
    is_close = "C" in flags

    if order_reference:
        if _REF_STOP.search(order_reference):
            return TradeReason.STOP_LOSS
        if _REF_TARGET.search(order_reference):
            return TradeReason.TAKE_PROFIT
    if flags & {"L", "LF"}:
        return TradeReason.LIQUIDATION
    if "AFx" in flags:
        return TradeReason.AUTO_FX
    if not is_close:
        return TradeReason.ENTRY if "O" in flags else TradeReason.UNKNOWN
    if not order_type:
        return TradeReason.UNKNOWN  # Activity Statement rows carry no order type
    kind = order_type.upper()
    if kind in STOP_ORDER_TYPES:
        return TradeReason.STOP_LOSS
    resting = order_time is not None and trade_datetime - order_time >= RESTING_THRESHOLD
    in_profit = realized_pnl is not None and realized_pnl > 0
    if kind in LIMIT_ORDER_TYPES and resting and in_profit:
        return TradeReason.TAKE_PROFIT
    return TradeReason.MANUAL_EXIT
