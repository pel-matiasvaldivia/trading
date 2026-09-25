"""Collector de larga duracion.

Acumula datos de mercado de forma sostenida. Es la Fase 1 del plan: sin
semanas de datos reales no hay backtest con significancia estadistica.

    python -m tradingbot.daemon --book usd_ars --interval 60
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from .collector import collect_once
from .config import Config
from .exchange.bitso import BitsoClient, BitsoError
from .storage import Store

log = logging.getLogger("collector")

_stop = False


def _handle_signal(signum, frame) -> None:
    """Apagado limpio: termina el ciclo actual antes de salir."""
    global _stop
    log.info("senal %s recibida, cerrando tras el ciclo actual", signum)
    _stop = True


def run(book: str, interval: int, limit: int, max_backoff: int = 900) -> int:
    cfg = Config.from_env(book=book)
    client = BitsoClient(cfg.credentials)
    backoff = interval

    with Store(cfg.db_path) as store:
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
            _sleep(interval)

    log.info("collector detenido")
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
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    book = args.book or Config.from_env().book
    log.info("collector arrancando: book=%s interval=%ss", book, args.interval)
    return run(book, args.interval, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
