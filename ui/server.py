"""FastAPI server for the Nemotron Cluster Advisor demo.

Architecture:
  GET  /                       → serve static index.html
  POST /run?mock=true          → kick off an investigation, return {run_id}
  GET  /run/{run_id}/stream    → SSE stream of agent trace events
  POST /run/{run_id}/action/{idx}/{decision}  → approve/reject a proposed action

The agent loop runs in a background thread (it's blocking I/O against the
NVIDIA hosted API). Its on_event callback bounces events into an asyncio.Queue
via loop.call_soon_threadsafe; the SSE endpoint drains the queue. The page
renders each event with vanilla JS — no build step, no framework.

Approvals are recorded in-process; this server intentionally does NOT execute
the approved actions against a real cluster. Wiring execution is a separate
concern (see README "Option D — real kubectl").

Env:
  NVIDIA_API_KEY        required
  NEMOTRON_BASE_URL     default: https://integrate.api.nvidia.com/v1
  NEMOTRON_MODEL        default: nvidia/nvidia-nemotron-nano-9b-v2
  PROMETHEUS_URL        default: http://localhost:9090 (only for mock=false)
  MAX_STEPS             default: 12
"""

import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import Thread
from typing import Dict, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from agents import (
    AnomalyDetectorAgent,
    K8sAPIAgent,
    MetricsAgent,
    MockK8sAPIAgent,
    MockMetricsAgent,
    ToolRegistry,
    build_registry,
)
from orchestrator import Nemotron
from orchestrator.nemotron import TraceEvent
from orchestrator.prompts import SYSTEM_PROMPT, USER_PROMPT

load_dotenv()

ROOT = Path(__file__).parent
app = FastAPI(title="Nemotron Cluster Advisor")


@dataclass
class Run:
    id: str
    queue: asyncio.Queue
    loop: asyncio.AbstractEventLoop
    registry: Optional[ToolRegistry] = None
    approvals: Dict[int, str] = field(default_factory=dict)   # idx -> pending|approved|rejected
    done: bool = False
    error: Optional[str] = None

    def emit(self, ev: TraceEvent):
        """Called from the worker thread. Bounce into the asyncio loop safely."""
        self.loop.call_soon_threadsafe(self.queue.put_nowait, ev)


RUNS: Dict[str, Run] = {}


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.post("/run")
async def start_run(mock: bool = True):
    run = Run(id=uuid.uuid4().hex[:8], queue=asyncio.Queue(), loop=asyncio.get_running_loop())
    RUNS[run.id] = run

    if mock:
        metrics, k8s = MockMetricsAgent(), MockK8sAPIAgent()
    else:
        metrics = MetricsAgent(prometheus_url=os.getenv("PROMETHEUS_URL", "http://localhost:9090"))
        k8s = K8sAPIAgent()

    registry = build_registry(metrics, k8s, AnomalyDetectorAgent())
    run.registry = registry

    brain = Nemotron(max_steps=int(os.getenv("MAX_STEPS", "12")))

    def worker():
        try:
            result = brain.run(SYSTEM_PROMPT, USER_PROMPT, registry, on_event=run.emit)
            run.done = True
            for i in range(len(registry.proposed_actions)):
                run.approvals.setdefault(i, "pending")
            run.emit(TraceEvent("final", {
                "report": result.report,
                "actions": registry.proposed_actions,
                "stop_reason": result.stop_reason,
                "steps": result.steps,
            }))
        except Exception as e:
            run.error = str(e)
            run.emit(TraceEvent("error", {"message": str(e)}))
            run.emit(TraceEvent("final", {"report": None, "actions": [], "error": str(e)}))

    Thread(target=worker, daemon=True).start()
    return {"run_id": run.id, "mock": mock}


@app.get("/run/{run_id}/stream")
async def stream(run_id: str):
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="unknown run")

    async def gen():
        while True:
            ev: TraceEvent = await run.queue.get()
            yield f"data: {json.dumps({'kind': ev.kind, 'payload': ev.payload}, default=str)}\n\n"
            if ev.kind == "final":
                break

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/run/{run_id}/action/{idx}/{decision}")
async def decide(run_id: str, idx: int, decision: str):
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="unknown run")
    if decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be approved|rejected")
    if not run.registry or idx >= len(run.registry.proposed_actions):
        raise HTTPException(status_code=404, detail="unknown action index")
    run.approvals[idx] = decision
    return {"ok": True, "idx": idx, "decision": decision, "action": run.registry.proposed_actions[idx]}


if __name__ == "__main__":
    uvicorn.run("ui.server:app", host="127.0.0.1", port=8001, reload=False)
