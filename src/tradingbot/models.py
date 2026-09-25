"""Tipos de datos compartidos por todas las capas."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class Signal(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class Candle:
    """Vela OHLCV. `ts` es epoch en segundos, inicio del intervalo."""

    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Trade:
    """Operacion individual del libro publico."""

    tid: int
    ts: int
    price: float
    amount: float
    side: str


@dataclass(frozen=True)
class Order:
    """Intencion de operar, antes de pasar por riesgo y ejecucion."""

    ts: int
    book: str
    side: Side
    amount: float  # en moneda base (ej. BTC en btc_ars)
    client_id: str
    reference_price: float  # precio de referencia al momento de decidir


@dataclass(frozen=True)
class Fill:
    """Resultado de una orden ejecutada."""

    ts: int
    book: str
    side: Side
    amount: float
    price: float  # precio efectivo, ya con spread y slippage
    fee: float  # en moneda cotizada
    client_id: str

    @property
    def notional(self) -> float:
        return self.amount * self.price


@dataclass(frozen=True)
class PortfolioState:
    """Foto del portafolio en un instante."""

    ts: int
    cash: float  # moneda cotizada (ARS, MXN, USD...)
    position: float  # moneda base
    last_price: float
    realized_pnl: float
    fees_paid: float

    @property
    def equity(self) -> float:
        return self.cash + self.position * self.last_price
