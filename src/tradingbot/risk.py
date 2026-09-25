"""Capa de riesgo: el unico veto duro antes de ejecutar.

Esta capa existe para que un bug en la estrategia no se convierta en una
perdida total. Nada llega al broker sin pasar por aca, ni en papel ni en
vivo. Si una regla y la estrategia se contradicen, gana la regla.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Order, PortfolioState, Side


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str = ""
    adjusted_amount: float | None = None


class RiskManager:
    """Limites de exposicion, tamano minimo y kill switch diario."""

    def __init__(
        self,
        max_position_pct: float = 1.0,
        max_daily_loss_pct: float = 0.05,
        min_order_notional: float = 5.0,
    ):
        self.max_position_pct = max_position_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.min_order_notional = min_order_notional
        self._day_start_equity: float | None = None
        self._current_day: int | None = None
        self.halted = False
        self.halt_reason = ""

    # ------------------------------------------------------------------

    def _roll_day(self, state: PortfolioState) -> None:
        """Reinicia la referencia de perdida diaria al cambiar de dia."""
        day = state.ts // 86_400
        if self._current_day != day:
            self._current_day = day
            self._day_start_equity = state.equity

    def daily_pnl_pct(self, state: PortfolioState) -> float:
        if not self._day_start_equity:
            return 0.0
        return (state.equity - self._day_start_equity) / self._day_start_equity

    def check_kill_switch(self, state: PortfolioState) -> bool:
        """Activa el corte si la perdida diaria supera el limite.

        Una vez activado NO se desactiva solo: requiere intervencion manual.
        Un bot que se auto-reactiva despues de perder es un bot que insiste
        en perder.
        """
        self._roll_day(state)
        if self.halted:
            return True
        loss = -self.daily_pnl_pct(state)
        if loss >= self.max_daily_loss_pct:
            self.halted = True
            self.halt_reason = (
                f"kill switch: perdida diaria {loss:.2%} "
                f">= limite {self.max_daily_loss_pct:.2%}"
            )
            return True
        return False

    def reset(self) -> None:
        """Rearme manual tras revisar que paso. Nunca automatico."""
        self.halted = False
        self.halt_reason = ""

    # ------------------------------------------------------------------

    def approve(self, order: Order, state: PortfolioState) -> RiskDecision:
        """Aprueba, recorta o rechaza una orden."""
        if self.check_kill_switch(state):
            return RiskDecision(False, self.halt_reason or "operativa detenida")

        if order.amount <= 0:
            return RiskDecision(False, "cantidad no positiva")

        amount = order.amount
        notional = amount * order.reference_price

        if order.side is Side.BUY:
            max_notional = state.equity * self.max_position_pct
            current_notional = state.position * order.reference_price
            room = max_notional - current_notional
            if room <= 0:
                return RiskDecision(False, "limite de exposicion alcanzado")
            # Tambien limitado por el efectivo disponible.
            room = min(room, state.cash)
            if notional > room:
                amount = room / order.reference_price
                notional = amount * order.reference_price
            if notional > state.cash:
                return RiskDecision(False, "efectivo insuficiente")
        else:
            if amount > state.position:
                amount = state.position
                notional = amount * order.reference_price
            if amount <= 0:
                return RiskDecision(False, "sin posicion para vender")

        if notional < self.min_order_notional:
            return RiskDecision(
                False,
                f"nocional {notional:.2f} bajo el minimo {self.min_order_notional:.2f}",
            )

        if amount != order.amount:
            return RiskDecision(True, "cantidad recortada por limites", amount)
        return RiskDecision(True)
