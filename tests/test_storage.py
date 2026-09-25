from tradingbot.models import Candle, Trade
from tradingbot.storage import Store


def test_trades_are_deduplicated(tmp_path):
    store = Store(tmp_path / "t.db")
    trades = [Trade(1, 10, 100.0, 1.0, "buy")]
    assert store.upsert_trades("usd_ars", trades) == 1
    store.upsert_trades("usd_ars", trades)
    assert len(store.load_trades("usd_ars")) == 1


def test_candles_round_trip(tmp_path):
    store = Store(tmp_path / "t.db")
    candles = [Candle(0, 1, 2, 0.5, 1.5, 10), Candle(60, 1.5, 2, 1, 1.8, 5)]
    store.upsert_candles("usd_ars", 60, candles)
    assert store.load_candles("usd_ars", 60) == candles


def test_candles_are_isolated_by_timeframe(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert_candles("usd_ars", 60, [Candle(0, 1, 1, 1, 1, 1)])
    assert store.load_candles("usd_ars", 3600) == []


def test_journal_records_and_filters_by_kind(tmp_path):
    store = Store(tmp_path / "t.db")
    store.log("run1", 0, "signal", detail="buy")
    store.log("run1", 1, "reject", detail="sin efectivo")
    store.log("run2", 2, "signal", detail="sell")
    assert len(store.run_entries("run1")) == 2
    assert len(store.run_entries("run1", kind="reject")) == 1
