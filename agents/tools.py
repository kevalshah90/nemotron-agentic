"""Tool registry for the Nemotron agent loop.

Each tool is exposed to the model as an OpenAI-compatible function spec
(name, description, JSON-schema parameters). The model decides which to call;
ToolRegistry.dispatch routes the call to the backing Python implementation.

Two tools are special:
  - propose_action: records a remediation proposal. Never executes it.
                    Returns "PROPOSED — awaiting approval" so the model knows
                    the action is queued, not done.
  - finish: terminates the loop with a structured final report.
"""

import json
from typing import Any, Callable, Dict, List, Optional


class ToolError(Exception):
    """Raised when a tool call fails. The message is returned to the model
    as the tool result so it can recover (try a different query, etc.)."""


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Callable[..., Any]] = {}
        self._schemas: List[Dict[str, Any]] = []
        self.proposed_actions: List[Dict[str, Any]] = []
        self.final_report: Dict[str, Any] | None = None

    def register(self, schema: Dict[str, Any], fn: Callable[..., Any]):
        self._tools[schema["function"]["name"]] = fn
        self._schemas.append(schema)

    def schemas(self) -> List[Dict[str, Any]]:
        return self._schemas

    def dispatch(self, name: str, arguments: str) -> str:
        """Run the tool and return a string result for the model.
        Errors are caught and returned as text so the model can retry."""
        if name not in self._tools:
            return json.dumps({"error": f"unknown tool: {name}"})
        try:
            args = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"invalid JSON arguments: {e}"})
        try:
            result = self._tools[name](**args)
        except ToolError as e:
            return json.dumps({"error": str(e)})
        except TypeError as e:
            return json.dumps({"error": f"bad arguments for {name}: {e}"})
        return json.dumps(result, default=str)

    def is_terminal(self, name: str) -> bool:
        return name == "finish"


def build_registry(metrics, k8s, anomaly, cua=None) -> ToolRegistry:
    """Wire the backend agents into a tool registry the model can call.

    `cua` is the optional Computer Use Agent backend used for evidence
    enrichment (Grafana panel screenshots). If omitted, a stub-mode
    CUAGrafanaBackend is constructed; it returns synthetic responses unless
    GRAFANA_URL and ANTHROPIC_API_KEY are present in the environment."""
    from .cua_backend import CUAGrafanaBackend

    if cua is None:
        cua = CUAGrafanaBackend()

    reg = ToolRegistry()

    reg.register(
        {
            "type": "function",
            "function": {
                "name": "query_prometheus_instant",
                "description": (
                    "Run a PromQL instant query against Prometheus. "
                    "Use this for current values of a metric across the cluster. "
                    "Returns a list of {labels, value} samples."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "promql": {
                            "type": "string",
                            "description": "PromQL expression, e.g. 'DCGM_FI_DEV_GPU_UTIL' or 'sum(DCGM_FI_DEV_POWER_USAGE) by (instance)'",
                        }
                    },
                    "required": ["promql"],
                },
            },
        },
        lambda promql: metrics.query_instant(promql),
    )

    reg.register(
        {
            "type": "function",
            "function": {
                "name": "query_prometheus_range",
                "description": (
                    "Run a PromQL range query over the last N minutes. "
                    "Use this to fetch a timeseries for trend or anomaly analysis."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "promql": {"type": "string"},
                        "minutes": {
                            "type": "integer",
                            "description": "How many minutes back from now to query. Default 30.",
                            "default": 30,
                        },
                        "step_seconds": {
                            "type": "integer",
                            "description": "Sample interval in seconds. Default 30.",
                            "default": 30,
                        },
                    },
                    "required": ["promql"],
                },
            },
        },
        lambda promql, minutes=30, step_seconds=30: metrics.query_range(promql, minutes, step_seconds),
    )

    reg.register(
        {
            "type": "function",
            "function": {
                "name": "list_nodes",
                "description": "List cluster nodes with capacity, allocatable resources, and GPU count.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        lambda: k8s.list_nodes(),
    )

    reg.register(
        {
            "type": "function",
            "function": {
                "name": "list_pods",
                "description": "List pods, optionally filtered by namespace and label selector.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string", "description": "Namespace, or omit for all namespaces."},
                        "label_selector": {"type": "string", "description": "e.g. 'app=trainer'"},
                    },
                },
            },
        },
        lambda namespace=None, label_selector=None: k8s.list_pods(namespace, label_selector),
    )

    reg.register(
        {
            "type": "function",
            "function": {
                "name": "describe_node",
                "description": "Detailed view of one node: conditions, allocated pods, recent events.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
        lambda name: k8s.describe_node(name),
    )

    reg.register(
        {
            "type": "function",
            "function": {
                "name": "detect_anomalies",
                "description": (
                    "Run z-score anomaly detection over a numeric series. "
                    "Returns the indices/values whose |z| exceeds threshold_std."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "values": {"type": "array", "items": {"type": "number"}},
                        "threshold_std": {"type": "number", "default": 2.0},
                    },
                    "required": ["values"],
                },
            },
        },
        lambda values, threshold_std=2.0: anomaly.detect(values, threshold_std),
    )

    reg.register(
        {
            "type": "function",
            "function": {
                "name": "capture_grafana_panel",
                "description": (
                    "Evidence enrichment: capture a Grafana panel as visual evidence for a finding "
                    "(driven by an Anthropic Computer Use sub-agent). Use this AFTER you've already "
                    "located a suspect node/pod via PromQL, when a screenshot would meaningfully "
                    "strengthen a propose_action — e.g. a thermal-throttle pattern, a NCCL stall, "
                    "a clear regime change in a timeseries. Returns a panel_url and, when CUA is "
                    "configured, a screenshot_path. If unconfigured, returns a stub response with "
                    "the panel_url so a human can open it manually — the loop is unaffected."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dashboard_uid": {
                            "type": "string",
                            "description": "Grafana dashboard UID (the slug after /d/ in the URL).",
                        },
                        "panel_id": {
                            "type": "integer",
                            "description": "Numeric panel ID within the dashboard.",
                        },
                        "what_to_look_for": {
                            "type": "string",
                            "description": "One sentence describing the visual pattern you expect, e.g. 'clock-bouncing on gpu-3 after 14:20 UTC'.",
                        },
                        "from_minutes_ago": {
                            "type": "integer",
                            "description": "Time window start, minutes before now. Default 30.",
                            "default": 30,
                        },
                    },
                    "required": ["dashboard_uid", "panel_id", "what_to_look_for"],
                },
            },
        },
        lambda dashboard_uid, panel_id, what_to_look_for, from_minutes_ago=30: cua.capture_panel(
            dashboard_uid, panel_id, what_to_look_for, from_minutes_ago
        ),
    )

    def _propose(
        action_type: str,
        target: str,
        reason: str,
        dry_run: bool = True,
        params: Optional[Dict[str, Any]] = None,
    ):
        action = {
            "action_type": action_type,
            "target": target,
            "reason": reason,
            "dry_run": dry_run,
            "params": params or {},
        }
        reg.proposed_actions.append(action)
        return {
            "status": "PROPOSED — awaiting human approval",
            "action": action,
            "queued_total": len(reg.proposed_actions),
        }

    reg.register(
        {
            "type": "function",
            "function": {
                "name": "propose_action",
                "description": (
                    "Propose a remediation action. The action is QUEUED for human approval; "
                    "this tool never executes it directly. Call once per action; you may call multiple times."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action_type": {
                            "type": "string",
                            "enum": [
                                "cordon_node",
                                "drain_node",
                                "delete_pod",
                                "scale_deployment",
                                "adjust_clock_frequencies",
                                "power_cap",
                                "alert_oncall",
                                "no_action",
                            ],
                            "description": (
                                "cordon_node: mark unschedulable. "
                                "drain_node: cordon + evict pods. "
                                "delete_pod: kill one pod. "
                                "scale_deployment: change replica count. "
                                "adjust_clock_frequencies: lock SM/memory clocks via `nvidia-smi -ac <mem,sm>` "
                                "(use when GPUs are thermally throttling or to stabilize jitter); "
                                "requires params.sm_clock_mhz and params.mem_clock_mhz, or params.reset=true. "
                                "power_cap: set per-GPU power limit via `nvidia-smi -pl <watts>` "
                                "(use when rack PDU is near limit or sustained over-temp); "
                                "requires params.watts, or params.reset=true to restore default. "
                                "alert_oncall: page a human. "
                                "no_action: cluster is healthy."
                            ),
                        },
                        "target": {
                            "type": "string",
                            "description": (
                                "Resource identifier. For clock/power actions, scope to node or GPU index, "
                                "e.g. 'node/gpu-3' for all GPUs on the node, or 'node/gpu-3/gpu/0' for one device."
                            ),
                        },
                        "reason": {"type": "string", "description": "Why this action, citing the metrics you observed."},
                        "dry_run": {"type": "boolean", "default": True},
                        "params": {
                            "type": "object",
                            "description": (
                                "Action-specific parameters. "
                                "adjust_clock_frequencies: {sm_clock_mhz: int, mem_clock_mhz: int} or {reset: true}. "
                                "power_cap: {watts: int} or {reset: true}. "
                                "scale_deployment: {replicas: int}. "
                                "Other actions: omit."
                            ),
                            "properties": {
                                "sm_clock_mhz": {"type": "integer", "description": "Target SM (graphics) clock in MHz."},
                                "mem_clock_mhz": {"type": "integer", "description": "Target memory clock in MHz."},
                                "watts": {"type": "integer", "description": "Per-GPU power limit in watts."},
                                "replicas": {"type": "integer", "description": "Target replica count for scale_deployment."},
                                "reset": {"type": "boolean", "description": "Reset the knob to vendor default."},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "required": ["action_type", "target", "reason"],
                },
            },
        },
        _propose,
    )

    def _finish(assessment: str, risk_level: str, confidence: float = 0.7):
        reg.final_report = {
            "assessment": assessment,
            "risk_level": risk_level,
            "confidence": confidence,
            "proposed_actions": list(reg.proposed_actions),
        }
        return {"status": "loop terminated", "report": reg.final_report}

    reg.register(
        {
            "type": "function",
            "function": {
                "name": "finish",
                "description": (
                    "End the investigation. Call this once you have gathered enough evidence and "
                    "proposed all needed actions. Provide a brief assessment and overall risk level."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "assessment": {"type": "string"},
                        "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["assessment", "risk_level"],
                },
            },
        },
        _finish,
    )

    return reg
