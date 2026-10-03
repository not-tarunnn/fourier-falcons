"""The trading loop: data -> features -> signal -> risk checks -> order."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, TypeVar

from app.roostoo_client import RoostooClient
from data_preprocessing.features import Features, compute_features
from data_preprocessing.price_buffer import PriceBuffer
from misc.config import Config
from misc.logger import CsvLogger
from misc.state import StateStore
from misc.utils import fmt_qty, utc_now_iso
from risk_management.risk_manager import PairRules, RiskManager
from strategy.mean_reversion import MeanReversionStrategy

log = logging.getLogger(__name__)
T = TypeVar("T")

TRADE_FIELDS = [
    "time_utc", "pair", "side", "type", "quantity", "ref_price", "fill_price", "status",
    "order_id", "commission", "success", "err_msg", "reason", "zscore", "dry_run",
]


@dataclass
class Snapshot:
    usd_free: float
    equity: float
    exposure: float
    free: Dict[str, float]    # pair -> free coin quantity
    total: Dict[str, float]   # pair -> free + locked quantity


class TradingBot:
    def __init__(self, cfg: Config, client: RoostooClient, buffer: PriceBuffer,
                 strategy: MeanReversionStrategy, risk: RiskManager, state: StateStore):
        self.cfg = cfg
        self.client = client
        self.buffer = buffer
        self.strategy = strategy
        self.risk = risk
        self.state = state
        self.rules: Dict[str, PairRules] = {}
        self.pairs: List[str] = []
        self.trade_log = CsvLogger(Path(cfg.log_dir) / "trades.csv", TRADE_FIELDS)

    # ---- startup -------------------------------------------------------
    def setup(self) -> None:
        self._check_clock()
        info = self._retry(self.client.exchange_info)
        trade_pairs = info.get("TradePairs", {})
        for pair in self.cfg.pairs:
            meta = trade_pairs.get(pair)
            if not meta or not meta.get("CanTrade", False):
                log.warning("Skipping %s (not listed / not tradable)", pair)
                continue
            self.rules[pair] = PairRules(
                pair=pair,
                amount_precision=int(meta["AmountPrecision"]),
                price_precision=int(meta["PricePrecision"]),
                min_order=float(meta["MiniOrder"]),
            )
        self.pairs = list(self.rules)
        if not self.pairs:
            raise RuntimeError(f"None of {self.cfg.pairs} are tradable. Available: {list(trade_pairs)}")
        log.info("Trading %d pairs: %s | dry_run=%s", len(self.pairs), ", ".join(self.pairs),
                 self.cfg.dry_run)

    def _check_clock(self) -> None:
        """Signed requests are rejected if the local clock is >60s off the server."""
        try:
            skew = abs(time.time() * 1000 - self.client.server_time()) / 1000
            if skew > 30:
                log.warning("Local clock is %.0fs off the server - run `sudo chronyc makestep`", skew)
        except Exception as exc:  # non-fatal
            log.warning("Clock check failed: %s", exc)

    def _retry(self, fn: Callable[[], T], attempts: int = 5, delay: float = 5.0) -> T:
        for i in range(1, attempts + 1):
            try:
                return fn()
            except Exception as exc:
                if i == attempts:
                    raise
                log.warning("Startup call failed (%s) - retrying in %.0fs", exc, delay)
                time.sleep(delay)
        raise RuntimeError("unreachable")

    # ---- main loop -----------------------------------------------------
    def run_forever(self, stop: threading.Event) -> None:
        errors = 0
        while not stop.is_set():
            started = time.time()
            try:
                self.run_cycle()
                errors = 0
            except Exception:
                errors += 1
                log.exception("Cycle failed (%d in a row)", errors)
            wait = max(1.0, self.cfg.poll_seconds * (1 + min(errors, 5)) - (time.time() - started))
            stop.wait(wait)
        log.info("Stopped.")

    def run_cycle(self) -> None:
        now = time.time()
        tickers = self.client.ticker()  # one request returns every pair
        for pair in self.pairs:
            t = tickers.get(pair)
            if t and t.get("LastPrice"):
                self.buffer.add(pair, float(t["LastPrice"]), now)

        snap = self._snapshot(self.client.balance(), tickers)

        exits: List[Tuple[str, str, Optional[Features]]] = []
        entries: List[Tuple[float, str, str, Features]] = []

        for pair in self.pairs:
            t = tickers.get(pair)
            if not t or not t.get("LastPrice"):
                continue
            last = float(t["LastPrice"])
            feats = compute_features(self.buffer.prices(pair), self.cfg.window)
            in_pos = snap.free[pair] * last > self.rules[pair].min_order
            self._sync_state(pair, in_pos, last, now)

            if in_pos:
                pos = self.state.positions[pair]
                forced = self.risk.forced_exit_reason(pos["entry_price"], pos["entry_ts"], last, now)
                signal = self.strategy.generate(pair, feats, True)
                if forced:
                    exits.append((pair, forced, feats))
                elif signal.action == "SELL":
                    exits.append((pair, signal.reason, feats))
            else:
                signal = self.strategy.generate(pair, feats, False)
                if signal.action == "BUY" and feats is not None:
                    entries.append((feats.zscore, pair, signal.reason, feats))

            log.debug("%s last=%s z=%s in_pos=%s", pair, last,
                      f"{feats.zscore:.2f}" if feats else "n/a", in_pos)

        # Exits first (frees cash), then entries - most oversold first.
        for pair, reason, feats in exits:
            bid = float(tickers[pair].get("MaxBid") or tickers[pair]["LastPrice"])
            if self._sell(pair, reason, feats, bid, snap, now):
                snap = self._snapshot(self.client.balance(), tickers)

        for _, pair, reason, feats in sorted(entries, key=lambda e: e[0]):
            ask = float(tickers[pair].get("MinAsk") or tickers[pair]["LastPrice"])
            if self._buy(pair, reason, feats, ask, snap, now):
                snap = self._snapshot(self.client.balance(), tickers)

        held = [p for p in self.pairs if snap.total[p] > 0 and p in self.state.positions]
        log.info("equity=%.2f cash=%.2f exposure=%.2f positions=%s",
                 snap.equity, snap.usd_free, snap.exposure, held or "none")

    # ---- helpers -------------------------------------------------------
    def _snapshot(self, wallet: Dict[str, Dict[str, float]], tickers: Dict[str, dict]) -> Snapshot:
        usd = wallet.get("USD", {})
        usd_free = float(usd.get("Free", 0))
        usd_total = usd_free + float(usd.get("Lock", 0))
        free: Dict[str, float] = {}
        total: Dict[str, float] = {}
        exposure = 0.0
        for pair in self.pairs:
            w = wallet.get(pair.split("/")[0], {})
            free[pair] = float(w.get("Free", 0))
            total[pair] = free[pair] + float(w.get("Lock", 0))
            exposure += total[pair] * float(tickers.get(pair, {}).get("LastPrice") or 0)
        return Snapshot(usd_free, usd_total + exposure, exposure, free, total)

    def _sync_state(self, pair: str, in_pos: bool, last: float, now: float) -> None:
        """Keep the local entry-price book consistent with what the wallet really holds."""
        positions = self.state.positions
        if in_pos and pair not in positions:
            positions[pair] = {"entry_price": last, "entry_ts": now}
            self.state.save()
            log.warning("%s: holding coins with no entry record - using current price", pair)
        elif not in_pos and pair in positions:
            positions.pop(pair)
            self.state.save()

    def _buy(self, pair: str, reason: str, feats: Features, ask: float,
             snap: Snapshot, now: float) -> bool:
        ok, why = self.risk.can_buy_now(now)
        if not ok:
            log.info("Skip BUY %s: %s", pair, why)
            return False
        qty, why = self.risk.size_buy(self.rules[pair], ask, snap.equity, snap.usd_free, snap.exposure)
        if qty <= 0:
            log.info("Skip BUY %s: %s", pair, why)
            return False
        return self._place(pair, "BUY", qty, ask, reason, feats, now)

    def _sell(self, pair: str, reason: str, feats: Optional[Features], bid: float,
              snap: Snapshot, now: float) -> bool:
        qty, why = self.risk.size_sell(self.rules[pair], snap.free[pair], bid)
        if qty <= 0:
            log.info("Skip SELL %s: %s", pair, why)
            return False
        return self._place(pair, "SELL", qty, bid, reason, feats, now)

    def _place(self, pair: str, side: str, qty: float, ref_price: float, reason: str,
               feats: Optional[Features], now: float) -> bool:
        qty_str = fmt_qty(qty, self.rules[pair].amount_precision)
        row = {
            "time_utc": utc_now_iso(), "pair": pair, "side": side, "type": "MARKET",
            "quantity": qty_str, "ref_price": ref_price, "reason": reason,
            "zscore": f"{feats.zscore:.3f}" if feats else "", "dry_run": self.cfg.dry_run,
        }
        log.info("%s %s qty=%s ~%.4f | %s", side, pair, qty_str, ref_price, reason)
        try:
            resp = self.client.place_order(pair, side, qty_str, "MARKET")
        except Exception as exc:
            # Unknown outcome (e.g. timeout): the next cycle re-reads the wallet to reconcile.
            log.error("Order request failed: %s", exc)
            self.trade_log.write(**row, success=False, err_msg=str(exc)[:200])
            return False

        detail = resp.get("OrderDetail") or {}
        success = bool(resp.get("Success"))
        fill_price = float(detail.get("FilledAverPrice") or ref_price)
        self.trade_log.write(
            **row, fill_price=fill_price, status=detail.get("Status", ""),
            order_id=detail.get("OrderID", ""), commission=detail.get("CommissionChargeValue", ""),
            success=success, err_msg=resp.get("ErrMsg", ""),
        )
        if not success:
            log.warning("Order rejected: %s", resp.get("ErrMsg"))
            return False

        self.risk.record_order(now, side)
        if detail.get("Status") == "FILLED":
            if side == "BUY":
                self.state.positions[pair] = {"entry_price": fill_price, "entry_ts": now}
            else:
                self.state.positions.pop(pair, None)
            self.state.save()
        return True
