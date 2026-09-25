"""Modelo de costos de operacion.

La razon de ser de este modulo: con capital chico los costos dominan el
resultado. Cualquier backtest que no los aplique miente. Todo precio de
ejecucion en este proyecto pasa por aca.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, replace
from typing import Sequence

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

    def affordable_amount(self, cash: float, reference_price: float) -> float:
        """Maxima cantidad comprable con `cash`, descontando spread y comision.

        Dimensionar contra el precio de referencia en vez del efectivo es un
        error silencioso: la orden sale mas cara de lo previsto y el broker la
        rechaza sin que quede registro de por que.
        """
        if cash <= 0 or reference_price <= 0:
            return 0.0
        execution_price = self.effective_price(Side.BUY, reference_price)
        fee_rate = self.taker_fee_bps / BPS
        return cash / (execution_price * (1.0 + fee_rate))


def from_samples(
    samples: Sequence[dict], fallback: CostModel | None = None
) -> tuple[CostModel, bool]:
    """Arma un CostModel con los costos medidos contra el exchange real.

    Devuelve `(modelo, calibrado)`. Si no hay muestras, devuelve el fallback
    y `False`: el panel necesita distinguir "medido" de "supuesto", porque
    confiar en un default como si fuera dato es exactamente como se construye
    un backtest que miente.

    El medio spread usa la MEDIANA de las muestras, no la ultima: el spread
    se abre y se cierra a lo largo del dia, y una sola lectura puede caer
    justo en el mejor momento y subestimar el costo real.
    """
    base = fallback or CostModel()
    spreads = [s["half_spread_bps"] for s in samples if s.get("half_spread_bps")]
    if not spreads:
        return base, False

    changes: dict = {"half_spread_bps": statistics.median(spreads)}
    # Las comisiones vienen de la cuenta y no fluctuan, asi que alcanza con
    # la lectura mas reciente que las traiga.
    for key in ("maker_fee_bps", "taker_fee_bps"):
        value = next((s[key] for s in samples if s.get(key) is not None), None)
        if value is not None:
            changes[key] = value
    return replace(base, **changes), True
