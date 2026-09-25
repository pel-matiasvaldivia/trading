"""Broker de papel: ejecuta contra el modelo de costos, no contra el mercado.

Asume llenado completo al precio efectivo. Es optimista respecto del vivo
(no modela ordenes parcialmente llenas ni rechazos), asi que los resultados
en papel deben leerse como una cota SUPERIOR de lo alcanzable.
"""

from __future__ import annotations

from ..costs import CostModel
from ..models import Fill, Order, PortfolioState, Side
from .base import Broker


class PaperBroker(Broker):
    def __init__(self, starting_cash: float, costs: CostModel | None = None):
        if starting_cash <= 0:
            raise ValueError("starting_cash debe ser positivo")
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.position = 0.0
        self.costs = costs or CostModel()
        self.fees_paid = 0.0
        self.realized_pnl = 0.0
        self.fills: list[Fill] = []
        # Costo promedio de la posicion abierta, para PnL realizado.
        self._avg_cost = 0.0

    def execute(self, order: Order) -> Fill | None:
        price = self.costs.effective_price(order.side, order.reference_price)
        notional = order.amount * price
        fee = self.costs.fee(notional)

        if order.side is Side.BUY:
            # Tolerancia relativa: dimensionar una orden "con todo el
            # efectivo" da exactamente cash, y el error de punto flotante no
            # debe convertir eso en un rechazo.
            if notional + fee > self.cash * (1.0 + 1e-9):
                return None
            # Costo promedio ponderado, incluyendo la comision de entrada.
            total_cost = self._avg_cost * self.position + notional + fee
            self.position += order.amount
            self._avg_cost = total_cost / self.position if self.position else 0.0
            self.cash -= notional + fee
        else:
            if order.amount > self.position + 1e-12:
                return None
            self.realized_pnl += notional - fee - self._avg_cost * order.amount
            self.position -= order.amount
            if self.position <= 1e-12:
                self.position = 0.0
                self._avg_cost = 0.0
            self.cash += notional - fee

        self.fees_paid += fee
        fill = Fill(
            ts=order.ts,
            book=order.book,
            side=order.side,
            amount=order.amount,
            price=price,
            fee=fee,
            client_id=order.client_id,
        )
        self.fills.append(fill)
        return fill

    def state(self, ts: int, last_price: float) -> PortfolioState:
        return PortfolioState(
            ts=ts,
            cash=self.cash,
            position=self.position,
            last_price=last_price,
            realized_pnl=self.realized_pnl,
            fees_paid=self.fees_paid,
        )
