"""Configuracion del servicio de API, leida del entorno."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from tradingbot.collector import TIMEFRAMES


@dataclass(frozen=True)
class ApiSettings:
    db_path: Path
    token: str | None
    book: str
    starting_cash: float
    cors_origins: list[str]
    # Deben coincidir con los del collector, o el panel evaluaria una corrida
    # distinta de la que realmente esta operando en papel.
    tf: int
    fast: int
    slow: int

    @classmethod
    def from_env(cls) -> "ApiSettings":
        origins = os.environ.get("CORS_ORIGINS", "")
        return cls(
            db_path=Path(os.environ.get("TRADING_DB_PATH", "/data/trading.db")),
            # Sin token la API queda abierta a quien alcance el contenedor.
            # El compose siempre define uno; esto es solo el fallback.
            token=os.environ.get("DASHBOARD_TOKEN") or None,
            book=os.environ.get("TRADING_BOOK", "usd_ars"),
            starting_cash=float(os.environ.get("STARTING_CASH", "33.27")),
            cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
            # Etiqueta ("1h"), la MISMA variable que usa el collector: si el
            # panel y el bot resolvieran timeframes distintos, el dashboard
            # evaluaria una corrida que no es la que esta operando.
            tf=TIMEFRAMES.get(os.environ.get("PAPER_TF", "1h"), 3600),
            fast=int(os.environ.get("PAPER_FAST", "10")),
            slow=int(os.environ.get("PAPER_SLOW", "30")),
        )


settings = ApiSettings.from_env()
