"""Metricas de desempeno. Todas se calculan DESPUES de costos."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .models import Fill, Side

SECONDS_PER_YEAR = 365 * 24 * 3600


@dataclass(frozen=True)
class Metrics:
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    n_trades: int
    fees_paid: float
    fees_pct_of_start: float
    win_rate: float
    expectancy: float

    def render(self) -> str:
        return "\n".join(
            [
                f"  Retorno total      {self.total_return_pct:>8.2f} %",
                f"  Max drawdown       {self.max_drawdown_pct:>8.2f} %",
                f"  Sharpe (anualiz.)  {self.sharpe:>8.2f}",
                f"  Operaciones        {self.n_trades:>8d}",
                f"  Comisiones pagadas {self.fees_paid:>8.2f}"
                f"  ({self.fees_pct_of_start:.2f} % del capital inicial)",
                f"  Win rate           {self.win_rate:>8.2f} %",
                f"  Expectancy/trade   {self.expectancy:>8.4f}",
            ]
        )


def max_drawdown(equity: Sequence[float]) -> float:
    """Peor caida porcentual desde un maximo previo."""
    peak, worst = -math.inf, 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value - peak) / peak)
    return worst * 100.0


def sharpe_ratio(equity: Sequence[float], period_seconds: int) -> float:
    """Sharpe anualizado sobre los retornos por periodo, tasa libre = 0."""
    if len(equity) < 3:
        return 0.0
    returns = [
        (equity[i] - equity[i - 1]) / equity[i - 1]
        for i in range(1, len(equity))
        if equity[i - 1] > 0
    ]
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    periods_per_year = SECONDS_PER_YEAR / period_seconds
    return mean / std * math.sqrt(periods_per_year)


def round_trip_pnls(fills: Sequence[Fill]) -> list[float]:
    """PnL neto de cada ciclo compra-venta, con comisiones de ambos lados."""
    pnls: list[float] = []
    open_cost = 0.0
    open_amount = 0.0
    for fill in fills:
        if fill.side is Side.BUY:
            open_cost += fill.notional + fill.fee
            open_amount += fill.amount
        else:
            if open_amount <= 0:
                continue
            share = min(fill.amount, open_amount) / open_amount
            cost = open_cost * share
            pnls.append(fill.notional - fill.fee - cost)
            open_cost -= cost
            open_amount -= min(fill.amount, open_amount)
    return pnls


def compute(
    equity: Sequence[float],
    fills: Sequence[Fill],
    starting_cash: float,
    period_seconds: int,
) -> Metrics:
    if not equity:
        raise ValueError("curva de equity vacia")

    total_return = (equity[-1] - starting_cash) / starting_cash * 100.0
    fees = sum(f.fee for f in fills)
    pnls = round_trip_pnls(fills)
    wins = [p for p in pnls if p > 0]

    return Metrics(
        total_return_pct=total_return,
        max_drawdown_pct=max_drawdown(equity),
        sharpe=sharpe_ratio(equity, period_seconds),
        n_trades=len(fills),
        fees_paid=fees,
        fees_pct_of_start=fees / starting_cash * 100.0,
        win_rate=len(wins) / len(pnls) * 100.0 if pnls else 0.0,
        expectancy=sum(pnls) / len(pnls) if pnls else 0.0,
    )
