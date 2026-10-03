"""Paper-trading client for DRY_RUN mode.

Uses REAL market data from Roostoo but keeps a local virtual wallet and simulates
market-order fills (buy at ask, sell at bid, 0.1% taker fee). No orders are sent.
"""
from __future__ import annotations

import copy
import time
from typing import Any, Dict, Optional

from app.roostoo_client import RoostooClient


class PaperClient(RoostooClient):
    def __init__(self, *args, cash: float = 100_000, fee_rate: float = 0.001, **kwargs):
        super().__init__(*args, **kwargs)
        self.fee_rate = fee_rate
        self._wallet: Dict[str, Dict[str, float]] = {"USD": {"Free": float(cash), "Lock": 0.0}}
        self._order_id = 0

    def balance(self) -> Dict[str, Dict[str, float]]:
        return copy.deepcopy(self._wallet)

    def place_order(self, pair: str, side: str, quantity: str, order_type: str = "MARKET",
                    price: Optional[float] = None) -> Dict[str, Any]:
        quote = self.ticker(pair)[pair]
        qty = float(quantity)
        coin = pair.split("/")[0]
        usd = self._wallet["USD"]
        holding = self._wallet.setdefault(coin, {"Free": 0.0, "Lock": 0.0})

        if side.upper() == "BUY":
            px = float(quote["MinAsk"])
            cost = qty * px
            fee = cost * self.fee_rate
            if cost + fee > usd["Free"]:
                return {"Success": False, "ErrMsg": "insufficient balance"}
            usd["Free"] -= cost + fee
            holding["Free"] += qty
        else:
            px = float(quote["MaxBid"])
            proceeds = qty * px
            fee = proceeds * self.fee_rate
            if qty > holding["Free"] + 1e-12:
                return {"Success": False, "ErrMsg": "insufficient balance"}
            holding["Free"] = max(0.0, holding["Free"] - qty)
            usd["Free"] += proceeds - fee

        self._order_id += 1
        return {
            "Success": True,
            "ErrMsg": "",
            "OrderDetail": {
                "Pair": pair, "OrderID": f"paper-{self._order_id}", "Status": "FILLED",
                "Role": "TAKER", "Side": side.upper(), "Type": "MARKET",
                "Quantity": qty, "FilledQuantity": qty, "FilledAverPrice": px,
                "CommissionChargeValue": fee, "CreateTimestamp": int(time.time() * 1000),
            },
        }
