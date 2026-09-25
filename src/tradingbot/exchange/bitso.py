"""Cliente de la API v3 de Bitso. Solo stdlib, sin dependencias.

Endpoints publicos: no requieren credenciales.
Endpoints privados: requieren BITSO_API_KEY / BITSO_API_SECRET en el entorno.

IMPORTANTE: este cliente NO implementa colocacion de ordenes ni retiros a
proposito. La API key de este proyecto debe crearse con permisos de SOLO
LECTURA. Agregar permiso de trading es una decision explicita para la Fase 2,
y el permiso de retiro no se habilita nunca.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..config import Credentials
from ..models import Trade

BASE_URL = "https://api.bitso.com"
USER_AGENT = "tradingbot/0.1 (+https://github.com/pel-matiasvaldivia/trading)"


class BitsoError(RuntimeError):
    """Error devuelto por la API o por el transporte."""


class BitsoClient:
    def __init__(
        self,
        credentials: Credentials | None = None,
        base_url: str = BASE_URL,
        timeout: float = 15.0,
    ):
        self.credentials = credentials or Credentials()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Transporte
    # ------------------------------------------------------------------

    def _sign(self, method: str, request_path: str, body: str = "") -> str:
        """Firma HMAC-SHA256 segun el esquema de Bitso v3."""
        if not self.credentials.available:
            raise BitsoError(
                "Faltan credenciales. Cargar BITSO_API_KEY y BITSO_API_SECRET "
                "como variables de entorno (nunca en el codigo)."
            )
        nonce = str(int(time.time() * 1000))
        message = f"{nonce}{method.upper()}{request_path}{body}"
        signature = hmac.new(
            self.credentials.api_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"Bitso {self.credentials.api_key}:{nonce}:{signature}"

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        private: bool = False,
    ) -> Any:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        request_path = f"{path}{query}"
        url = f"{self.base_url}{request_path}"

        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if private:
            headers["Authorization"] = self._sign(method, request_path)

        req = urllib.request.Request(url, method=method.upper(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise BitsoError(f"HTTP {exc.code} en {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise BitsoError(
                f"No se pudo alcanzar {url}: {exc.reason}. "
                "Si corre en un entorno con politica de red, verificar que "
                "api.bitso.com este permitido."
            ) from exc

        if not payload.get("success", False):
            raise BitsoError(f"La API rechazo la llamada: {payload.get('error')}")
        return payload["payload"]

    # ------------------------------------------------------------------
    # Endpoints publicos
    # ------------------------------------------------------------------

    def available_books(self) -> list[dict]:
        """Libros disponibles, con montos minimos y maximos por orden."""
        return self._request("GET", "/v3/available_books/")

    def ticker(self, book: str) -> dict:
        return self._request("GET", "/v3/ticker/", {"book": book})

    def order_book(self, book: str, aggregate: bool = True) -> dict:
        return self._request(
            "GET", "/v3/order_book/", {"book": book, "aggregate": str(aggregate).lower()}
        )

    def trades(self, book: str, limit: int = 100, marker: str | None = None) -> list[Trade]:
        """Trades publicos recientes, del mas nuevo al mas viejo."""
        params: dict[str, Any] = {"book": book, "limit": limit, "sort": "desc"}
        if marker:
            params["marker"] = marker
        raw = self._request("GET", "/v3/trades/", params)
        return [
            Trade(
                tid=int(t["tid"]),
                ts=_parse_ts(t["created_at"]),
                price=float(t["price"]),
                amount=float(t["amount"]),
                side=t["maker_side"],
            )
            for t in raw
        ]

    def spread_bps(self, book: str) -> float:
        """Spread actual del libro en basis points.

        Sirve para calibrar CostModel.half_spread_bps con datos reales en vez
        de suponer. En libros poco liquidos suele ser la mayor sorpresa.
        """
        ob = self.order_book(book, aggregate=True)
        if not ob.get("bids") or not ob.get("asks"):
            raise BitsoError(f"Libro {book} sin profundidad")
        bid = float(ob["bids"][0]["price"])
        ask = float(ob["asks"][0]["price"])
        mid = (bid + ask) / 2.0
        return (ask - bid) / mid * 10_000.0

    # ------------------------------------------------------------------
    # Endpoints privados (solo lectura)
    # ------------------------------------------------------------------

    def balance(self) -> dict[str, dict]:
        payload = self._request("GET", "/v3/balance/", private=True)
        return {b["currency"]: b for b in payload["balances"]}

    def fees(self) -> dict:
        """Comisiones reales de la cuenta. Usar esto para calibrar CostModel."""
        return self._request("GET", "/v3/fees/", private=True)

    def user_trades(self, book: str, limit: int = 100) -> list[dict]:
        return self._request(
            "GET", "/v3/user_trades/", {"book": book, "limit": limit}, private=True
        )


def _parse_ts(created_at: str) -> int:
    """Convierte el timestamp ISO-8601 de Bitso a epoch en segundos."""
    from datetime import datetime

    cleaned = created_at.replace("Z", "+00:00")
    return int(datetime.fromisoformat(cleaned).timestamp())
