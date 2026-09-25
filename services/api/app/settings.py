"""Configuracion del servicio de API, leida del entorno."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApiSettings:
    db_path: Path
    token: str | None
    book: str
    starting_cash: float
    cors_origins: list[str]

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
        )


settings = ApiSettings.from_env()
