"""Cruce de medias moviles: la estrategia baseline.

No esta aca porque sea buena. Esta porque es la referencia contra la cual
medir cualquier idea futura: si una estrategia nueva no le gana a esto
DESPUES de costos, no vale la pena.
"""

from __future__ import annotations

from typing import Sequence

from ..models import Candle, Signal
from .base import Strategy


def sma(values: Sequence[float], window: int) -> float:
    if len(values) < window:
        raise ValueError(f"se necesitan {window} valores, hay {len(values)}")
    return sum(values[-window:]) / window


class SmaCross(Strategy):
    """Compra cuando la media rapida cruza por encima de la lenta."""

    name = "sma_cross"

    def __init__(self, fast: int = 10, slow: int = 30):
        if fast >= slow:
            raise ValueError("la media rapida debe ser menor que la lenta")
        self.fast = fast
        self.slow = slow

    @property
    def warmup(self) -> int:
        # +1 porque necesitamos la vela anterior para detectar el CRUCE,
        # no simplemente el estado actual de las medias.
        return self.slow + 1

    def signal(self, history: Sequence[Candle]) -> Signal:
        if len(history) < self.warmup:
            return Signal.HOLD

        closes = [c.close for c in history]
        prev_closes = closes[:-1]

        fast_now, slow_now = sma(closes, self.fast), sma(closes, self.slow)
        fast_prev, slow_prev = sma(prev_closes, self.fast), sma(prev_closes, self.slow)

        crossed_up = fast_prev <= slow_prev and fast_now > slow_now
        crossed_down = fast_prev >= slow_prev and fast_now < slow_now

        if crossed_up:
            return Signal.BUY
        if crossed_down:
            return Signal.SELL
        return Signal.HOLD


class BuyAndHold(Strategy):
    """Referencia honesta: comprar en la primera vela y no tocar nada.

    Muchas estrategias "rentables" pierden contra esto una vez que se
    descuentan las comisiones. Conviene tenerlo siempre a la vista.
    """

    name = "buy_and_hold"

    @property
    def warmup(self) -> int:
        return 1

    def signal(self, history: Sequence[Candle]) -> Signal:
        return Signal.BUY if len(history) == 1 else Signal.HOLD
