"""Paper trading en vivo: la Fase 1 del plan.

Diferencia con `backtest.py`: el backtest recorre una historia cerrada de una
sola pasada; esto procesa velas a medida que van cerrando, sobrevive a
reinicios y acumula evidencia a lo largo de semanas.

El pipeline es el mismo — estrategia -> riesgo -> broker — y el broker es el
mismo `PaperBroker`. Esa es justamente la propiedad que hace que lo que se
valide aca sea lo que despues corra con plata real.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

from .broker.paper import PaperBroker
from .costs import CostModel
from .models import Candle, Order, Side, Signal
from .risk import RiskManager
from .storage import Store
from .strategy.base import Strategy


@dataclass
class StepResult:
    """Resultado de un ciclo del motor."""

    processed: int  # velas nuevas procesadas
    fills: int
    rejections: int
    equity: float
    halted: bool
    last_candle_ts: int | None

    @property
    def idle(self) -> bool:
        return self.processed == 0


def run_id_for(book: str, tf: int, strategy: Strategy) -> str:
    """Identificador estable: un reinicio continua la misma corrida.

    Si el run_id cambiara en cada arranque, cada deploy partiria la evidencia
    en pedazos y el criterio de salida de la fase nunca se alcanzaria.
    """
    return f"paper-{book}-{tf}s-{strategy.name}"


class PaperEngine:
    def __init__(
        self,
        store: Store,
        book: str,
        tf: int,
        strategy: Strategy,
        starting_cash: float,
        costs: CostModel | None = None,
        risk: RiskManager | None = None,
    ):
        self.store = store
        self.book = book
        self.tf = tf
        self.strategy = strategy
        self.starting_cash = starting_cash
        self.costs = costs or CostModel()
        self.risk = risk or RiskManager()
        self.run_id = run_id_for(book, tf, strategy)

        self.broker = PaperBroker(starting_cash, self.costs)
        self.last_candle_ts: int | None = None
        self.started_ts = int(time.time())
        self._restore()

    # ------------------------------------------------------------------

    def _restore(self) -> None:
        """Recupera el estado guardado, si existe."""
        state = self.store.load_paper_state(self.run_id)
        if not state:
            return
        self.broker.cash = state["cash"]
        self.broker.position = state["position"]
        self.broker._avg_cost = state["avg_cost"]
        self.broker.realized_pnl = state["realized_pnl"]
        self.broker.fees_paid = state["fees_paid"]
        self.last_candle_ts = state["last_candle_ts"]
        self.started_ts = state["started_ts"]
        if state["halted"]:
            # El kill switch no se rearma solo, ni siquiera reiniciando el
            # proceso. Reactivarlo es una decision humana.
            self.risk.halted = True
            self.risk.halt_reason = state["halt_reason"] or "detenido"

    def _persist(self, ts: int, equity: float) -> None:
        self.store.save_paper_state(
            {
                "run_id": self.run_id,
                "book": self.book,
                "tf": self.tf,
                "strategy": self.strategy.name,
                "cash": self.broker.cash,
                "position": self.broker.position,
                "avg_cost": self.broker._avg_cost,
                "realized_pnl": self.broker.realized_pnl,
                "fees_paid": self.broker.fees_paid,
                "last_candle_ts": self.last_candle_ts,
                "started_ts": self.started_ts,
                "updated_ts": int(time.time()),
                "halted": int(self.risk.halted),
                "halt_reason": self.risk.halt_reason or None,
            }
        )

    # ------------------------------------------------------------------

    def closed_candles(self, now: int | None = None) -> list[Candle]:
        """Velas ya CERRADAS, en orden.

        La vela mas reciente sigue recibiendo trades del collector: operar
        sobre ella seria decidir con datos incompletos, y la senal cambiaria
        a medida que llegan operaciones. Una vela en `ts` recien esta cerrada
        cuando el reloj paso `ts + tf`.
        """
        now = now if now is not None else int(time.time())
        candles = self.store.load_candles(self.book, self.tf)
        return [c for c in candles if c.ts + self.tf <= now]

    def step(self, now: int | None = None) -> StepResult:
        """Procesa las velas cerradas que todavia no se procesaron."""
        candles = self.closed_candles(now)
        fills = rejections = processed = 0

        for index, candle in enumerate(candles):
            if self.last_candle_ts is not None and candle.ts <= self.last_candle_ts:
                continue
            if index + 1 < self.strategy.warmup:
                # Sin historia suficiente la estrategia no puede opinar, pero
                # la vela igual queda marcada como vista.
                self.last_candle_ts = candle.ts
                processed += 1
                continue

            history = candles[: index + 1]
            outcome = self._process(candle, history)
            fills += outcome[0]
            rejections += outcome[1]
            self.last_candle_ts = candle.ts
            processed += 1

        last_price = candles[-1].close if candles else 0.0
        equity = self.broker.state(
            self.last_candle_ts or 0, last_price
        ).equity if candles else self.broker.cash

        if processed:
            self.store.log(
                self.run_id, self.last_candle_ts or 0, "equity", equity=equity
            )
        self._persist(self.last_candle_ts or 0, equity)

        return StepResult(
            processed=processed,
            fills=fills,
            rejections=rejections,
            equity=equity,
            halted=self.risk.halted,
            last_candle_ts=self.last_candle_ts,
        )

    def _process(self, candle: Candle, history: Sequence[Candle]) -> tuple[int, int]:
        price = candle.close
        state = self.broker.state(candle.ts, price)
        signal = self.strategy.signal(history)
        if signal is Signal.HOLD:
            return 0, 0

        side = Side.BUY if signal is Signal.BUY else Side.SELL
        amount = (
            self.costs.affordable_amount(state.cash, price)
            if side is Side.BUY
            else state.position
        )
        if amount <= 0:
            return 0, 0

        order = Order(
            ts=candle.ts,
            book=self.book,
            side=side,
            amount=amount,
            client_id=f"{self.run_id}-{candle.ts}",
            reference_price=price,
        )

        decision = self.risk.approve(order, state)
        if not decision.approved:
            self.store.log(
                self.run_id, candle.ts, "reject", detail=decision.reason
            )
            return 0, 1

        if decision.adjusted_amount is not None:
            order = Order(
                ts=order.ts,
                book=order.book,
                side=order.side,
                amount=decision.adjusted_amount,
                client_id=order.client_id,
                reference_price=order.reference_price,
            )

        fill = self.broker.execute(order)
        if fill is None:
            self.store.log(
                self.run_id, candle.ts, "reject", detail="broker rechazo la orden"
            )
            return 0, 1

        self.store.log_fill(
            self.run_id, fill, self.broker.state(candle.ts, price).equity
        )
        return 1, 0
