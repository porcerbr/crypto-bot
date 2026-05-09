from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import TimeSeriesSplit

from ml_features import build_features, create_labels


def train(csv_path: str, model_path: str = "models/model.joblib") -> dict:
    df = pd.read_csv(csv_path, parse_dates=["time"])
    x = build_features(df)
    y = create_labels(df).reindex(x.index).dropna()
    x = x.loc[y.index]

    tscv = TimeSeriesSplit(n_splits=5)
    scores = []
    model = RandomForestClassifier(n_estimators=300, max_depth=8, random_state=42, n_jobs=-1)

    for train_idx, test_idx in tscv.split(x):
        model.fit(x.iloc[train_idx], y.iloc[train_idx])
        score = model.score(x.iloc[test_idx], y.iloc[test_idx])
        scores.append(score)

    model.fit(x, y)
    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)

    preds = model.predict(x)
    report = classification_report(y, preds, output_dict=True, zero_division=0)
    return {"cv_mean_accuracy": sum(scores) / len(scores), "report": report}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--model-path", default="models/model.joblib")
    args = parser.parse_args()
    result = train(args.csv, args.model_path)
    print(result)
