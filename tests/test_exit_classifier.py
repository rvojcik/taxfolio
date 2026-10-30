from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from taxfolio.engine.exit_classifier import TradeReason, classify

T = datetime(2025, 9, 2, 9, 30)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"codes": "O", "order_type": "LMT"}, TradeReason.ENTRY),
        ({"codes": "C", "order_type": "STP"}, TradeReason.STOP_LOSS),
        ({"codes": "C;P", "order_type": "TRAIL"}, TradeReason.STOP_LOSS),
        # limit resting since the previous day, closed in profit → target
        (
            {
                "codes": "C",
                "order_type": "LMT",
                "order_time": T - timedelta(days=1),
                "realized_pnl": Decimal(5),
            },
            TradeReason.TAKE_PROFIT,
        ),
        # resting limit but closed at a loss → not a take-profit
        (
            {
                "codes": "C",
                "order_type": "LMT",
                "order_time": T - timedelta(hours=2),
                "realized_pnl": Decimal(-5),
            },
            TradeReason.MANUAL_EXIT,
        ),
        # limit filled seconds after sending → manual exit
        (
            {
                "codes": "C",
                "order_type": "LMT",
                "order_time": T - timedelta(seconds=8),
                "realized_pnl": Decimal(5),
            },
            TradeReason.MANUAL_EXIT,
        ),
        ({"codes": "C", "order_type": "MKT", "order_time": T}, TradeReason.MANUAL_EXIT),
        ({"codes": "C;L", "order_type": "MKT"}, TradeReason.LIQUIDATION),
        ({"codes": "AFx", "order_type": "MKT"}, TradeReason.AUTO_FX),
        ({"codes": "C", "order_type": None}, TradeReason.UNKNOWN),
        ({"codes": "C", "order_type": "LMT", "order_reference": "my SL"}, TradeReason.STOP_LOSS),
        ({"codes": "C", "order_type": "MKT", "order_reference": "TP1"}, TradeReason.MANUAL_EXIT),
        ({"codes": "C", "order_type": "MKT", "order_reference": "tp"}, TradeReason.TAKE_PROFIT),
        ({"codes": "C", "order_type": "STP", "override": TradeReason.MANUAL_EXIT}, TradeReason.MANUAL_EXIT),
    ],
)
def test_classify(kwargs: dict, expected: TradeReason) -> None:
    kwargs.setdefault("order_time", None)
    assert classify(trade_datetime=T, **kwargs) == expected
