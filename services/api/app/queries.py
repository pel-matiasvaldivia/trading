"""Lecturas sobre la base del bot.

Se abre SIEMPRE en modo solo lectura: el dashboard observa, no muta. Si un
bug del panel pudiera escribir en la base del bot, el panel seria parte del
sistema de trading, y no lo es.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from tradingbot.models import Candle

TIMEFRAMES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


def connect(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def coverage(conn: sqlite3.Connection) -> dict[str, Any]:
    """Cuantos datos hay y de que periodo. Responde: ¿ya puedo confiar?"""
    books = _rows(
        conn,
        "SELECT book, COUNT(*) AS trades, MIN(ts) AS first_ts, MAX(ts) AS last_ts"
        " FROM trades GROUP BY book ORDER BY trades DESC",
    )
    candles = _rows(
        conn,
        "SELECT book, tf, COUNT(*) AS n, MIN(ts) AS first_ts, MAX(ts) AS last_ts"
        " FROM candles GROUP BY book, tf ORDER BY book, tf",
    )
    label_by_tf = {v: k for k, v in TIMEFRAMES.items()}
    for row in candles:
        row["tf_label"] = label_by_tf.get(row["tf"], f"{row['tf']}s")
    return {"books": books, "candles": candles}


def runs(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Corridas registradas en el journal, de la mas reciente a la mas vieja."""
    return _rows(
        conn,
        "SELECT run_id,"
        "       MIN(ts) AS first_ts,"
        "       MAX(ts) AS last_ts,"
        "       SUM(kind = 'fill') AS fills,"
        "       SUM(kind = 'reject') AS rejects,"
        "       MAX(id) AS seq"
        " FROM journal GROUP BY run_id ORDER BY seq DESC LIMIT ?",
        (limit,),
    )


def equity_curve(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    return _rows(
        conn,
        "SELECT ts, equity FROM journal"
        " WHERE run_id = ? AND kind = 'equity' AND equity IS NOT NULL"
        " ORDER BY ts, id",
        (run_id,),
    )


def fills(conn: sqlite3.Connection, run_id: str | None = None, limit: int = 100) -> list[dict]:
    sql = (
        "SELECT run_id, ts, book, side, amount, price, fee, equity FROM journal"
        " WHERE kind = 'fill'"
    )
    params: tuple = ()
    if run_id:
        sql += " AND run_id = ?"
        params = (run_id,)
    sql += " ORDER BY ts DESC, id DESC LIMIT ?"
    return _rows(conn, sql, (*params, limit))


def rejections(conn: sqlite3.Connection, run_id: str | None = None, limit: int = 100) -> list[dict]:
    """Ordenes que la capa de riesgo o el broker no dejaron pasar.

    Es la vista mas util del panel: un backtest lindo con muchos rechazos
    esta ocultando que la estrategia pide cosas que no se pueden hacer.
    """
    sql = "SELECT run_id, ts, detail FROM journal WHERE kind = 'reject'"
    params: tuple = ()
    if run_id:
        sql += " AND run_id = ?"
        params = (run_id,)
    sql += " ORDER BY ts DESC, id DESC LIMIT ?"
    return _rows(conn, sql, (*params, limit))


class ReadOnlyStore:
    """Vista de solo lectura con la interfaz minima que `phase` necesita.

    `Store` abre la base para escritura y aplica el esquema al construirse,
    asi que la API no puede usarla: monta el volumen con :ro. Esta clase
    expone solo los dos metodos que la evaluacion de fase consume, sobre la
    conexion de solo lectura que ya usa el resto del panel.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def load_candles(self, book: str, tf: int, limit: int | None = None) -> list[Candle]:
        rows = self.conn.execute(
            "SELECT ts, open, high, low, close, volume FROM candles"
            " WHERE book = ? AND tf = ? ORDER BY ts",
            (book, tf),
        ).fetchall()
        return [Candle(**dict(r)) for r in rows]

    def run_entries(self, run_id: str, kind: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM journal WHERE run_id = ?"
        params: tuple = (run_id,)
        if kind:
            sql += " AND kind = ?"
            params = (run_id, kind)
        sql += " ORDER BY ts, id"
        return self.conn.execute(sql, params).fetchall()

    def calibration_samples(self, book: str, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT ts, maker_fee_bps, taker_fee_bps, half_spread_bps"
            " FROM calibration WHERE book = ? ORDER BY ts DESC LIMIT ?",
            (book, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def paper_runs(conn: sqlite3.Connection) -> list[dict]:
    """Corridas de paper trading en curso, con su estado persistido."""
    rows = conn.execute(
        "SELECT * FROM paper_state ORDER BY updated_ts DESC"
    ).fetchall()
    return [dict(r) for r in rows]
