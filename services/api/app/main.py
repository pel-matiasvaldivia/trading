"""API de lectura del laboratorio de trading.

Expone lo que el bot ya registro: cobertura de datos, corridas, curva de
equity, operaciones y rechazos. No coloca ordenes, no modifica la base y no
toca las credenciales de Bitso: es un observador.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from . import queries
from .settings import settings

# El core del bot es la fuente de verdad: la API no reimplementa el modelo de
# costos ni el criterio de fase, los importa. Duplicar esa logica seria
# garantizar que el panel y el bot terminen diciendo cosas distintas.
from tradingbot import costs as costs_mod
from tradingbot import phase as phase_mod
from tradingbot.costs import CostModel
from tradingbot.strategy.sma_cross import SmaCross

app = FastAPI(
    title="tradingbot API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.add_middleware(GZipMiddleware, minimum_size=500)
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

_costs = CostModel()


def require_token(x_api_token: Annotated[str | None, Header()] = None) -> None:
    """Token compartido. Si no hay token configurado, la API queda abierta."""
    if settings.token and x_api_token != settings.token:
        raise HTTPException(status_code=401, detail="token invalido o ausente")


def db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                f"No existe {settings.db_path}. El collector todavia no "
                "genero datos, o el volumen no esta montado."
            ),
        )
    conn = queries.connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(db)]
Auth = Annotated[None, Depends(require_token)]


@app.get("/api/health")
def health() -> dict:
    """Sin autenticacion: lo usa el healthcheck de Docker."""
    return {"status": "ok", "db_present": settings.db_path.exists()}


def _strategy() -> SmaCross:
    return SmaCross(settings.fast, settings.slow)


def _effective_costs(conn: sqlite3.Connection) -> tuple[CostModel, bool]:
    """Costos medidos si hay calibracion; si no, los estimados."""
    reader = queries.ReadOnlyStore(conn)
    return costs_mod.from_samples(reader.calibration_samples(settings.book), _costs)


@app.get("/api/status")
def status(conn: Conn, _: Auth) -> dict:
    """Estado del sistema y los numeros que enmarcan todo lo demas."""
    model, calibrated = _effective_costs(conn)
    return {
        "book": settings.book,
        "starting_cash": settings.starting_cash,
        # El panel es de solo lectura; que el bot opere en vivo es una
        # decision del proceso del bot, no de esta API.
        "live_trading": False,
        "phase": 1,
        "costs": {
            "taker_fee_bps": model.taker_fee_bps,
            "maker_fee_bps": model.maker_fee_bps,
            "half_spread_bps": model.half_spread_bps,
            "slippage_bps": model.slippage_bps,
            "round_trip_bps": model.round_trip_bps(),
            "breakeven_move_pct": model.breakeven_move_pct(),
            # Distinguir medido de supuesto no es un detalle: tratar un
            # default como si fuera dato es como se construye un backtest
            # que miente.
            "calibrated": calibrated,
        },
        "cost_per_round_trip": settings.starting_cash
        * model.round_trip_bps()
        / 10_000,
    }


@app.get("/api/phase")
def phase(conn: Conn, _: Auth) -> dict:
    """Criterio de salida de la fase: cuanto falta y cual es el veredicto."""
    reader = queries.ReadOnlyStore(conn)
    strategy = _strategy()
    run_id = phase_mod.run_id_for_paper(settings.book, settings.tf, strategy)
    result = phase_mod.evaluate(reader, settings.book, strategy, run_id=run_id)

    return {
        "run_id": result.run_id,
        "verdict": result.verdict,
        "reason": result.reason,
        "passed": result.passed,
        "round_trips": result.round_trips,
        "required": result.required,
        "progress": result.progress,
        "expectancy": result.expectancy,
        "net_pnl": result.net_pnl,
        "fees_paid": result.fees_paid,
        "win_rate": result.win_rate,
        "strategy": {
            "name": strategy.name,
            "fast": settings.fast,
            "slow": settings.slow,
            "warmup": strategy.warmup,
            "tf": settings.tf,
        },
        "readiness": [
            {
                "tf": r.tf,
                "label": r.label,
                "candles": r.candles,
                "warmup": r.warmup,
                "ready": r.ready,
                "missing": r.missing,
                "eta_seconds": r.eta_seconds,
                "eta_human": phase_mod.humanize_eta(r.eta_seconds),
            }
            for r in result.readiness
        ],
    }


@app.get("/api/paper")
def paper(conn: Conn, _: Auth) -> list[dict]:
    """Estado persistido de las corridas de paper trading."""
    return queries.paper_runs(conn)


@app.get("/api/coverage")
def coverage(conn: Conn, _: Auth) -> dict:
    return queries.coverage(conn)


@app.get("/api/runs")
def runs(conn: Conn, _: Auth, limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    return queries.runs(conn, limit)


@app.get("/api/runs/{run_id}/equity")
def equity(run_id: str, conn: Conn, _: Auth) -> list[dict]:
    curve = queries.equity_curve(conn, run_id)
    if not curve:
        raise HTTPException(status_code=404, detail=f"sin curva para {run_id}")
    return curve


@app.get("/api/fills")
def fills(
    conn: Conn,
    _: Auth,
    run_id: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict]:
    return queries.fills(conn, run_id, limit)


@app.get("/api/rejections")
def rejections(
    conn: Conn,
    _: Auth,
    run_id: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict]:
    return queries.rejections(conn, run_id, limit)
