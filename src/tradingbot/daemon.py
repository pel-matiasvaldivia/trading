"""Proceso de larga duracion: collector y, opcionalmente, paper trading.

Es la Fase 1 del plan: sin semanas de datos reales no hay backtest con
significancia estadistica.

    python -m tradingbot.daemon --book usdc_ars --interval 60
    python -m tradingbot.daemon --book usdc_ars --paper --tf 1h

El motor de papel corre DENTRO de este proceso, despues de cada ciclo de
recoleccion. Es deliberado: asi hay un unico escritor sobre SQLite, y las
velas se procesan recien cuando ya se guardaron.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time

from . import costs as costs_mod
from .collector import TIMEFRAMES, collect_once
from .config import Config
from .exchange.bitso import BitsoClient, BitsoError
from .paper import PaperEngine
from .risk import RiskManager
from .storage import Store
from .strategy.sma_cross import SmaCross

log = logging.getLogger("collector")


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "si"}

_stop = False


def _handle_signal(signum, frame) -> None:
    """Apagado limpio: termina el ciclo actual antes de salir."""
    global _stop
    log.info("senal %s recibida, cerrando tras el ciclo actual", signum)
    _stop = True


def verify_book(client: BitsoClient, book: str) -> None:
    """Falla temprano y fuerte si el libro no existe en el exchange.

    Sin esto, un nombre de libro mal escrito produce un BitsoError por ciclo
    y el backoff lo convierte en un proceso que parece vivo pero nunca junta
    un solo dato. Un error de configuracion tiene que verse como tal.

    Si la consulta falla por red, NO se aborta: eso es un problema transitorio
    y el backoff del ciclo principal ya lo maneja.
    """
    try:
        available = [b["book"] for b in client.available_books()]
    except BitsoError as exc:
        log.warning("no se pudo verificar el libro %s (%s); se sigue igual", book, exc)
        return

    if book in available:
        return

    parts = set(book.split("_"))
    similar = [b for b in available if parts & set(b.split("_"))]
    raise SystemExit(
        f"El libro '{book}' no existe en Bitso.\n"
        f"Libros parecidos: {', '.join(sorted(similar)) or 'ninguno'}\n"
        f"Ver la lista completa con: python -m tradingbot books"
    )


def build_engine(store: Store, cfg: Config, book: str, tf: int, fast: int, slow: int) -> PaperEngine:
    """Motor de papel con los costos MEDIDOS, si los hay.

    Correr paper trading con costos supuestos produce evidencia que no sirve:
    el criterio de la fase se evalua neto de costos, asi que los costos tienen
    que ser los reales.
    """
    model, calibrated = costs_mod.from_samples(
        store.calibration_samples(book), cfg.costs
    )
    if not calibrated:
        log.warning(
            "sin calibracion para %s: se usan costos estimados. "
            "Correr 'calibrate' para medirlos contra el exchange.",
            book,
        )
    return PaperEngine(
        store=store,
        book=book,
        tf=tf,
        strategy=SmaCross(fast, slow),
        starting_cash=cfg.starting_cash,
        costs=model,
        risk=RiskManager(
            cfg.max_position_pct, cfg.max_daily_loss_pct, cfg.min_order_notional
        ),
    )


def run(
    book: str,
    interval: int,
    limit: int,
    paper: bool = False,
    tf: int = 3600,
    fast: int = 10,
    slow: int = 30,
    max_backoff: int = 900,
) -> int:
    cfg = Config.from_env(book=book)
    client = BitsoClient(cfg.credentials)
    verify_book(client, book)
    backoff = interval

    with Store(cfg.db_path) as store:
        engine = build_engine(store, cfg, book, tf, fast, slow) if paper else None
        if engine:
            log.info(
                "paper trading activo: run_id=%s tf=%ss warmup=%s velas",
                engine.run_id, tf, engine.strategy.warmup,
            )

        while not _stop:
            try:
                stats = collect_once(client, store, book, limit=limit)
                log.info(
                    "book=%s nuevos=%s total=%s",
                    book, stats["new_trades"], stats["total_trades"],
                )
                backoff = interval
            except BitsoError as exc:
                # Backoff exponencial con techo: un exchange caido no debe
                # convertirse en miles de requests fallidos por minuto.
                log.warning("fallo el ciclo: %s (reintento en %ss)", exc, backoff)
                _sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                continue

            if engine:
                # Un fallo del motor no debe matar la recoleccion: los datos
                # son lo unico irrecuperable si se pierden.
                try:
                    result = engine.step()
                    if not result.idle:
                        log.info(
                            "paper: %s velas, %s fills, %s rechazos, equity=%.4f%s",
                            result.processed, result.fills, result.rejections,
                            result.equity,
                            " [DETENIDO]" if result.halted else "",
                        )
                except Exception:
                    log.exception("el motor de papel fallo; la recoleccion sigue")

            _sleep(interval)

    log.info("proceso detenido")
    return 0


def _sleep(seconds: float) -> None:
    """Duerme en tramos cortos para responder rapido a una senal."""
    deadline = time.monotonic() + seconds
    while not _stop and time.monotonic() < deadline:
        time.sleep(min(1.0, deadline - time.monotonic()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tradingbot-collector")
    parser.add_argument("--book", default=None)
    parser.add_argument("--interval", type=int, default=60, help="segundos entre ciclos")
    parser.add_argument("--limit", type=int, default=100, help="trades por request")
    # Los defaults salen del entorno para que el compose configure todo con
    # variables y no haya que reescribir el `command` del servicio.
    parser.add_argument(
        "--paper",
        action="store_true",
        default=_env_flag("PAPER_ENABLED"),
        help="activa paper trading (o PAPER_ENABLED=1)",
    )
    parser.add_argument(
        "--tf", choices=sorted(TIMEFRAMES), default=os.environ.get("PAPER_TF", "1h")
    )
    parser.add_argument("--fast", type=int, default=int(os.environ.get("PAPER_FAST", "10")))
    parser.add_argument("--slow", type=int, default=int(os.environ.get("PAPER_SLOW", "30")))
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    book = args.book or Config.from_env().book
    log.info(
        "arrancando: book=%s interval=%ss paper=%s",
        book, args.interval, args.paper,
    )
    return run(
        book,
        args.interval,
        args.limit,
        paper=args.paper,
        tf=TIMEFRAMES[args.tf],
        fast=args.fast,
        slow=args.slow,
    )


if __name__ == "__main__":
    raise SystemExit(main())
