import requests
from datetime import datetime
from typing import Dict, Any
import numpy as np

class MetricsAgent:
    def __init__(self, prometheus_url: str):
        self.prometheus_url = prometheus_url
    
    def query_power_consumption(self, timerange_hours: int = 1) -> Dict[str, Any]:
        query = 'sum(DCGM_FI_DEV_POWER_USAGE)'
        response = requests.get(
            f"{self.prometheus_url}/api/v1/query",
            params={'query': query, 'time': datetime.now().isoformat()}
        )
        data = response.json()
        if data['status'] == 'success' and data['data']['result']:
            current_power_watts = float(data['data']['result'][0]['value'][1])
            return {
                'current_power_watts': current_power_watts,
                'current_power_kw': current_power_watts / 1000,
                'timestamp': datetime.now().isoformat()
            }
        return {'error': 'No data available'}

    def query_gpu_utilization(self) -> Dict[str, Any]:
        query = 'DCGM_FI_DEV_GPU_UTIL'
        response = requests.get(f"{self.prometheus_url}/api/v1/query", params={'query': query})
        data = response.json()
        if data['status'] == 'success':
            utilizations = [float(r['value'][1]) for r in data['data']['result']]
            return {
                'average_utilization_pct': np.mean(utilizations),
                'num_gpus': len(utilizations),
                'gpu_details': [{'node': r['metric'].get('instance'), 'util': float(r['value'][1])} for r in data['data']['result']]
            }
        return {'error': 'No GPU data available'}