"""
shark_client.py
──────────────────────────────────────────────────────────────────────────────
Python Broker Connector for Shark Exchange REST API.
Engineered to mirror the official Shark Exchange SDK specification.

Protocol Details:
  • Base URL: https://api.sharkexchange.in
  • Headers:
      'api-key': <SHARK_API_KEY>
      'signature': <HMAC-SHA256 hex>
  • Timestamp: injected in query for GET, in JSON body for POST/DELETE
  • Routes:
      Ticker:    GET  /v1/market/ticker24Hr/{contractPair}
      Klines:    POST /v1/market/klines
      Depth:     GET  /v1/market/depth/{contractPair}
      Balances:  GET  /v1/wallet/futures-wallet/details
      Positions: GET  /v1/positions/OPEN
      Orders:    POST /v1/order/place-order
                 DELETE /v1/order/delete-order
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

# Load env variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env.example"))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

log = logging.getLogger("shark_client")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [SHARK-PY] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

API_KEY    = os.getenv("SHARK_API_KEY", "")
API_SECRET = os.getenv("SHARK_API_SECRET", "")
BASE_URL   = os.getenv("SHARK_BASE_URL", "https://api.sharkexchange.in").rstrip("/")
IS_LIVE    = os.getenv("LIVE", "false").lower() == "true"
IS_DRY_RUN = os.getenv("DRY_RUN", "true").lower() != "false"

MAX_RETRIES   = 3
RETRY_DELAY_S = 1.0
TIMEOUT_S     = 10


class SharkClientError(Exception):
    """Raised when Shark API returns a non-OK response."""


class SharkClient:
    def __init__(
        self,
        api_key:    str = API_KEY,
        api_secret: str = API_SECRET,
        base_url:   str = BASE_URL,
        dry_run:    bool = IS_DRY_RUN,
        live:       bool = IS_LIVE,
    ):
        self.api_key    = api_key
        self.api_secret = api_secret
        self.base_url   = base_url.rstrip("/")
        self.dry_run    = dry_run
        self.live       = live
        self._session   = requests.Session()
        self._session.headers.update({
            "Accept":       "application/json",
            "Content-Type": "application/json",
        })

    def _sign_query(self, query: dict) -> tuple[dict, str]:
        """Sign query parameters with HMAC-SHA256."""
        query["timestamp"] = str(int(time.time() * 1000))
        # Alphabetical sorting of query keys
        items = sorted(query.items())
        qs = urlencode(items)
        sig = hmac.new(
            self.api_secret.encode("utf-8"),
            qs.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return query, sig

    def _sign_body(self, body: dict) -> tuple[dict, str]:
        """Sign JSON body with HMAC-SHA256."""
        body["timestamp"] = str(int(time.time() * 1000))
        body_str = json.dumps(body, separators=(",", ":"))
        sig = hmac.new(
            self.api_secret.encode("utf-8"),
            body_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return body, sig

    def _request(
        self,
        method:  str,
        path:    str,
        query:   Optional[dict] = None,
        body:    Optional[dict] = None,
        auth:    bool = False,
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers = {}

        if query is None:
            query = {}

        if auth:
            if not self.api_key or not self.api_secret:
                raise SharkClientError("API Key and Secret required for authenticated requests")
            headers["api-key"] = self.api_key

            if method.upper() in ("GET", "DELETE") and body is None:
                query, sig = self._sign_query(query)
                headers["signature"] = sig
            else:
                if body is None:
                    body = {}
                body, sig = self._sign_body(body)
                headers["signature"] = sig

        delay = RETRY_DELAY_S
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._session.request(
                    method=method.upper(),
                    url=url,
                    params=query if query else None,
                    json=body if body is not None else None,
                    headers=headers,
                    timeout=TIMEOUT_S,
                )
                if resp.status_code == 429:
                    time.sleep(delay)
                    delay *= 2
                    continue

                resp.raise_for_status()
                data = resp.json()

                if isinstance(data, dict):
                    if "data" in data:
                        return data["data"]
                    if data.get("code", 0) != 0 and "code" in data:
                        raise SharkClientError(f"API Error {data.get('code')}: {data.get('message')}")

                return data

            except Exception as err:
                if attempt == MAX_RETRIES:
                    raise SharkClientError(f"Request to {path} failed: {err}") from err
                time.sleep(delay)
                delay *= 2

    # ── Market Data ────────────────────────────────────────────────────────────

    def get_ticker(self, symbol: str = "BTCUSDT") -> dict:
        """GET /v1/market/ticker24Hr/{contractPair}"""
        return self._request("GET", f"/v1/market/ticker24Hr/{symbol}", auth=False)

    def get_klines(
        self,
        symbol:     str = "BTCUSDT",
        interval:   str = "5m",
        limit:      int = 200,
        start_time: Optional[int] = None,
        end_time:   Optional[int] = None,
    ) -> list[dict]:
        """POST /v1/market/klines"""
        payload: dict = {"pair": symbol, "interval": interval, "limit": limit}
        if start_time: payload["startTime"] = start_time
        if end_time:   payload["endTime"]   = end_time
        return self._request("POST", "/v1/market/klines", body=payload, auth=False)

    def get_orderbook(self, symbol: str = "BTCUSDT", depth: int = 10) -> dict:
        """GET /v1/market/depth/{contractPair}"""
        return self._request("GET", f"/v1/market/depth/{symbol}", auth=False)

    # ── Authenticated Account Endpoints ────────────────────────────────────────

    def get_balances(self) -> dict:
        """GET /v1/wallet/futures-wallet/details"""
        return self._request("GET", "/v1/wallet/futures-wallet/details", auth=True)

    def get_positions(self, symbol: Optional[str] = None) -> list[dict]:
        """GET /v1/positions/OPEN"""
        query = {"pair": symbol} if symbol else {}
        return self._request("GET", "/v1/positions/OPEN", query=query, auth=True)

    # ── Orders ─────────────────────────────────────────────────────────────────

    def _order_guard(self) -> bool:
        return self.live and not self.dry_run

    def place_order(
        self,
        symbol:      str,
        side:        str,
        order_type:  str,
        qty:         float,
        price:       Optional[float] = None,
        stop_price:  Optional[float] = None,
        reduce_only: bool = False,
    ) -> dict:
        """POST /v1/order/place-order"""
        side       = side.upper()
        order_type = order_type.upper()

        if not self._order_guard():
            synthetic = {
                "ok":        True,
                "orderId":   f"PAPER-{int(time.time()*1000)}",
                "symbol":    symbol,
                "side":      side,
                "type":      order_type,
                "qty":       qty,
                "price":     price,
                "paper":     True,
                "timestamp": int(time.time() * 1000),
            }
            log.info("[PAPER] Order placed: %s", synthetic)
            return synthetic

        payload: dict = {
            "pair":       symbol,
            "side":       side,
            "type":       order_type,
            "quantity":   qty,
            "reduceOnly": reduce_only,
        }
        if price:      payload["price"]     = price
        if stop_price: payload["stopPrice"] = stop_price

        res = self._request("POST", "/v1/order/place-order", body=payload, auth=True)
        return {
            "ok":        True,
            "orderId":   res.get("orderId"),
            "symbol":    symbol,
            "side":      side,
            "type":      order_type,
            "qty":       qty,
            "paper":     False,
            "raw":       res,
        }

    def cancel_order(self, symbol: str, client_order_id: str) -> dict:
        """DELETE /v1/order/delete-order"""
        if not self._order_guard():
            return {"ok": True, "orderId": client_order_id, "paper": True}

        res = self._request("DELETE", "/v1/order/delete-order",
                            body={"clientOrderId": client_order_id}, auth=True)
        return {"ok": True, "orderId": client_order_id, "raw": res}

    def emergency_flatten(self, symbol: str) -> dict:
        """Close open positions."""
        if not self._order_guard():
            log.info("[PAPER] Emergency flatten simulated for %s", symbol)
            return {"ok": True, "symbol": symbol, "paper": True, "action": "flatten"}

        res = self._request("POST", "/v1/positions/closeAll",
                            body={"contractPair": symbol}, auth=True)
        return {"ok": True, "symbol": symbol, "raw": res}
