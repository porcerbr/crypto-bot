from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Iterable

import pandas as pd

from core_models import Signal


class SignalStorage:
    def __init__(self, path: str = "data/signals.csv") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def append(self, signal: Signal) -> None:
        row = pd.DataFrame([asdict(signal)])
        with self._lock:
            if self.path.exists():
                existing = pd.read_csv(self.path)
                combined = pd.concat([existing, row], ignore_index=True)
            else:
                combined = row
            combined.to_csv(self.path, index=False)

    def load(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame()
        return pd.read_csv(self.path)

    def extend(self, signals: Iterable[Signal]) -> None:
        for signal in signals:
            self.append(signal)
