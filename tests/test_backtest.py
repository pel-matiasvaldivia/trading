import math

import pytest

from tradingbot import backtest
from tradingbot.costs import CostModel
from tradingbot.models import Candle
from tradingbot.strategy.base import Strategy
from tradingbot.strategy.sma_cross import BuyAndHold, SmaCross
from tradingbot.models import Signal

FREE = CostModel(taker_fee_bps=0, maker_fee_bps=0, half_spread_bps=0, slippage_bps=0)


def candles(prices):
    return [Candle(i * 3600, p, p, p, p, 1.0) for i, p in enumerate(prices)]


def oscillating(n=120, amplitude=0.02, period=10):
    """Mercado sin tendencia: vuelve siempre al mismo nivel."""
    return [100.0 * (1 + amplitude * math.sin(2 * math.pi * i / period)) for i in range(n)]


def test_buy_and_hold_tracks_the_market_without_costs():
    result = backtest.run(candles([100.0] * 2 + [200.0]), BuyAndHold(), 1000.0, costs=FREE)
    assert result.metrics.total_return_pct == pytest.approx(100.0, rel=1e-6)


def no_kill_switch():
    """Riesgo sin corte diario, para aislar el efecto de los costos."""
    from tradingbot.risk import RiskManager

    return RiskManager(max_daily_loss_pct=10.0, min_order_notional=1.0)


def test_costs_strictly_reduce_returns():
    """El mismo mercado y la misma estrategia, solo cambian los costos."""
    prices = oscillating()
    free = backtest.run(
        candles(prices), SmaCross(3, 8), 1000.0, costs=FREE, risk=no_kill_switch()
    )
    real = backtest.run(
        candles(prices), SmaCross(3, 8), 1000.0, costs=CostModel(), risk=no_kill_switch()
    )
    assert real.metrics.n_trades == free.metrics.n_trades
    assert real.metrics.total_return_pct < free.metrics.total_return_pct
    assert real.metrics.fees_paid > 0


def test_choppy_market_bleeds_capital_through_fees():
    """La tesis central del proyecto, como test.

    En un mercado que oscila sin ir a ningun lado, un cruce de medias opera
    seguido y pierde plata aunque el precio termine donde empezo.
    """
    prices = oscillating(n=200, amplitude=0.01, period=8)
    result = backtest.run(candles(prices), SmaCross(3, 8), 33.27, costs=CostModel())
    assert result.metrics.n_trades > 0
    assert result.metrics.total_return_pct < 0
    assert result.metrics.fees_pct_of_start > 0


def test_no_lookahead_bias():
    """Extender el futuro no puede cambiar las senales ya emitidas."""
    prices = oscillating(n=60)
    short = backtest.run(candles(prices[:40]), SmaCross(3, 8), 1000.0, costs=FREE)
    long = backtest.run(candles(prices), SmaCross(3, 8), 1000.0, costs=FREE)
    assert long.equity[:40] == pytest.approx(short.equity)


def test_rejects_insufficient_history():
    with pytest.raises(ValueError):
        backtest.run(candles([1.0, 2.0]), SmaCross(10, 30), 1000.0)


def test_equity_has_one_point_per_candle():
    prices = oscillating(n=50)
    result = backtest.run(candles(prices), SmaCross(3, 8), 1000.0)
    assert len(result.equity) == 50


def test_never_goes_negative():
    """Ningun camino de precios debe poder dejar el equity bajo cero."""
    prices = [100.0 * (0.9**i) for i in range(40)]  # caida sostenida
    result = backtest.run(candles(prices), SmaCross(3, 8), 33.27, costs=CostModel())
    assert all(e >= 0 for e in result.equity)


class AlwaysBuy(Strategy):
    name = "always_buy"

    @property
    def warmup(self):
        return 1

    def signal(self, history):
        return Signal.BUY


def test_risk_layer_caps_exposure():
    """Con el tope al 50%, nunca puede haber mas de la mitad en posicion."""
    from tradingbot.risk import RiskManager

    result = backtest.run(
        candles([100.0] * 30),
        AlwaysBuy(),
        1000.0,
        costs=FREE,
        risk=RiskManager(max_position_pct=0.5, min_order_notional=1.0),
    )
    assert len(result.fills) == 1
    assert result.fills[0].notional <= 1000.0 * 0.5 + 1e-6
    # Las compras posteriores chocan contra el tope y quedan registradas.
    assert result.rejections


def test_order_sizing_leaves_room_for_costs():
    """Comprar con todo el efectivo no debe rebotar contra las comisiones."""
    result = backtest.run(candles([100.0] * 5), BuyAndHold(), 33.27, costs=CostModel())
    assert result.metrics.n_trades == 1
    assert not result.rejections
