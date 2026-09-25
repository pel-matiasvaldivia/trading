"""Interfaz de broker.

Backtest, paper y vivo implementan esta misma interfaz. Esa es la garantia
de que lo que se valido en papel es literalmente el mismo codigo que corre
con plata real: lo unico que cambia es la implementacion de `execute`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Fill, Order, PortfolioState


class Broker(ABC):
    @abstractmethod
    def execute(self, order: Order) -> Fill | None:
        """Ejecuta la orden. Devuelve None si no se llego a ejecutar."""

    @abstractmethod
    def state(self, ts: int, last_price: float) -> PortfolioState:
        """Foto del portafolio."""
