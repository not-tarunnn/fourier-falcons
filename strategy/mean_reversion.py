"""Mean-reversion strategy (long-only spot).

Idea: prices that stretch far below their recent average tend to snap back.
  BUY  when the z-score drops to -entry_z (oversold) AND the move back to the mean
       is big enough to pay for fees.
  SELL when the z-score recovers to exit_z (price is back near its average).
Stop-loss / max-hold exits are handled by the risk manager, not here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from data_preprocessing.features import Features


@dataclass(frozen=True)
class Signal:
    pair: str
    action: str  # "BUY" | "SELL" | "HOLD"
    reason: str


class MeanReversionStrategy:
    def __init__(self, entry_z: float, exit_z: float, min_edge_pct: float):
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.min_edge_pct = min_edge_pct

    def generate(self, pair: str, feats: Optional[Features], in_position: bool) -> Signal:
        if feats is None:
            return Signal(pair, "HOLD", "warming up")

        if in_position:
            if feats.zscore >= self.exit_z:
                return Signal(pair, "SELL", f"reverted to mean (z={feats.zscore:.2f})")
            return Signal(pair, "HOLD", f"waiting for reversion (z={feats.zscore:.2f})")

        if feats.zscore <= -self.entry_z and feats.edge_pct >= self.min_edge_pct:
            return Signal(
                pair, "BUY", f"oversold (z={feats.zscore:.2f}, edge={feats.edge_pct:.2%})"
            )
        return Signal(pair, "HOLD", f"no setup (z={feats.zscore:.2f})")
