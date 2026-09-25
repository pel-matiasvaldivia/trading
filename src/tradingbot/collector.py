"""Recoleccion de datos de mercado.

Bitso v3 no expone un endpoint publico documentado de velas OHLCV, asi que
las construimos localmente agregando los trades publicos. Consecuencia
practica: no hay historia profunda disponible de entrada. El collector tiene
que correr sostenidamente para acumular datos antes de que un backtest sea
estadisticamente significativo.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .exchange.bitso import BitsoClient
from .models import Candle, Trade
from .storage import Store

TIMEFRAMES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


def aggregate_candles(trades: Iterable[Trade], timeframe: int) -> list[Candle]:
    """Agrupa trades en velas. Los intervalos sin trades no generan vela."""
    if timeframe <= 0:
        raise ValueError("timeframe debe ser positivo")

    buckets: dict[int, list[Trade]] = {}
    for trade in trades:
        buckets.setdefault(trade.ts - (trade.ts % timeframe), []).append(trade)

    candles = []
    for bucket_ts in sorted(buckets):
        group = sorted(buckets[bucket_ts], key=lambda t: t.tid)
        prices = [t.price for t in group]
        candles.append(
            Candle(
                ts=bucket_ts,
                open=prices[0],
                high=max(prices),
                low=min(prices),
                close=prices[-1],
                volume=sum(t.amount for t in group),
            )
        )
    return candles


def collect_once(
    client: BitsoClient, store: Store, book: str, limit: int = 100
) -> dict[str, int]:
    """Baja los trades recientes, los guarda y reconstruye las velas."""
    trades = client.trades(book, limit=limit)
    new_trades = store.upsert_trades(book, trades)

    all_trades = store.load_trades(book)
    written = {}
    for label, tf in TIMEFRAMES.items():
        candles = aggregate_candles(all_trades, tf)
        store.upsert_candles(book, tf, candles)
        written[label] = len(candles)

    return {"new_trades": new_trades, "total_trades": len(all_trades), **written}


def calibrate_costs(client: BitsoClient, book: str) -> dict[str, float]:
    """Mide el spread real del libro y lee las comisiones de la cuenta.

    Reemplazar los defaults de CostModel por estos numeros antes de confiar
    en cualquier backtest.
    """
    result: dict[str, float] = {"half_spread_bps": client.spread_bps(book) / 2.0}
    if client.credentials.available:
        fees = client.fees()
        for entry in fees.get("fees", []):
            if entry.get("book") == book:
                result["maker_fee_bps"] = float(entry["maker_fee_percent"]) * 100.0
                result["taker_fee_bps"] = float(entry["taker_fee_percent"]) * 100.0
                break
    return result
