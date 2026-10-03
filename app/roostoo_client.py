"""Thin wrapper around the Roostoo REST API (https://mock-api.roostoo.com).

- Signed endpoints use HMAC-SHA256 over the sorted "k=v&k=v" parameter string.
- Every request (success or failure) is logged to logs/api_log.csv.
- GETs are retried; POSTs (orders) are NEVER auto-retried, to avoid duplicate trades.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from misc.logger import CsvLogger
from misc.utils import utc_now_iso

log = logging.getLogger(__name__)

API_FIELDS = ["time_utc", "method", "path", "http_status", "success", "err_msg", "latency_ms"]


class RoostooError(Exception):
    """Raised when the API answers Success=false or cannot be reached."""


class RoostooClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str, log_dir: Path,
                 timeout: float = 10.0):
        self.api_key = api_key
        self._secret = api_secret.encode()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self._api_log = CsvLogger(Path(log_dir) / "api_log.csv", API_FIELDS)

    # ---- low level -----------------------------------------------------
    @staticmethod
    def _timestamp() -> str:
        return str(int(time.time() * 1000))

    def sign(self, total_params: str) -> str:
        return hmac.new(self._secret, total_params.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _total_params(params: Dict[str, Any]) -> str:
        return "&".join(f"{k}={params[k]}" for k in sorted(params))

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None,
                 signed: bool = False, with_ts: bool = True, retries: int = 3) -> Dict[str, Any]:
        attempts = retries if method == "GET" else 1
        last_exc: Optional[Exception] = None

        for attempt in range(1, attempts + 1):
            payload = dict(params or {})
            if with_ts:
                payload["timestamp"] = self._timestamp()  # fresh on every attempt
            total = self._total_params(payload)
            headers: Dict[str, str] = {}
            if signed:
                headers = {"RST-API-KEY": self.api_key, "MSG-SIGNATURE": self.sign(total)}

            url = f"{self.base_url}{path}"
            started = time.time()
            status: Any = ""
            try:
                if method == "GET":
                    resp = self.session.get(f"{url}?{total}" if total else url,
                                            headers=headers, timeout=self.timeout)
                else:
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
                    resp = self.session.post(url, data=total, headers=headers,
                                             timeout=self.timeout)
                status = resp.status_code
                resp.raise_for_status()
                data = resp.json()
                self._log_call(method, path, status, data.get("Success", True),
                               data.get("ErrMsg", ""), started)
                return data
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                self._log_call(method, path, status, False, str(exc)[:200], started)
                log.warning("%s %s failed (attempt %d/%d): %s", method, path, attempt, attempts, exc)
                if attempt < attempts:
                    time.sleep(min(2 ** attempt, 10))

        raise RoostooError(f"{method} {path} failed: {last_exc}") from last_exc

    def _log_call(self, method: str, path: str, status: Any, success: Any, err: str,
                  started: float) -> None:
        self._api_log.write(
            time_utc=utc_now_iso(), method=method, path=path, http_status=status,
            success=success, err_msg=err, latency_ms=int((time.time() - started) * 1000),
        )

    @staticmethod
    def _check(data: Dict[str, Any], what: str) -> Dict[str, Any]:
        if not data.get("Success", False):
            raise RoostooError(f"{what}: {data.get('ErrMsg') or 'unknown error'}")
        return data

    # ---- public endpoints ----------------------------------------------
    def server_time(self) -> int:
        return int(self._request("GET", "/v3/serverTime", with_ts=False)["ServerTime"])

    def exchange_info(self) -> Dict[str, Any]:
        return self._request("GET", "/v3/exchangeInfo", with_ts=False)

    def ticker(self, pair: Optional[str] = None) -> Dict[str, Dict[str, float]]:
        """Returns {pair: {MaxBid, MinAsk, LastPrice, ...}}. All pairs if `pair` is None."""
        params = {"pair": pair} if pair else {}
        data = self._check(self._request("GET", "/v3/ticker", params), "ticker")
        return data.get("Data", {})

    # ---- signed endpoints ----------------------------------------------
    def balance(self) -> Dict[str, Dict[str, float]]:
        """Returns {coin: {Free, Lock}}."""
        data = self._check(self._request("GET", "/v3/balance", signed=True), "balance")
        return data.get("Wallet", {})

    def place_order(self, pair: str, side: str, quantity: str, order_type: str = "MARKET",
                    price: Optional[float] = None) -> Dict[str, Any]:
        """Places an order and returns the raw response (check ['Success'])."""
        params: Dict[str, Any] = {
            "pair": pair, "side": side.upper(), "type": order_type.upper(), "quantity": quantity,
        }
        if order_type.upper() == "LIMIT":
            if price is None:
                raise ValueError("LIMIT orders need a price")
            params["price"] = price
        return self._request("POST", "/v3/place_order", params, signed=True)

    def pending_count(self) -> Dict[str, Any]:
        return self._request("GET", "/v3/pending_count", signed=True)

    def cancel_order(self, pair: Optional[str] = None, order_id: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if order_id:
            params["order_id"] = order_id
        elif pair:
            params["pair"] = pair
        return self._request("POST", "/v3/cancel_order", params, signed=True)
