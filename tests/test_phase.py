import pytest

from tradingbot import phase
from tradingbot.costs import CostModel
from tradingbot.demo import synthetic_candles
from tradingbot.models import Candle
from tradingbot.paper import PaperEngine
from tradingbot.risk import RiskManager
from tradingbot.storage import Store
from tradingbot.strategy.sma_cross import SmaCross

TF = 3600


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "phase.db") as s:
        yield s


def readiness(candles, warmup=31, first=None, last=None):
    return phase.TimeframeReadiness(
        tf=TF, label="1h", candles=candles, warmup=warmup,
        first_ts=first, last_ts=last,
    )


# --- readiness -------------------------------------------------------------

def test_missing_candles_are_counted():
    row = readiness(candles=2, warmup=31)
    assert not row.ready
    assert row.missing == 29


def test_ready_when_warmup_is_met():
    row = readiness(candles=31, warmup=31)
    assert row.ready
    assert row.missing == 0
    assert row.eta_seconds == 0


def test_rate_uses_observed_pace_not_nominal():
    """En un libro poco liquido no hay una vela por intervalo: solo hay vela
    donde hubo trades. Estimar con el nominal daria una espera optimista."""
    # 3 velas repartidas en 6 horas: el ritmo real es de 3h por vela, no 1h.
    row = readiness(candles=3, warmup=5, first=0, last=6 * TF)
    assert row.seconds_per_candle == 3 * TF
    assert row.eta_seconds == 2 * 3 * TF


def test_no_estimate_without_enough_history():
    assert readiness(candles=1, first=0, last=0).eta_seconds is None
    assert readiness(candles=0).seconds_per_candle is None


def test_humanize_eta():
    assert phase.humanize_eta(None) == "sin estimacion"
    assert phase.humanize_eta(0) == "listo"
    assert phase.humanize_eta(30) == "<1 min"
    assert "h" in phase.humanize_eta(2 * 3600)
    assert "d" in phase.humanize_eta(3 * 86400)


# --- gate ------------------------------------------------------------------

def test_verdict_without_any_trades(store):
    result = phase.evaluate(store, "usd_ars", SmaCross(3, 8), run_id="nada")
    assert result.verdict == "sin_datos"
    assert not result.passed
    assert result.round_trips == 0


def test_verdict_is_insufficient_below_threshold(store):
    candles = synthetic_candles(n=200, tf=TF, seed=7, volatility=0.02)
    store.upsert_candles("usd_ars", TF, candles)
    engine = PaperEngine(
        store, "usd_ars", TF, SmaCross(3, 8), 100.0, CostModel(),
        RiskManager(max_daily_loss_pct=10.0, min_order_notional=1.0),
    )
    engine.step(now=candles[-1].ts + TF)

    result = phase.evaluate(store, "usd_ars", SmaCross(3, 8), run_id=engine.run_id)
    assert 0 < result.round_trips < phase.REQUIRED_ROUND_TRIPS
    assert result.verdict == "insuficiente"
    assert not result.passed


def test_positive_expectancy_alone_does_not_pass(store):
    """El umbral de muestra no es negociable: con pocas operaciones, una
    expectancy positiva es tan probablemente suerte como habilidad."""
    result = phase.evaluate(
        store, "usd_ars", SmaCross(3, 8), run_id="x", required=100
    )
    assert not result.passed


def test_gate_passes_with_enough_winning_trades(store, monkeypatch):
    run_id = "sintetico"
    price = 100.0
    for i in range(10):
        store.log(run_id, i * 2, "fill", book="usd_ars", side="buy",
                  amount=1.0, price=price, fee=0.0, detail="c")
        store.log(run_id, i * 2 + 1, "fill", book="usd_ars", side="sell",
                  amount=1.0, price=price * 1.10, fee=0.0, detail="c")

    result = phase.evaluate(
        store, "usd_ars", SmaCross(3, 8), run_id=run_id, required=10
    )
    assert result.round_trips == 10
    assert result.expectancy > 0
    assert result.verdict == "aprobado"
    assert result.passed


def test_gate_rejects_negative_expectancy(store):
    run_id = "perdedor"
    for i in range(10):
        store.log(run_id, i * 2, "fill", book="usd_ars", side="buy",
                  amount=1.0, price=100.0, fee=0.5, detail="c")
        store.log(run_id, i * 2 + 1, "fill", book="usd_ars", side="sell",
                  amount=1.0, price=99.0, fee=0.5, detail="c")

    result = phase.evaluate(
        store, "usd_ars", SmaCross(3, 8), run_id=run_id, required=10
    )
    assert result.expectancy < 0
    assert result.verdict == "rechazado"
    assert not result.passed


def test_progress_is_capped_at_one(store):
    run_id = "muchos"
    for i in range(6):
        store.log(run_id, i * 2, "fill", book="usd_ars", side="buy",
                  amount=1.0, price=100.0, fee=0.0, detail="c")
        store.log(run_id, i * 2 + 1, "fill", book="usd_ars", side="sell",
                  amount=1.0, price=101.0, fee=0.0, detail="c")
    result = phase.evaluate(store, "usd_ars", SmaCross(3, 8), run_id=run_id, required=3)
    assert result.progress == 1.0
