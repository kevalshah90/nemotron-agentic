"""Statistical anomaly detection, exposed as a tool the agent can call
on any numeric series it has fetched."""

from typing import Any, Dict, List

import numpy as np


class AnomalyDetectorAgent:
    def detect(self, values: List[float], threshold_std: float = 2.0) -> Dict[str, Any]:
        if not values:
            return {"error": "empty series"}
        arr = np.asarray(values, dtype=float)
        mean = float(arr.mean())
        std = float(arr.std())
        if std == 0:
            return {"num_anomalies": 0, "is_stable": True, "mean": mean, "std": 0.0, "anomalies": []}

        z = (arr - mean) / std
        idx = np.where(np.abs(z) > threshold_std)[0]
        anomalies = [
            {"index": int(i), "value": float(arr[i]), "z_score": float(z[i])}
            for i in idx
        ]
        return {
            "num_anomalies": len(anomalies),
            "is_stable": len(anomalies) == 0,
            "mean": mean,
            "std": std,
            "anomalies": anomalies,
        }
