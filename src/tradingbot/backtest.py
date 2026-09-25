"""Motor de backtest.

Recorre las velas una por una, en orden, y en cada paso solo ve el pasado.
Estrategia -> riesgo -> broker, el mismo pipeline que correra en vivo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Sequence

from . import metrics as metrics_mod
from .broker.paper import PaperBroker
from .costs import CostModel
from .models import Candle, Fill, Order, Side, Signal
from .risk import RiskManager
from .storage import Store
from .strategy.base import Strategy


@dataclass
class BacktestResult:
    run_id: str
    equity: list[float]
    fills: list[Fill]
    metrics: metrics_mod.Metrics
    rejections: list[tuple[int, str]]
    halted: bool
    halt_reason: str


def run(
    candles: Sequence[Candle],
    strategy: Strategy,
    starting_cash: float,
    costs: CostModel | None = None,
    risk: RiskManager | None = None,
    store: Store | None = None,
    book: str = "backtest",
) -> BacktestResult:
    if len(candles) < strategy.warmup:
        raise ValueError(
            f"{strategy.name} necesita {strategy.warmup} velas, hay {len(candles)}"
        )

    costs = costs or CostModel()
    risk = risk or RiskManager()
    broker = PaperBroker(starting_cash, costs)
    run_id = f"{strategy.name}-{uuid.uuid4().hex[:8]}"

    equity: list[float] = []
    rejections: list[tuple[int, str]] = []

    for i in range(len(candles)):
        history = candles[: i + 1]
        candle = candles[i]
        price = candle.close
        state = broker.state(candle.ts, price)

        signal = strategy.signal(history)
        if signal is not Signal.HOLD:
            side = Side.BUY if signal is Signal.BUY else Side.SELL
            # Tamano propuesto: entrar con todo el efectivo, salir con toda
            # la posicion. Riesgo lo recorta segun sus limites.
            amount = (
                costs.affordable_amount(state.cash, price)
                if side is Side.BUY
                else state.position
            )
            if amount > 0:
                order = Order(
                    ts=candle.ts,
                    book=book,
                    side=side,
                    amount=amount,
                    client_id=f"{run_id}-{i}",
                    reference_price=price,
                )
                decision = risk.approve(order, state)
                if decision.approved:
                    if decision.adjusted_amount is not None:
                        order = Order(
                            ts=order.ts,
                            book=order.book,
                            side=order.side,
                            amount=decision.adjusted_amount,
                            client_id=order.client_id,
                            reference_price=order.reference_price,
                        )
                    fill = broker.execute(order)
                    if fill is None:
                        # El broker rechazo la orden (efectivo o posicion
                        # insuficientes tras aplicar costos). Se registra:
                        # un rechazo silencioso es un backtest que miente.
                        rejections.append((candle.ts, "broker rechazo la orden"))
                        if store:
                            store.log(
                                run_id, candle.ts, "reject",
                                detail="broker rechazo la orden",
                            )
                    elif store:
                        store.log_fill(run_id, fill, broker.state(candle.ts, price).equity)
                else:
                    rejections.append((candle.ts, decision.reason))
                    if store:
                        store.log(
                            run_id, candle.ts, "reject", detail=decision.reason
                        )

        current_equity = broker.state(candle.ts, price).equity
        equity.append(current_equity)
        if store:
            store.log(run_id, candle.ts, "equity", equity=current_equity)

    period = _infer_period(candles)
    return BacktestResult(
        run_id=run_id,
        equity=equity,
        fills=broker.fills,
        metrics=metrics_mod.compute(equity, broker.fills, starting_cash, period),
        rejections=rejections,
        halted=risk.halted,
        halt_reason=risk.halt_reason,
    )


def _infer_period(candles: Sequence[Candle]) -> int:
    """Timeframe en segundos, deducido de la mediana de los saltos."""
    if len(candles) < 2:
        return 3600
    gaps = sorted(
        candles[i].ts - candles[i - 1].ts for i in range(1, len(candles))
    )
    median = gaps[len(gaps) // 2]
    return max(int(median), 1)
