import numpy as np
from typing import List, Dict, Any

class AnomalyDetectorAgent:
    def detect_power_anomalies(self, timeseries_data: List[float], threshold_std: float = 2.0) -> Dict[str, Any]:
        if not timeseries_data: return {'error': 'No data'}
        mean = np.mean(timeseries_data)
        std = np.std(timeseries_data)
        anomalies = []

        for i, value in enumerate(timeseries_data):
            z_score = (value - mean) / std if std > 0 else 0
            if abs(z_score) > threshold_std:
                anomalies.append({'index': i, 'value': value, 'z_score': z_score})

        return {
                'num_anomalies': len(anomalies),
                'is_stable': len(anomalies) == 0,
                'mean': mean,
                'anomalies': anomalies
        }