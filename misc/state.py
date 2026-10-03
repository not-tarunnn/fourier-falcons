"""Tiny JSON store so entry prices survive a restart."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict

log = logging.getLogger(__name__)


class StateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.positions: Dict[str, dict] = {}  # pair -> {"entry_price": float, "entry_ts": float}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            self.positions = json.loads(self.path.read_text()).get("positions", {})
        except (ValueError, OSError):
            log.warning("Could not read %s - starting with empty state", self.path)

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"positions": self.positions}, indent=2))
        os.replace(tmp, self.path)
