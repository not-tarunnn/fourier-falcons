#!/usr/bin/env python3
"""Entry point: wires every module together and runs the bot.

    python main.py             # live trading on Roostoo (needs API keys in .env)
    python main.py --dry-run   # paper trading with real prices, no orders sent
    python main.py --once      # run a single cycle and exit (smoke test)
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
import signal
import sys
import threading

from app.bot import TradingBot
from app.paper_client import PaperClient
from app.roostoo_client import RoostooClient
from data_preprocessing.price_buffer import PriceBuffer
from misc.config import Config
from misc.logger import setup_logging
from misc.state import StateStore
from risk_management.risk_manager import RiskManager
from strategy.mean_reversion import MeanReversionStrategy


def main() -> int:
    parser = argparse.ArgumentParser(description="Roostoo mean-reversion trading bot")
    parser.add_argument("--dry-run", action="store_true", help="paper trade, send no orders")
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    args = parser.parse_args()

    cfg = Config.from_env()
    if args.dry_run:
        cfg = dataclasses.replace(cfg, dry_run=True)
    cfg.validate()

    setup_logging(cfg.log_dir, cfg.log_level)
    log = logging.getLogger("main")

    client_args = dict(api_key=cfg.api_key, api_secret=cfg.api_secret,
                       base_url=cfg.base_url, log_dir=cfg.log_dir)
    if cfg.dry_run:
        client = PaperClient(**client_args, cash=cfg.paper_cash, fee_rate=cfg.fee_rate)
    else:
        client = RoostooClient(**client_args)

    buffer = PriceBuffer(
        maxlen=cfg.window,
        path=cfg.data_dir / "price_history.csv",
        max_age_seconds=cfg.window * cfg.poll_seconds * 3,
    )
    bot = TradingBot(
        cfg=cfg,
        client=client,
        buffer=buffer,
        strategy=MeanReversionStrategy(cfg.entry_z, cfg.exit_z, cfg.min_edge_pct),
        risk=RiskManager(cfg),
        state=StateStore(cfg.data_dir / "state.json"),
    )

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    bot.setup()
    if args.once:
        bot.run_cycle()
        return 0

    log.info("Bot started (poll every %ss, window=%d samples)", cfg.poll_seconds, cfg.window)
    bot.run_forever(stop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
