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

# El core del bot es la fuente de verdad del modelo de costos: la API no lo
# reimplementa, lo importa. Duplicar esos numeros seria garantizar que el
# panel y el bot terminen diciendo cosas distintas.
from tradingbot.costs import CostModel

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


@app.get("/api/status")
def status(_: Auth) -> dict:
    """Estado del sistema y los numeros que enmarcan todo lo demas."""
    return {
        "book": settings.book,
        "starting_cash": settings.starting_cash,
        # El panel es de solo lectura; que el bot opere en vivo es una
        # decision del proceso del bot, no de esta API.
        "live_trading": False,
        "phase": 0,
        "costs": {
            "taker_fee_bps": _costs.taker_fee_bps,
            "maker_fee_bps": _costs.maker_fee_bps,
            "half_spread_bps": _costs.half_spread_bps,
            "slippage_bps": _costs.slippage_bps,
            "round_trip_bps": _costs.round_trip_bps(),
            "breakeven_move_pct": _costs.breakeven_move_pct(),
        },
        "cost_per_round_trip": settings.starting_cash
        * _costs.round_trip_bps()
        / 10_000,
    }


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
