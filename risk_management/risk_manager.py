"""Position sizing, exits and order throttling. Every order passes through here."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Tuple

from misc.config import Config
from misc.utils import floor_to


@dataclass(frozen=True)
class PairRules:
    """Per-pair trading rules taken from the exchange's /v3/exchangeInfo."""
    pair: str
    amount_precision: int
    price_precision: int
    min_order: float  # order is OK if price * quantity > min_order


class RiskManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._order_times: Deque[float] = deque()
        self._last_buy_ts = 0.0

    # ---- exits ---------------------------------------------------------
    def forced_exit_reason(
        self, entry_price: float, entry_ts: float, price: float, now: float
    ) -> Optional[str]:
        """Stop-loss or max holding time. Returns a reason string, or None."""
        if entry_price > 0 and price <= entry_price * (1 - self.cfg.stop_loss_pct):
            return f"stop-loss ({price / entry_price - 1:.2%})"
        if now - entry_ts >= self.cfg.max_hold_minutes * 60:
            return f"max hold time ({self.cfg.max_hold_minutes} min)"
        return None

    # ---- throttling ----------------------------------------------------
    def can_buy_now(self, now: float) -> Tuple[bool, str]:
        while self._order_times and now - self._order_times[0] > 86_400:
            self._order_times.popleft()
        if len(self._order_times) >= self.cfg.max_orders_per_day:
            return False, "daily order cap reached"
        if now - self._last_buy_ts < self.cfg.min_seconds_between_buys:
            return False, "buy throttle"
        return True, ""

    def record_order(self, now: float, side: str) -> None:
        self._order_times.append(now)
        if side == "BUY":
            self._last_buy_ts = now

    # ---- sizing --------------------------------------------------------
    def size_buy(
        self, rules: PairRules, ask: float, equity: float, usd_free: float, exposure: float
    ) -> Tuple[float, str]:
        """How much to buy. Returns (quantity, reason_if_zero)."""
        if ask <= 0 or equity <= 0:
            return 0.0, "no price/equity"
        target_usd = equity * self.cfg.max_position_pct
        room_usd = equity * self.cfg.max_exposure_pct - exposure
        if room_usd <= 0:
            return 0.0, "max exposure reached"
        spend = min(target_usd, room_usd, usd_free / (1 + self.cfg.fee_rate))
        qty = floor_to(spend / ask, rules.amount_precision)
        if qty <= 0 or qty * ask <= rules.min_order:
            return 0.0, "below minimum order size"
        return qty, ""

    def size_sell(self, rules: PairRules, qty_free: float, bid: float) -> Tuple[float, str]:
        """Sell the whole free balance (rounded down to the allowed precision)."""
        qty = floor_to(qty_free, rules.amount_precision)
        if qty <= 0 or qty * bid <= rules.min_order:
            return 0.0, "dust position"
        return qty, ""
