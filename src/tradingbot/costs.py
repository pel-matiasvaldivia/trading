"""Modelo de costos de operacion.

La razon de ser de este modulo: con capital chico los costos dominan el
resultado. Cualquier backtest que no los aplique miente. Todo precio de
ejecucion en este proyecto pasa por aca.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Side

BPS = 10_000.0


@dataclass(frozen=True)
class CostModel:
    """Costos en basis points (1 bp = 0.01%).

    Los defaults son conservadores y corresponden al tier mas bajo de un
    exchange retail. Verificar los valores reales en la cuenta propia:
    subestimar comisiones es la forma mas comun de construir un backtest
    que parece rentable y no lo es.
    """

    taker_fee_bps: float = 65.0  # 0.65%
    maker_fee_bps: float = 50.0  # 0.50%
    half_spread_bps: float = 10.0  # mitad del spread del libro
    slippage_bps: float = 5.0  # deslizamiento extra por impacto

    def effective_price(self, side: Side, reference_price: float) -> float:
        """Precio al que realmente se ejecuta, peor que el de referencia.

        Comprar cruza contra el ask (paga mas), vender contra el bid
        (cobra menos). El signo nunca favorece a quien opera.
        """
        if reference_price <= 0:
            raise ValueError("reference_price debe ser positivo")
        adverse = (self.half_spread_bps + self.slippage_bps) / BPS
        if side is Side.BUY:
            return reference_price * (1.0 + adverse)
        return reference_price * (1.0 - adverse)

    def fee(self, notional: float, maker: bool = False) -> float:
        """Comision sobre el nocional, en moneda cotizada."""
        rate = (self.maker_fee_bps if maker else self.taker_fee_bps) / BPS
        return abs(notional) * rate

    def round_trip_bps(self, maker: bool = False) -> float:
        """Costo total de entrar y salir de una posicion, en bps.

        Es el umbral minimo que tiene que superar cualquier estrategia para
        no perder plata. Si la senal promedio captura menos que esto, no hay
        estrategia: hay una forma lenta de donar al exchange.
        """
        fee_bps = self.maker_fee_bps if maker else self.taker_fee_bps
        adverse_bps = self.half_spread_bps + self.slippage_bps
        return 2.0 * (fee_bps + adverse_bps)

    def breakeven_move_pct(self, maker: bool = False) -> float:
        """Movimiento de precio necesario para empatar, en porcentaje."""
        return self.round_trip_bps(maker) / 100.0
