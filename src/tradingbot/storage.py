"""Persistencia en SQLite: velas, trades crudos y journal de decisiones.

El journal es la pieza mas importante del proyecto. Sin un registro de cada
decision y cada costo no se puede responder la unica pregunta que importa:
por que gane o perdi plata.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Sequence

from .models import Candle, Fill, Trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    book   TEXT    NOT NULL,
    tid    INTEGER NOT NULL,
    ts     INTEGER NOT NULL,
    price  REAL    NOT NULL,
    amount REAL    NOT NULL,
    side   TEXT    NOT NULL,
    PRIMARY KEY (book, tid)
);
CREATE INDEX IF NOT EXISTS idx_trades_book_ts ON trades (book, ts);

CREATE TABLE IF NOT EXISTS candles (
    book   TEXT    NOT NULL,
    tf     INTEGER NOT NULL,  -- timeframe en segundos
    ts     INTEGER NOT NULL,
    open   REAL    NOT NULL,
    high   REAL    NOT NULL,
    low    REAL    NOT NULL,
    close  REAL    NOT NULL,
    volume REAL    NOT NULL,
    PRIMARY KEY (book, tf, ts)
);

CREATE TABLE IF NOT EXISTS journal (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    TEXT    NOT NULL,
    ts        INTEGER NOT NULL,
    kind      TEXT    NOT NULL,  -- signal | order | fill | reject | equity
    book      TEXT,
    side      TEXT,
    amount    REAL,
    price     REAL,
    fee       REAL,
    equity    REAL,
    detail    TEXT
);
CREATE INDEX IF NOT EXISTS idx_journal_run ON journal (run_id, ts);

-- Costos medidos contra el exchange real. Se guarda cada medicion en vez de
-- pisarla: el spread varia a lo largo del dia, y una sola muestra puede ser
-- justo el peor o el mejor momento.
CREATE TABLE IF NOT EXISTS calibration (
    book            TEXT    NOT NULL,
    ts              INTEGER NOT NULL,
    maker_fee_bps   REAL,
    taker_fee_bps   REAL,
    half_spread_bps REAL    NOT NULL,
    PRIMARY KEY (book, ts)
);

-- Estado del portafolio de papel. Existe para que el paper trading sobreviva
-- a un reinicio del contenedor: sin esto, cada deploy borraria la evidencia
-- que la Fase 1 esta juntando.
CREATE TABLE IF NOT EXISTS paper_state (
    run_id        TEXT    PRIMARY KEY,
    book          TEXT    NOT NULL,
    tf            INTEGER NOT NULL,
    strategy      TEXT    NOT NULL,
    cash          REAL    NOT NULL,
    position      REAL    NOT NULL,
    avg_cost      REAL    NOT NULL,
    realized_pnl  REAL    NOT NULL,
    fees_paid     REAL    NOT NULL,
    last_candle_ts INTEGER,
    started_ts    INTEGER NOT NULL,
    updated_ts    INTEGER NOT NULL,
    halted        INTEGER NOT NULL DEFAULT 0,
    halt_reason   TEXT
);
"""


class Store:
    """Wrapper fino sobre sqlite3. Usar como context manager."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    # --- trades ---

    def upsert_trades(self, book: str, trades: Iterable[Trade]) -> int:
        rows = [(book, t.tid, t.ts, t.price, t.amount, t.side) for t in trades]
        if not rows:
            return 0
        cur = self.conn.executemany(
            "INSERT OR IGNORE INTO trades (book, tid, ts, price, amount, side)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()
        return cur.rowcount

    def load_trades(self, book: str) -> list[Trade]:
        cur = self.conn.execute(
            "SELECT tid, ts, price, amount, side FROM trades"
            " WHERE book = ? ORDER BY ts, tid",
            (book,),
        )
        return [Trade(**dict(r)) for r in cur.fetchall()]

    # --- candles ---

    def upsert_candles(self, book: str, tf: int, candles: Sequence[Candle]) -> int:
        rows = [
            (book, tf, c.ts, c.open, c.high, c.low, c.close, c.volume)
            for c in candles
        ]
        if not rows:
            return 0
        cur = self.conn.executemany(
            "INSERT OR REPLACE INTO candles"
            " (book, tf, ts, open, high, low, close, volume)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()
        return cur.rowcount

    def load_candles(self, book: str, tf: int, limit: int | None = None) -> list[Candle]:
        sql = (
            "SELECT ts, open, high, low, close, volume FROM candles"
            " WHERE book = ? AND tf = ? ORDER BY ts"
        )
        params: tuple = (book, tf)
        if limit is not None:
            sql += " DESC LIMIT ?"
            params = (book, tf, limit)
        rows = self.conn.execute(sql, params).fetchall()
        candles = [Candle(**dict(r)) for r in rows]
        return sorted(candles, key=lambda c: c.ts)

    # --- journal ---

    def log(self, run_id: str, ts: int, kind: str, **fields) -> None:
        cols = ["run_id", "ts", "kind"] + list(fields)
        placeholders = ", ".join("?" for _ in cols)
        self.conn.execute(
            f"INSERT INTO journal ({', '.join(cols)}) VALUES ({placeholders})",
            [run_id, ts, kind, *fields.values()],
        )
        self.conn.commit()

    def log_fill(self, run_id: str, fill: Fill, equity: float) -> None:
        self.log(
            run_id,
            fill.ts,
            "fill",
            book=fill.book,
            side=fill.side.value,
            amount=fill.amount,
            price=fill.price,
            fee=fill.fee,
            equity=equity,
            detail=fill.client_id,
        )

    # --- calibracion ---

    def save_calibration(
        self,
        book: str,
        ts: int,
        half_spread_bps: float,
        maker_fee_bps: float | None = None,
        taker_fee_bps: float | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO calibration"
            " (book, ts, maker_fee_bps, taker_fee_bps, half_spread_bps)"
            " VALUES (?, ?, ?, ?, ?)",
            (book, ts, maker_fee_bps, taker_fee_bps, half_spread_bps),
        )
        self.conn.commit()

    def calibration_samples(self, book: str, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT ts, maker_fee_bps, taker_fee_bps, half_spread_bps"
            " FROM calibration WHERE book = ? ORDER BY ts DESC LIMIT ?",
            (book, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- estado del paper trading ---

    def save_paper_state(self, state: dict) -> None:
        cols = list(state)
        placeholders = ", ".join("?" for _ in cols)
        self.conn.execute(
            f"INSERT OR REPLACE INTO paper_state ({', '.join(cols)})"
            f" VALUES ({placeholders})",
            list(state.values()),
        )
        self.conn.commit()

    def load_paper_state(self, run_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM paper_state WHERE run_id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def paper_runs(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM paper_state ORDER BY updated_ts DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def run_entries(self, run_id: str, kind: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM journal WHERE run_id = ?"
        params: tuple = (run_id,)
        if kind:
            sql += " AND kind = ?"
            params = (run_id, kind)
        sql += " ORDER BY ts, id"
        return self.conn.execute(sql, params).fetchall()
