"""Turn a raw price list into the numbers the strategy needs."""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Features:
    price: float
    mean: float
    std: float
    zscore: float
    edge_pct: float  # how far the mean is above the price, as a fraction of price


def compute_features(prices: List[float], window: int) -> Optional[Features]:
    """Rolling mean / std / z-score over the last `window` samples.

    Returns None until enough history has been collected (warm-up).
    """
    if len(prices) < window:
        return None
    sample = prices[-window:]
    price = sample[-1]
    mean = statistics.fmean(sample)
    std = statistics.pstdev(sample)
    zscore = (price - mean) / std if std > 1e-12 else 0.0
    edge_pct = (mean - price) / price if price > 0 else 0.0
    return Features(price=price, mean=mean, std=std, zscore=zscore, edge_pct=edge_pct)
