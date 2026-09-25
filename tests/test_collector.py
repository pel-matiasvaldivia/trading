from tradingbot.collector import aggregate_candles
from tradingbot.models import Trade


def trade(tid, ts, price, amount=1.0):
    return Trade(tid, ts, price, amount, "buy")


def test_groups_trades_into_intervals():
    trades = [trade(1, 0, 100), trade(2, 30, 110), trade(3, 60, 105)]
    candles = aggregate_candles(trades, 60)
    assert len(candles) == 2
    assert (candles[0].open, candles[0].high, candles[0].close) == (100, 110, 110)


def test_ohlc_is_consistent():
    trades = [trade(i, i * 10, 100 + (i % 5)) for i in range(20)]
    for candle in aggregate_candles(trades, 60):
        assert candle.low <= candle.open <= candle.high
        assert candle.low <= candle.close <= candle.high


def test_open_and_close_follow_trade_order_not_arrival():
    """El orden lo da el tid, no el orden en que llegaron los trades."""
    trades = [trade(3, 50, 130), trade(1, 10, 110), trade(2, 30, 120)]
    candle = aggregate_candles(trades, 60)[0]
    assert candle.open == 110
    assert candle.close == 130


def test_volume_is_summed():
    trades = [trade(1, 0, 100, 1.5), trade(2, 10, 100, 2.5)]
    assert aggregate_candles(trades, 60)[0].volume == 4.0


def test_empty_input_gives_no_candles():
    assert aggregate_candles([], 60) == []
