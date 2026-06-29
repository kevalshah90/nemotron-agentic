"""Mock backends for the demo path.

Simulates a small GPU cluster with one degraded node (gpu-3) running hot —
power draw and utilization are both anomalous, and there are recent
NodeNotReady events. Enough signal for the model to investigate, identify
the offender, and propose a remediation.

Used when main.py is run with --mock. Same surface as the real backends, so
the tool registry doesn't care which is plugged in.
"""

import math
import random
from typing import Any, Dict, List, Optional


_NODES = [
    {"name": "gpu-1", "gpus": 8, "power_baseline_w": 1800, "util_baseline_pct": 60, "ready": True},
    {"name": "gpu-2", "gpus": 8, "power_baseline_w": 1750, "util_baseline_pct": 55, "ready": True},
    {"name": "gpu-3", "gpus": 8, "power_baseline_w": 2950, "util_baseline_pct": 99, "ready": True},  # degraded
    {"name": "gpu-4", "gpus": 8, "power_baseline_w": 1820, "util_baseline_pct": 62, "ready": True},
]


def _series_for(promql: str, minutes: int, step_seconds: int) -> List[Dict[str, Any]]:
    rng = random.Random(hash(promql) & 0xFFFFFFFF)
    samples = max(1, (minutes * 60) // step_seconds)
    out = []
    for node in _NODES:
        if "POWER" in promql.upper():
            base = node["power_baseline_w"]
            noise = lambda: rng.gauss(0, 40)
        elif "UTIL" in promql.upper():
            base = node["util_baseline_pct"]
            noise = lambda: rng.gauss(0, 3)
        else:
            base = 1.0
            noise = lambda: rng.gauss(0, 0.05)
        vals = [[float(i * step_seconds), max(0.0, base + noise())] for i in range(samples)]
        out.append({"labels": {"instance": node["name"]}, "values": vals})
    return out


class MockMetricsAgent:
    def __init__(self, *_, **__):
        pass

    def query_instant(self, promql: str) -> Dict[str, Any]:
        samples = []
        for node in _NODES:
            if "POWER" in promql.upper():
                v = node["power_baseline_w"] + random.gauss(0, 40)
            elif "UTIL" in promql.upper():
                v = node["util_baseline_pct"] + random.gauss(0, 3)
            elif promql.lower().startswith("sum"):
                v = sum(n["power_baseline_w"] for n in _NODES)
            else:
                v = 1.0
            samples.append({"labels": {"instance": node["name"]}, "value": float(max(0.0, v))})
        return {"promql": promql, "samples": samples, "count": len(samples)}

    def query_range(self, promql: str, minutes: int = 30, step_seconds: int = 30) -> Dict[str, Any]:
        return {
            "promql": promql,
            "window_minutes": minutes,
            "step_seconds": step_seconds,
            "series": _series_for(promql, minutes, step_seconds),
        }


class MockK8sAPIAgent:
    def __init__(self, *_, **__):
        pass

    def list_nodes(self) -> Dict[str, Any]:
        return {
            "total_nodes": len(_NODES),
            "nodes": [{
                "name": n["name"],
                "gpus": n["gpus"],
                "cpu_capacity": "96",
                "cpu_allocatable": "92",
                "memory_capacity": "768Gi",
                "ready": n["ready"],
                "labels": {"node-role": "gpu-worker", "zone": "us-east-1a"},
            } for n in _NODES],
        }

    def list_pods(self, namespace: Optional[str] = None, label_selector: Optional[str] = None) -> Dict[str, Any]:
        pods = []
        for n in _NODES:
            pods.append({
                "namespace": "ml-training",
                "name": f"trainer-{n['name']}-0",
                "node": n["name"],
                "phase": "Running",
                "restarts": 7 if n["name"] == "gpu-3" else 0,
            })
        if namespace:
            pods = [p for p in pods if p["namespace"] == namespace]
        return {"count": len(pods), "pods": pods}

    def describe_node(self, name: str) -> Dict[str, Any]:
        if name == "gpu-3":
            return {
                "name": name,
                "conditions": [
                    {"type": "Ready", "status": "True", "reason": "KubeletReady", "message": "kubelet is posting ready status"},
                    {"type": "MemoryPressure", "status": "False", "reason": "KubeletHasSufficientMemory", "message": ""},
                    {"type": "DiskPressure", "status": "False", "reason": "KubeletHasNoDiskPressure", "message": ""},
                ],
                "events": [
                    {"type": "Warning", "reason": "NodeNotReady", "message": "Node went NotReady briefly at 14:12", "first_seen": "2026-06-28T14:12:00Z", "count": 3},
                    {"type": "Warning", "reason": "GPUThermalThrottle", "message": "DCGM reports thermal throttling on GPU 0,2,5", "first_seen": "2026-06-28T14:18:00Z", "count": 12},
                ],
            }
        return {
            "name": name,
            "conditions": [{"type": "Ready", "status": "True", "reason": "KubeletReady", "message": ""}],
            "events": [],
        }
