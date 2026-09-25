"""Evaluacion del criterio de salida de fase.

La Fase 1 termina cuando hay evidencia, no cuando parece que si. El criterio
es explicito y esta implementado aca para que lo conteste el codigo y no el
entusiasmo: al menos N operaciones completas simuladas, con expectancy
positiva DESPUES de costos.

Si el criterio no se cumple, no se avanza. Ese es todo el punto de tenerlo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from . import metrics
from .collector import TIMEFRAMES
from .models import Fill, Side
from .storage import Store
from .strategy.base import Strategy

# Umbral de la Fase 1. Con menos operaciones, cualquier expectancy positiva
# es tan probablemente suerte como habilidad.
REQUIRED_ROUND_TRIPS = 100


@dataclass
class TimeframeReadiness:
    """Cuanta historia hay en un timeframe frente a la que hace falta."""

    tf: int
    label: str
    candles: int
    warmup: int
    first_ts: int | None
    last_ts: int | None

    @property
    def ready(self) -> bool:
        return self.candles >= self.warmup

    @property
    def missing(self) -> int:
        return max(self.warmup - self.candles, 0)

    @property
    def seconds_per_candle(self) -> float | None:
        """Ritmo REAL observado, no el nominal del timeframe.

        En un libro poco liquido no hay una vela por intervalo: solo hay vela
        donde hubo trades. Estimar con el nominal daria una espera optimista.
        """
        if self.candles < 2 or self.first_ts is None or self.last_ts is None:
            return None
        return (self.last_ts - self.first_ts) / (self.candles - 1)

    @property
    def eta_seconds(self) -> float | None:
        """Espera estimada hasta tener el warmup completo."""
        rate = self.seconds_per_candle
        if self.ready:
            return 0.0
        if rate is None or rate <= 0:
            return None
        return self.missing * rate


@dataclass
class GateResult:
    """Veredicto del criterio de salida."""

    run_id: str | None
    round_trips: int
    required: int
    expectancy: float
    net_pnl: float
    fees_paid: float
    win_rate: float
    verdict: str  # sin_datos | insuficiente | rechazado | aprobado
    reason: str
    readiness: list[TimeframeReadiness] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.verdict == "aprobado"

    @property
    def progress(self) -> float:
        """Fraccion del camino recorrido hacia el umbral, entre 0 y 1."""
        if self.required <= 0:
            return 1.0
        return min(self.round_trips / self.required, 1.0)


def run_id_for_paper(book: str, tf: int, strategy: Strategy) -> str:
    """Reexporta el identificador del motor de papel, para no duplicarlo."""
    from .paper import run_id_for

    return run_id_for(book, tf, strategy)


def fills_for_run(store: Store, run_id: str) -> list[Fill]:
    """Reconstruye los fills de una corrida desde el journal."""
    fills = []
    for row in store.run_entries(run_id, kind="fill"):
        fills.append(
            Fill(
                ts=row["ts"],
                book=row["book"] or "",
                side=Side(row["side"]),
                amount=row["amount"] or 0.0,
                price=row["price"] or 0.0,
                fee=row["fee"] or 0.0,
                client_id=row["detail"] or "",
            )
        )
    return fills


def readiness(
    store: Store, book: str, strategy: Strategy
) -> list[TimeframeReadiness]:
    """Estado de la historia disponible en cada timeframe."""
    result = []
    for label, tf in TIMEFRAMES.items():
        candles = store.load_candles(book, tf)
        result.append(
            TimeframeReadiness(
                tf=tf,
                label=label,
                candles=len(candles),
                warmup=strategy.warmup,
                first_ts=candles[0].ts if candles else None,
                last_ts=candles[-1].ts if candles else None,
            )
        )
    return result


def evaluate(
    store: Store,
    book: str,
    strategy: Strategy,
    run_id: str | None = None,
    required: int = REQUIRED_ROUND_TRIPS,
) -> GateResult:
    """Contesta si la fase puede darse por cumplida."""
    ready = readiness(store, book, strategy)
    fills = fills_for_run(store, run_id) if run_id else []
    pnls = metrics.round_trip_pnls(fills)
    wins = [p for p in pnls if p > 0]
    expectancy = sum(pnls) / len(pnls) if pnls else 0.0
    fees = sum(f.fee for f in fills)

    if not fills:
        verdict = "sin_datos"
        reason = (
            "Todavia no hay operaciones simuladas. El collector tiene que "
            "acumular historia y el motor de papel tiene que llegar al warmup "
            "de la estrategia."
        )
    elif len(pnls) < required:
        verdict = "insuficiente"
        reason = (
            f"{len(pnls)} de {required} operaciones completas. Con menos, una "
            "expectancy positiva es tan probablemente suerte como habilidad."
        )
    elif expectancy > 0:
        verdict = "aprobado"
        reason = (
            f"{len(pnls)} operaciones con expectancy {expectancy:+.4f} neta de "
            "costos. El criterio de la fase se cumple."
        )
    else:
        verdict = "rechazado"
        reason = (
            f"{len(pnls)} operaciones con expectancy {expectancy:+.4f}: la "
            "estrategia pierde plata despues de costos. No se avanza de fase; "
            "se cambia la estrategia."
        )

    return GateResult(
        run_id=run_id,
        round_trips=len(pnls),
        required=required,
        expectancy=expectancy,
        net_pnl=sum(pnls),
        fees_paid=fees,
        win_rate=len(wins) / len(pnls) * 100.0 if pnls else 0.0,
        verdict=verdict,
        reason=reason,
        readiness=ready,
    )


def humanize_eta(seconds: float | None) -> str:
    """Espera en palabras. `None` significa que no hay ritmo para estimar."""
    if seconds is None:
        return "sin estimacion"
    if seconds <= 0:
        return "listo"
    units = (("d", 86400), ("h", 3600), ("min", 60))
    for label, size in units:
        if seconds >= size:
            return f"~{seconds / size:.0f} {label}"
    return "<1 min"
