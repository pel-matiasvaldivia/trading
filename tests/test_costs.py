import pytest

from tradingbot.costs import CostModel
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
