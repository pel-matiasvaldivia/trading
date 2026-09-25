import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi.testclient import TestClient  # noqa: E402

from tradingbot import backtest  # noqa: E402
from tradingbot.demo import sine_candles  # noqa: E402
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
