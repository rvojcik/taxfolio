from datetime import datetime
from decimal import Decimal

from taxfolio.engine.lots import SplitInput, TradeInput, match_fifo, split_ratio

D = Decimal


def trade(ref: int, when: str, qty: str, proceeds: str, comm: str = "0", key: str = "US1", ccy: str = "USD"):
    return TradeInput(
        ref=ref,
        key=key,
        symbol="X",
        currency=ccy,
        trade_datetime=datetime.fromisoformat(when),
        quantity=D(qty),
        proceeds=D(proceeds),
        commission=D(comm),
        commission_currency=ccy,
    )


def test_fifo_consumes_oldest_lots_and_splits_partially() -> None:
    res = match_fifo(
        [
            trade(1, "2024-01-02T10:00", "10", "-100", "-1"),  # cost 101 → 10.1/sh
            trade(2, "2024-02-02T10:00", "10", "-200", "-1"),  # cost 201 → 20.1/sh
            trade(3, "2025-03-01T10:00", "-15", "450", "-3"),  # net 447 → 29.8/sh
        ]
    )
    assert [(m.open_ref, m.quantity) for m in res.matches] == [(1, D(10)), (2, D(5))]
    first, second = res.matches
    assert first.cost == D(101) and first.proceeds == D(298)
    assert second.cost == D("100.5") and second.proceeds == D(149)
    assert sum(m.pnl for m in res.matches) == D(447) - D("201.5")
    assert first.holding_days == 424
    (lot,) = res.open_lots
    assert lot.quantity == D(5) and lot.cost == D("100.5")


def test_forward_split_keeps_cost_and_open_date() -> None:
    res = match_fifo(
        [trade(1, "2024-01-03T11:00", "2", "-1000"), trade(2, "2024-10-11T11:00", "-20", "2400")],
        [SplitInput(datetime(2024, 6, 7, 20, 25), "US1", "US1", D(10))],
    )
    (m,) = res.matches
    assert m.quantity == D(20) and m.cost == D(1000) and m.open_datetime == datetime(2024, 1, 3, 11)
    assert res.warnings == []


def test_reverse_split_moves_lots_to_new_isin() -> None:
    res = match_fifo(
        [
            trade(1, "2024-01-03T09:00", "270", "-270", key="OLD"),
            trade(2, "2024-08-01T10:00", "-27", "540", key="NEW"),
        ],
        [SplitInput(datetime(2024, 7, 9, 20, 25), "OLD", "NEW", D("0.1"))],
    )
    (m,) = res.matches
    assert m.key == "NEW" and m.quantity == D(27) and m.cost == D(270)


def test_selling_more_than_held_warns() -> None:
    res = match_fifo([trade(1, "2024-01-02T10:00", "1", "-10"), trade(2, "2024-01-03T10:00", "-3", "30")])
    assert len(res.matches) == 1 and "2" in res.warnings[0]


def test_same_timestamp_keeps_input_order() -> None:
    res = match_fifo(
        [
            trade(1, "2024-02-28T10:39:56", "27", "-441.1", "-1"),
            trade(2, "2024-02-28T10:39:56", "13", "-211.9", "0"),
            trade(3, "2024-12-06T09:31:48", "-14", "294", "-1"),
        ]
    )
    assert [m.open_ref for m in res.matches] == [1]


def test_split_ratio_parsing() -> None:
    assert split_ratio("NVDA(US67066G1040) SPLIT 10 FOR 1 (NVDA, NVIDIA CORP, US67066G1040)") == D(10)
    assert split_ratio("HOOK(US43906K1007) Split 1 for 10 (HOOK, HOOKIPA PHARMA INC, US43906K2096)") == D(
        "0.1"
    )
    assert split_ratio("Cash dividend") is None
