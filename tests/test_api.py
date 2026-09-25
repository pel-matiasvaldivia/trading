import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi.testclient import TestClient  # noqa: E402

from tradingbot import backtest  # noqa: E402
from tradingbot.costs import CostModel  # noqa: E402
from tradingbot.demo import sine_candles, synthetic_candles  # noqa: E402
from tradingbot.paper import PaperEngine  # noqa: E402
from tradingbot.risk import RiskManager  # noqa: E402
from tradingbot.storage import Store  # noqa: E402
from tradingbot.strategy.sma_cross import SmaCross  # noqa: E402

TOKEN = "test-token"


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "trading.db"
    with Store(db) as store:
        backtest.run(
            sine_candles(n=120), SmaCross(3, 8), 1000.0, store=store, book="DEMO"
        )
        store.upsert_candles("DEMO", 3600, sine_candles(n=50))

    monkeypatch.setenv("TRADING_DB_PATH", str(db))
    monkeypatch.setenv("DASHBOARD_TOKEN", TOKEN)
    monkeypatch.setenv("TRADING_BOOK", "DEMO")
    monkeypatch.setenv("PAPER_FAST", "3")
    monkeypatch.setenv("PAPER_SLOW", "8")
    for module in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[module]

    from app.main import app  # noqa: PLC0415

    return TestClient(app)


def auth():
    return {"X-API-Token": TOKEN}


def test_health_needs_no_token(client):
    assert client.get("/api/health").status_code == 200


def test_protected_endpoints_reject_missing_token(client):
    for path in ("/api/status", "/api/coverage", "/api/runs", "/api/fills"):
        assert client.get(path).status_code == 401, path


def test_protected_endpoints_reject_wrong_token(client):
    response = client.get("/api/status", headers={"X-API-Token": "nope"})
    assert response.status_code == 401


def test_status_reports_cost_model(client):
    data = client.get("/api/status", headers=auth()).json()
    assert data["costs"]["round_trip_bps"] == pytest.approx(160.0)
    assert data["live_trading"] is False


def test_runs_and_equity_curve(client):
    runs = client.get("/api/runs", headers=auth()).json()
    assert runs
    run_id = runs[0]["run_id"]
    curve = client.get(f"/api/runs/{run_id}/equity", headers=auth()).json()
    assert len(curve) > 10
    assert all("ts" in point and "equity" in point for point in curve)


def test_unknown_run_is_404(client):
    assert client.get("/api/runs/nope/equity", headers=auth()).status_code == 404


def test_coverage_labels_timeframes(client):
    data = client.get("/api/coverage", headers=auth()).json()
    assert any(row["tf_label"] == "1h" for row in data["candles"])


def test_fills_are_returned(client):
    fills = client.get("/api/fills", headers=auth()).json()
    assert fills
    assert {"side", "price", "fee"} <= set(fills[0])


def test_database_is_opened_read_only(client, tmp_path):
    """El panel observa; no debe poder escribir en la base del bot."""
    import sqlite3

    from app import queries
    from app.settings import settings

    conn = queries.connect(settings.db_path)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO journal (run_id, ts, kind) VALUES ('x', 0, 'y')")


# --- calibracion y fase ----------------------------------------------------


@pytest.fixture
def calibrated_client(tmp_path, monkeypatch):
    """Cliente sobre una base con calibracion y una corrida de papel real."""
    db = tmp_path / "cal.db"
    candles = synthetic_candles(n=200, tf=3600, seed=7, volatility=0.02)
    with Store(db) as store:
        store.upsert_candles("DEMO", 3600, candles)
        store.save_calibration("DEMO", 100, half_spread_bps=40.0, taker_fee_bps=70.0)
        engine = PaperEngine(
            store, "DEMO", 3600, SmaCross(3, 8), 100.0, CostModel(),
            RiskManager(max_daily_loss_pct=10.0, min_order_notional=1.0),
        )
        engine.step(now=candles[-1].ts + 3600)

    monkeypatch.setenv("TRADING_DB_PATH", str(db))
    monkeypatch.setenv("DASHBOARD_TOKEN", TOKEN)
    monkeypatch.setenv("TRADING_BOOK", "DEMO")
    monkeypatch.setenv("PAPER_FAST", "3")
    monkeypatch.setenv("PAPER_SLOW", "8")
    for module in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[module]

    from app.main import app  # noqa: PLC0415

    return TestClient(app)


def test_status_flags_uncalibrated_costs(client):
    """Sin mediciones, el panel tiene que decir que los costos son supuestos."""
    data = client.get("/api/status", headers=auth()).json()
    assert data["costs"]["calibrated"] is False


def test_status_uses_measured_costs_when_available(calibrated_client):
    data = calibrated_client.get("/api/status", headers=auth()).json()
    assert data["costs"]["calibrated"] is True
    assert data["costs"]["half_spread_bps"] == 40.0
    assert data["costs"]["taker_fee_bps"] == 70.0
    # Un spread mas ancho tiene que mover el umbral de rentabilidad.
    assert data["costs"]["breakeven_move_pct"] > 1.6


def test_phase_endpoint_requires_token(calibrated_client):
    assert calibrated_client.get("/api/phase").status_code == 401


def test_phase_reports_progress_and_verdict(calibrated_client):
    data = calibrated_client.get("/api/phase", headers=auth()).json()
    assert data["required"] == 100
    assert data["round_trips"] > 0
    assert data["verdict"] == "insuficiente"
    assert data["passed"] is False
    assert 0 < data["progress"] < 1


def test_phase_reports_readiness_per_timeframe(calibrated_client):
    data = calibrated_client.get("/api/phase", headers=auth()).json()
    labels = {r["label"]: r for r in data["readiness"]}
    assert labels["1h"]["ready"] is True
    assert labels["1d"]["ready"] is False
    assert labels["1d"]["eta_human"]
    assert data["strategy"]["warmup"] == 9


def test_paper_endpoint_exposes_persisted_state(calibrated_client):
    runs = calibrated_client.get("/api/paper", headers=auth()).json()
    assert runs
    assert runs[0]["book"] == "DEMO"
    assert runs[0]["last_candle_ts"] is not None


def test_phase_is_read_only(calibrated_client):
    """Evaluar la fase no debe poder escribir en la base del bot."""
    import sqlite3

    from app import queries
    from app.settings import settings

    conn = queries.connect(settings.db_path)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO calibration (book, ts, half_spread_bps)"
                     " VALUES ('x', 1, 1.0)")
