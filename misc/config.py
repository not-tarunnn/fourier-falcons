"""All settings in one place. Values come from environment variables / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

ROOT = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Tiny .env loader (KEY=VALUE per line). Real env vars take priority."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if value[:1] in {'"', "'"}:
            value = value.strip(value[0])
        else:
            value = value.split(" #")[0].strip()  # drop inline comments
        os.environ.setdefault(key.strip(), value)


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    # --- API ---
    api_key: str
    api_secret: str
    base_url: str
    # --- Run mode ---
    pairs: Tuple[str, ...]
    poll_seconds: int
    dry_run: bool
    paper_cash: float
    # --- Strategy (mean reversion) ---
    window: int            # number of price samples in the rolling window
    entry_z: float         # buy when z-score <= -entry_z
    exit_z: float          # sell when z-score >= exit_z (0 = back at the mean)
    min_edge_pct: float    # require at least this % distance to the mean (covers fees)
    # --- Risk ---
    max_position_pct: float
    max_exposure_pct: float
    stop_loss_pct: float
    max_hold_minutes: int
    min_seconds_between_buys: int
    max_orders_per_day: int
    fee_rate: float
    # --- Paths / logging ---
    log_level: str
    log_dir: Path
    data_dir: Path

    @classmethod
    def from_env(cls) -> "Config":
        _load_env_file(ROOT / ".env")
        pairs = os.getenv("PAIRS", "BTC/USD,ETH/USD,BNB/USD,SOL/USD,XRP/USD")
        return cls(
            api_key=os.getenv("ROOSTOO_API_KEY", ""),
            api_secret=os.getenv("ROOSTOO_API_SECRET", ""),
            base_url=os.getenv("ROOSTOO_BASE_URL", "https://mock-api.roostoo.com"),
            pairs=tuple(p.strip().upper() for p in pairs.split(",") if p.strip()),
            poll_seconds=_int("POLL_SECONDS", 60),
            dry_run=_bool("DRY_RUN", False),
            paper_cash=_float("PAPER_CASH", 100_000),
            window=_int("WINDOW", 60),
            entry_z=_float("ENTRY_Z", 1.5),
            exit_z=_float("EXIT_Z", 0.0),
            min_edge_pct=_float("MIN_EDGE_PCT", 0.003),
            max_position_pct=_float("MAX_POSITION_PCT", 0.10),
            max_exposure_pct=_float("MAX_EXPOSURE_PCT", 0.50),
            stop_loss_pct=_float("STOP_LOSS_PCT", 0.03),
            max_hold_minutes=_int("MAX_HOLD_MINUTES", 360),
            min_seconds_between_buys=_int("MIN_SECONDS_BETWEEN_BUYS", 10),
            max_orders_per_day=_int("MAX_ORDERS_PER_DAY", 300),
            fee_rate=_float("FEE_RATE", 0.001),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            log_dir=ROOT / os.getenv("LOG_DIR", "logs"),
            data_dir=ROOT / os.getenv("DATA_DIR", "data"),
        )

    def validate(self) -> None:
        if not self.pairs:
            raise ValueError("PAIRS is empty")
        if not self.dry_run and not (self.api_key and self.api_secret):
            raise ValueError("ROOSTOO_API_KEY / ROOSTOO_API_SECRET missing (set them in .env)")
        if self.window < 5:
            raise ValueError("WINDOW must be >= 5")
