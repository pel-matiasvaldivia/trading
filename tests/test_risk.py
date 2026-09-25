from tradingbot.models import Order, PortfolioState, Side
from tradingbot.risk import RiskManager


def state(ts=0, cash=100.0, position=0.0, price=10.0, equity_hint=None):
    return PortfolioState(ts, cash, position, price, 0.0, 0.0)


def order(side, amount, price=10.0, ts=0):
    return Order(ts, "usd_ars", side, amount, "c1", price)


def test_caps_order_to_available_cash():
    risk = RiskManager(min_order_notional=1.0)
    decision = risk.approve(order(Side.BUY, 100.0), state(cash=50.0))
    assert decision.approved
    assert decision.adjusted_amount * 10.0 <= 50.0


def test_rejects_below_exchange_minimum():
    risk = RiskManager(min_order_notional=5.0)
    decision = risk.approve(order(Side.BUY, 0.1), state())
    assert not decision.approved
    assert "minimo" in decision.reason


def test_sell_is_capped_to_held_position():
    risk = RiskManager(min_order_notional=1.0)
    decision = risk.approve(order(Side.SELL, 10.0), state(position=2.0))
    assert decision.approved
    assert decision.adjusted_amount == 2.0


def test_rejects_sell_without_position():
    risk = RiskManager()
    assert not risk.approve(order(Side.SELL, 1.0), state(position=0.0)).approved


def test_kill_switch_trips_on_daily_loss():
    risk = RiskManager(max_daily_loss_pct=0.05, min_order_notional=1.0)
    risk.approve(order(Side.BUY, 1.0), state(ts=0, cash=100.0))
    decision = risk.approve(order(Side.BUY, 1.0), state(ts=3600, cash=90.0))
    assert not decision.approved
    assert risk.halted


def test_kill_switch_requires_manual_reset():
    """Un bot que se rearma solo despues de perder insiste en perder."""
    risk = RiskManager(max_daily_loss_pct=0.05, min_order_notional=1.0)
    risk.approve(order(Side.BUY, 1.0), state(ts=0, cash=100.0))
    risk.approve(order(Side.BUY, 1.0), state(ts=3600, cash=90.0))
    assert risk.halted
    # Recuperar el equity no lo reactiva.
    assert not risk.approve(order(Side.BUY, 1.0), state(ts=7200, cash=110.0)).approved
    risk.reset()
    assert not risk.halted
