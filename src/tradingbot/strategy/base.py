"""Interfaz de estrategia.

Contrato deliberadamente estrecho: una estrategia es una funcion pura de la
historia de velas a una senal. Sin estado oculto, sin acceso a la red, sin
saber cuanto capital hay. Eso la hace testeable y backtesteable, y hace que
el backtest y el vivo ejecuten exactamente el mismo codigo.

El tamano de la posicion NO es decision de la estrategia: es de risk.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from ..models import Candle, Signal


class Strategy(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def warmup(self) -> int:
        """Cuantas velas necesita antes de emitir senales validas."""

    @abstractmethod
    def signal(self, history: Sequence[Candle]) -> Signal:
        """Senal para la ULTIMA vela de `history`.

        `history` incluye solo velas ya cerradas. Mirar mas alla del ultimo
        elemento es look-ahead bias: el backtest daria resultados
        espectaculares e irreproducibles en vivo.
        """
