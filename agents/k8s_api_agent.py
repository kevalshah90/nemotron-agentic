"""Kubernetes API backend for the cluster-introspection tools.

Read-only by design. The agent loop can list nodes/pods and describe nodes;
it cannot mutate the cluster from here. Any mutation must go through the
propose_action tool, which queues a proposal for human approval.
"""

from typing import Any, Dict, Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from .tools import ToolError


class K8sAPIAgent:
    def __init__(self):
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        self.core = client.CoreV1Api()

    def list_nodes(self) -> Dict[str, Any]:
        try:
            nodes = self.core.list_node()
        except ApiException as e:
            raise ToolError(f"list_node failed: {e.reason}")
        out = []
        for n in nodes.items:
            cap = n.status.capacity or {}
            alloc = n.status.allocatable or {}
            conditions = {c.type: c.status for c in (n.status.conditions or [])}
            out.append({
                "name": n.metadata.name,
                "gpus": int(cap.get("nvidia.com/gpu", "0")),
                "cpu_capacity": cap.get("cpu"),
                "cpu_allocatable": alloc.get("cpu"),
                "memory_capacity": cap.get("memory"),
                "ready": conditions.get("Ready") == "True",
                "labels": {k: v for k, v in (n.metadata.labels or {}).items()
                           if any(t in k for t in ["gpu", "zone", "role"])},
            })
        return {"total_nodes": len(out), "nodes": out}

    def list_pods(self, namespace: Optional[str] = None, label_selector: Optional[str] = None) -> Dict[str, Any]:
        try:
            if namespace:
                pods = self.core.list_namespaced_pod(namespace, label_selector=label_selector or "")
            else:
                pods = self.core.list_pod_for_all_namespaces(label_selector=label_selector or "")
        except ApiException as e:
            raise ToolError(f"list_pods failed: {e.reason}")
        out = []
        for p in pods.items:
            out.append({
                "namespace": p.metadata.namespace,
                "name": p.metadata.name,
                "node": p.spec.node_name,
                "phase": p.status.phase,
                "restarts": sum((cs.restart_count or 0) for cs in (p.status.container_statuses or [])),
            })
        return {"count": len(out), "pods": out}

    def describe_node(self, name: str) -> Dict[str, Any]:
        try:
            node = self.core.read_node(name)
            field = f"involvedObject.name={name},involvedObject.kind=Node"
            events = self.core.list_event_for_all_namespaces(field_selector=field, limit=20)
        except ApiException as e:
            raise ToolError(f"describe_node failed: {e.reason}")

        return {
            "name": name,
            "conditions": [
                {"type": c.type, "status": c.status, "reason": c.reason, "message": c.message}
                for c in (node.status.conditions or [])
            ],
            "events": [
                {"type": e.type, "reason": e.reason, "message": e.message,
                 "first_seen": e.first_timestamp, "count": e.count}
                for e in events.items
            ],
        }
