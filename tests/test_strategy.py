import pytest

from tradingbot.models import Candle, Signal
from tradingbot.strategy.sma_cross import BuyAndHold, SmaCross


def candles(prices):
    return [Candle(i * 3600, p, p, p, p, 1.0) for i, p in enumerate(prices)]


def test_holds_during_warmup():
    strategy = SmaCross(2, 4)
    assert strategy.signal(candles([10, 11, 12])) is Signal.HOLD


def test_detects_upward_cross_once():
    strategy = SmaCross(2, 4)
    signals = [
        strategy.signal(candles([10, 10, 10, 10, 20, 20])[: i + 1])
        for i in range(6)
    ]
    assert signals.count(Signal.BUY) == 1


def test_detects_downward_cross():
    strategy = SmaCross(2, 4)
    prices = [20, 20, 20, 20, 20, 5, 5]
    signals = [strategy.signal(candles(prices)[: i + 1]) for i in range(len(prices))]
    assert Signal.SELL in signals


def test_no_signal_on_flat_market():
    strategy = SmaCross(2, 4)
    flat = candles([10] * 20)
    assert all(
        strategy.signal(flat[: i + 1]) is Signal.HOLD for i in range(len(flat))
    )


def test_fast_must_be_shorter_than_slow():
    with pytest.raises(ValueError):
        SmaCross(30, 10)


def test_buy_and_hold_buys_only_once():
    strategy = BuyAndHold()
    prices = candles([10, 11, 12, 13])
    signals = [strategy.signal(prices[: i + 1]) for i in range(4)]
    assert signals == [Signal.BUY, Signal.HOLD, Signal.HOLD, Signal.HOLD]
