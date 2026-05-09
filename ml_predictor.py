from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd


class Predictor:
    def __init__(self, model_path: str = "models/model.joblib") -> None:
        self.model_path = Path(model_path)
        self.model = joblib.load(self.model_path) if self.model_path.exists() else None

    def predict_proba(self, features: pd.DataFrame) -> float:
        if self.model is None:
            return 0.5
        proba = self.model.predict_proba(features.tail(1))[0, 1]
        return float(np.clip(proba, 0.0, 1.0))
