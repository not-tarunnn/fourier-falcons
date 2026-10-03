"""Rolling price history per pair, persisted to CSV so restarts keep their warm-up."""
from __future__ import annotations

import csv
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict, List

from misc.logger import CsvLogger


class PriceBuffer:
    def __init__(self, maxlen: int, path: Path, max_age_seconds: float):
        self._data: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=maxlen))
        self._csv = CsvLogger(path, ["ts", "pair", "price"])
        self._load(Path(path), max_age_seconds)

    def _load(self, path: Path, max_age_seconds: float) -> None:
        """Reload recent ticks only - an old gap would distort the rolling stats."""
        if not path.exists():
            return
        cutoff = time.time() - max_age_seconds
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    if float(row["ts"]) >= cutoff:
                        self._data[row["pair"]].append(float(row["price"]))
                except (KeyError, ValueError):
                    continue

    def add(self, pair: str, price: float, ts: float) -> None:
        self._data[pair].append(price)
        self._csv.write(ts=round(ts, 3), pair=pair, price=price)

    def prices(self, pair: str) -> List[float]:
        return list(self._data[pair])
