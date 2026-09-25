"""Datos sinteticos para probar el pipeline sin salida a internet.

ESTO NO ES DATA REAL. Sirve unicamente para verificar que collector ->
storage -> backtest -> metricas funcionan de punta a punta. Cualquier
resultado obtenido sobre estos datos no dice absolutamente nada sobre la
rentabilidad de una estrategia.
"""

from __future__ import annotations

import math
import random

from .models import Candle


def synthetic_candles(
    n: int = 500,
    start_price: float = 1000.0,
    tf: int = 3600,
    drift: float = 0.0,
    volatility: float = 0.01,
    seed: int = 42,
) -> list[Candle]:
    """Camino aleatorio con deriva. Reproducible via `seed`."""
    rng = random.Random(seed)
    candles: list[Candle] = []
    price = start_price

    for i in range(n):
        open_price = price
        shock = rng.gauss(drift, volatility)
        close = max(open_price * (1 + shock), 1e-6)
        wick = abs(rng.gauss(0, volatility / 2))
        candles.append(
            Candle(
                ts=i * tf,
                open=open_price,
                high=max(open_price, close) * (1 + wick),
                low=min(open_price, close) * (1 - wick),
                close=close,
                volume=abs(rng.gauss(10, 3)),
            )
        )
        price = close

    return candles


def sine_candles(
    n: int = 500, start_price: float = 1000.0, tf: int = 3600,
    amplitude: float = 0.02, period: int = 24,
) -> list[Candle]:
    """Mercado lateral puro: vuelve siempre al mismo nivel.

    El caso donde un cruce de medias opera mucho y pierde solo por costos.
    """
    candles = []
    for i in range(n):
        price = start_price * (1 + amplitude * math.sin(2 * math.pi * i / period))
        candles.append(Candle(i * tf, price, price, price, price, 10.0))
    return candles
