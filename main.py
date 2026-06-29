"""K8s Nemotron Advisor — agentic CLI entry point.

Wires the tool registry, kicks off the Nemotron loop, streams a readable
trace to the terminal, and asks the operator to approve any actions the
model proposed before they would be applied.

Run modes:
  python main.py --mock                                 # self-contained demo
  python main.py --prometheus-url http://... [...]      # against a real cluster

The model endpoint is controlled by env vars:
  NVIDIA_API_KEY        required
  NEMOTRON_BASE_URL     default: https://integrate.api.nvidia.com/v1
  NEMOTRON_MODEL        default: nvidia/nvidia-nemotron-nano-9b-v2
"""

import argparse
import json
import sys

from dotenv import load_dotenv

from agents import (
    AnomalyDetectorAgent,
    K8sAPIAgent,
    MetricsAgent,
    MockK8sAPIAgent,
    MockMetricsAgent,
    build_registry,
)
from orchestrator import Nemotron
from orchestrator.nemotron import TraceEvent
from orchestrator.prompts import SYSTEM_PROMPT, USER_PROMPT

load_dotenv()


# --- terminal pretty-printer for trace events -----------------------------------

GREY = "\033[90m"; CYAN = "\033[36m"; YEL = "\033[33m"; GRN = "\033[32m"
RED = "\033[31m"; DIM = "\033[2m"; ITAL = "\033[3m"; RST = "\033[0m"


def _truncate(s: str, n: int = 400) -> str:
    return s if len(s) <= n else s[:n] + f" … [+{len(s) - n} chars]"


def print_event(ev: TraceEvent):
    if ev.kind == "reasoning":
        print(f"{DIM}{ITAL}[step {ev.payload['step']}] ▸ thinking: {_truncate(ev.payload['text'], 280)}{RST}")
    elif ev.kind == "model_text":
        print(f"{GREY}[step {ev.payload['step']}] model:{RST} {ev.payload['text']}")
    elif ev.kind == "tool_call":
        args_pretty = ev.payload["arguments"]
        try:
            args_pretty = json.dumps(json.loads(args_pretty), separators=(",", "="))
        except Exception:
            pass
        print(f"{CYAN}[step {ev.payload['step']}] → call {ev.payload['name']}({_truncate(args_pretty, 200)}){RST}")
    elif ev.kind == "tool_result":
        print(f"{GREY}            ← {_truncate(ev.payload['result'])}{RST}")
    elif ev.kind == "stop":
        print(f"{YEL}[stop] reason={ev.payload['reason']} step={ev.payload['step']}{RST}")
    elif ev.kind == "error":
        print(f"{RED}[error] {ev.payload.get('message', '')}{RST}")


# --- entry point ----------------------------------------------------------------

def build_backends(args):
    if args.mock:
        return MockMetricsAgent(), MockK8sAPIAgent(), AnomalyDetectorAgent()
    return MetricsAgent(prometheus_url=args.prometheus_url), K8sAPIAgent(), AnomalyDetectorAgent()


def approve_actions(actions, auto_approve: bool) -> list:
    approved = []
    if not actions:
        print(f"\n{GRN}No actions proposed.{RST}")
        return approved
    print(f"\n{YEL}{len(actions)} action(s) proposed by Nemotron:{RST}")
    for i, a in enumerate(actions, 1):
        print(f"\n  [{i}] {a['action_type']}  →  {a['target']}")
        print(f"      reason: {a['reason']}")
        print(f"      dry_run: {a['dry_run']}")
        if auto_approve:
            print(f"      {GRN}auto-approved{RST}")
            approved.append(a)
            continue
        choice = input(f"      Approve? [y/N] ").strip().lower()
        if choice == "y":
            approved.append(a)
            print(f"      {GRN}approved (not executed — execution layer is intentionally not wired){RST}")
        else:
            print(f"      {RED}skipped{RST}")
    return approved


def main():
    parser = argparse.ArgumentParser(description="K8s Nemotron Advisor (agentic)")
    parser.add_argument("--prometheus-url", help="Prometheus endpoint (real cluster)")
    parser.add_argument("--mock", action="store_true", help="Use mock cluster — no Prometheus/K8s required")
    parser.add_argument("--auto-approve", action="store_true", help="Approve all proposed actions without prompting")
    parser.add_argument("--max-steps", type=int, default=12)
    args = parser.parse_args()

    if not args.mock and not args.prometheus_url:
        parser.error("--prometheus-url is required unless --mock is set")

    metrics, k8s, anomaly = build_backends(args)
    registry = build_registry(metrics, k8s, anomaly)
    brain = Nemotron(max_steps=args.max_steps)

    print(f"{CYAN}=== Nemotron agent loop starting ==={RST}")
    print(f"model={brain.model}  mock={args.mock}  max_steps={args.max_steps}  tools={len(registry.schemas())}\n")

    result = brain.run(SYSTEM_PROMPT, USER_PROMPT, registry, on_event=print_event)

    print(f"\n{CYAN}=== loop finished in {result.steps} steps ({result.stop_reason}) ==={RST}")
    if result.report:
        print(f"\nAssessment: {result.report['assessment']}")
        print(f"Risk level: {result.report['risk_level']}")
        print(f"Confidence: {result.report['confidence']}")

    approved = approve_actions(registry.proposed_actions, args.auto_approve)
    print(f"\n{GRN}{len(approved)} of {len(registry.proposed_actions)} action(s) approved.{RST}")

    return 0 if result.stop_reason != "max_steps" else 1


if __name__ == "__main__":
    sys.exit(main())
