from tradingbot.broker.paper import PaperBroker
from tradingbot.costs import CostModel
from tradingbot.models import Order, Side


def order(side, amount, price, ts=0):
    return Order(ts, "usd_ars", side, amount, f"t-{ts}", price)


def test_buy_deducts_cash_and_fee():
    broker = PaperBroker(100.0, CostModel(taker_fee_bps=100, half_spread_bps=0, slippage_bps=0))
    fill = broker.execute(order(Side.BUY, 1.0, 50.0))
    assert fill.price == 50.0
    assert fill.fee == 0.5
    assert broker.cash == 49.5
    assert broker.position == 1.0


def test_insufficient_cash_is_rejected():
    broker = PaperBroker(10.0)
    assert broker.execute(order(Side.BUY, 1.0, 50.0)) is None
    assert broker.cash == 10.0


def test_cannot_sell_more_than_held():
    broker = PaperBroker(100.0)
    assert broker.execute(order(Side.SELL, 1.0, 50.0)) is None


def test_flat_market_round_trip_loses_exactly_the_costs():
    """Comprar y vender al mismo precio debe perder el costo ida y vuelta."""
    costs = CostModel(taker_fee_bps=65, maker_fee_bps=50, half_spread_bps=10, slippage_bps=5)
    broker = PaperBroker(1000.0, costs)
    broker.execute(order(Side.BUY, 1.0, 100.0))
    broker.execute(order(Side.SELL, broker.position, 100.0, ts=1))

    loss_pct = (broker.cash - 1000.0) / 100.0 * 100.0  # sobre el nocional
    assert loss_pct < 0
    assert abs(loss_pct) == __import__("pytest").approx(
        costs.round_trip_bps() / 100.0, rel=0.02
    )


def test_realized_pnl_tracks_profitable_trade():
    broker = PaperBroker(1000.0, CostModel(taker_fee_bps=0, half_spread_bps=0, slippage_bps=0))
    broker.execute(order(Side.BUY, 1.0, 100.0))
    broker.execute(order(Side.SELL, 1.0, 120.0, ts=1))
    assert broker.realized_pnl == 20.0
    assert broker.position == 0.0
