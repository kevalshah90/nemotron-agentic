"""Prometheus backend for the metrics tools.

Exposes a small surface — instant and range queries — that the agent loop
composes via tool calls. The model writes its own PromQL.
"""

import time
from typing import Any, Dict

import requests

from .tools import ToolError


class MetricsAgent:
    def __init__(self, prometheus_url: str, timeout: float = 10.0):
        self.prometheus_url = prometheus_url.rstrip("/")
        self.timeout = timeout

    def query_instant(self, promql: str) -> Dict[str, Any]:
        try:
            r = requests.get(
                f"{self.prometheus_url}/api/v1/query",
                params={"query": promql},
                timeout=self.timeout,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            raise ToolError(f"prometheus instant query failed: {e}")

        data = r.json()
        if data.get("status") != "success":
            raise ToolError(f"prometheus error: {data.get('error', 'unknown')}")

        samples = [
            {"labels": item["metric"], "value": float(item["value"][1])}
            for item in data["data"]["result"]
        ]
        return {"promql": promql, "samples": samples, "count": len(samples)}

    def query_range(self, promql: str, minutes: int = 30, step_seconds: int = 30) -> Dict[str, Any]:
        end = time.time()
        start = end - minutes * 60
        try:
            r = requests.get(
                f"{self.prometheus_url}/api/v1/query_range",
                params={"query": promql, "start": start, "end": end, "step": step_seconds},
                timeout=self.timeout,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            raise ToolError(f"prometheus range query failed: {e}")

        data = r.json()
        if data.get("status") != "success":
            raise ToolError(f"prometheus error: {data.get('error', 'unknown')}")

        series = []
        for item in data["data"]["result"]:
            values = [[float(t), float(v)] for t, v in item["values"]]
            series.append({"labels": item["metric"], "values": values})
        return {
            "promql": promql,
            "window_minutes": minutes,
            "step_seconds": step_seconds,
            "series": series,
        }
