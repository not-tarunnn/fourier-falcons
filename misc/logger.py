"""Console/file logging plus CSV logs (trades + every API request)."""
from __future__ import annotations

import csv
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable


def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        log_dir / "bot.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


class CsvLogger:
    """Append-only CSV writer. Creates the file + header on first use."""

    def __init__(self, path: Path, fields: Iterable[str]):
        self.path = Path(path)
        self.fields = list(fields)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, **row) -> None:
        new_file = not self.path.exists() or self.path.stat().st_size == 0
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.fields, extrasaction="ignore", restval="")
            if new_file:
                writer.writeheader()
            writer.writerow(row)
