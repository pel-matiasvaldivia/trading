import pytest

from tradingbot.costs import CostModel, from_samples
from tradingbot.models import Side


def test_execution_price_is_always_adverse():
    costs = CostModel(half_spread_bps=10, slippage_bps=5)
    assert costs.effective_price(Side.BUY, 100.0) > 100.0
    assert costs.effective_price(Side.SELL, 100.0) < 100.0


def test_round_trip_includes_both_sides():
    costs = CostModel(taker_fee_bps=65, half_spread_bps=10, slippage_bps=5)
    assert costs.round_trip_bps() == pytest.approx(160.0)
    assert costs.breakeven_move_pct() == pytest.approx(1.60)


def test_maker_is_cheaper_than_taker():
    costs = CostModel()
    assert costs.round_trip_bps(maker=True) < costs.round_trip_bps(maker=False)


def test_rejects_invalid_price():
    with pytest.raises(ValueError):
        CostModel().effective_price(Side.BUY, 0.0)


# --- calibracion -----------------------------------------------------------

def test_without_samples_falls_back_and_says_so():
    """El panel necesita distinguir 'medido' de 'supuesto': tratar un default
    como si fuera dato es como se construye un backtest que miente."""
    model, calibrated = from_samples([], CostModel(taker_fee_bps=99))
    assert not calibrated
    assert model.taker_fee_bps == 99


def test_half_spread_uses_the_median_not_the_latest():
    """El spread se abre y se cierra durante el dia; una sola lectura puede
    caer en el mejor momento y subestimar el costo real."""
    samples = [{"half_spread_bps": v} for v in (100.0, 10.0, 20.0)]
    model, calibrated = from_samples(samples)
    assert calibrated
    assert model.half_spread_bps == 20.0


def test_fees_come_from_the_most_recent_sample_that_has_them():
    samples = [
        {"half_spread_bps": 10.0, "taker_fee_bps": None, "maker_fee_bps": None},
        {"half_spread_bps": 12.0, "taker_fee_bps": 40.0, "maker_fee_bps": 30.0},
    ]
    model, _ = from_samples(samples)
    assert model.taker_fee_bps == 40.0
    assert model.maker_fee_bps == 30.0


def test_measured_costs_change_the_breakeven():
    wide, _ = from_samples([{"half_spread_bps": 200.0}])
    tight, _ = from_samples([{"half_spread_bps": 1.0}])
    assert wide.breakeven_move_pct() > tight.breakeven_move_pct()


def test_affordable_amount_leaves_room_for_costs():
    costs = CostModel()
    amount = costs.affordable_amount(100.0, 10.0)
    price = costs.effective_price(Side.BUY, 10.0)
    total = amount * price + costs.fee(amount * price)
    assert total == pytest.approx(100.0)


def test_affordable_amount_is_zero_without_cash():
    assert CostModel().affordable_amount(0.0, 10.0) == 0.0
