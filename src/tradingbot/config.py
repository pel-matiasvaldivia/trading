"""Configuracion del bot.

Las credenciales se leen SOLO de variables de entorno. Nunca se escriben
en disco ni se commitean. Ver .env.example.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .costs import CostModel

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "trading.db"


@dataclass(frozen=True)
class Credentials:
    """Credenciales de la API privada. Vacias = modo solo lectura publica."""

    api_key: str | None = None
    api_secret: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.api_secret)

    @classmethod
    def from_env(cls) -> "Credentials":
        return cls(
            api_key=os.environ.get("BITSO_API_KEY") or None,
            api_secret=os.environ.get("BITSO_API_SECRET") or None,
        )


@dataclass(frozen=True)
class Config:
    book: str = "usd_ars"
    db_path: Path = DEFAULT_DB_PATH
    costs: CostModel = field(default_factory=CostModel)
    credentials: Credentials = field(default_factory=Credentials.from_env)

    # --- Limites de riesgo (ver risk.py) ---
    starting_cash: float = 33.27
    max_position_pct: float = 1.0  # fraccion del equity por posicion
    max_daily_loss_pct: float = 0.05  # kill switch diario
    min_order_notional: float = 5.0  # minimo del exchange, en cotizada

    # --- Seguridad ---
    # El bot arranca SIEMPRE en papel. Pasar a real es explicito y manual.
    live_trading: bool = False

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        env_book = os.environ.get("TRADING_BOOK")
        if env_book and "book" not in overrides:
            overrides["book"] = env_book
        env_db = os.environ.get("TRADING_DB_PATH")
        if env_db and "db_path" not in overrides:
            overrides["db_path"] = Path(env_db)
        return cls(**overrides)
