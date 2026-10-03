"""Small helpers shared across the bot."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN


def floor_to(value: float, decimals: int) -> float:
    """Round DOWN to `decimals` places (exchanges reject over-precise amounts)."""
    step = Decimal(1).scaleb(-decimals)
    return float(Decimal(str(value)).quantize(step, rounding=ROUND_DOWN))


def fmt_qty(value: float, decimals: int) -> str:
    """Plain decimal string (never scientific notation) for API payloads."""
    return f"{value:.{decimals}f}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
