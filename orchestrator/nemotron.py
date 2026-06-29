"""Nemotron agent loop.

Talks to any OpenAI-compatible endpoint via the `openai` SDK. By default
points at NVIDIA's hosted API (https://integrate.api.nvidia.com/v1) and uses
the Nemotron Nano 9B v2 reasoning model, but base_url + model can be swapped
to point at a self-hosted NIM (or a larger Nemotron variant) with no code
changes.

Per iteration:
  1. Send (system, user, [assistant, tool]*) + tool schemas.
  2. The model returns reasoning_content (its private thinking), content
     (optional spoken reasoning), and/or tool_calls.
  3. We emit reasoning + tool calls as TraceEvents, dispatch each tool via
     the registry, append role='tool' messages with the results.
  4. Stop on: model returns no tool_calls, model calls the `finish` tool,
     or max_steps is exceeded.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from openai import OpenAI

from agents.tools import ToolRegistry


@dataclass
class TraceEvent:
    # "reasoning" | "model_text" | "tool_call" | "tool_result" | "stop" | "error"
    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LoopResult:
    final_text: str
    report: Optional[Dict[str, Any]]
    trace: List[TraceEvent]
    steps: int
    stop_reason: str


class Nemotron:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_steps: int = 12,
        temperature: float = 0.6,
        top_p: float = 0.95,
        max_tokens: int = 2048,
        min_thinking_tokens: int = 256,
        max_thinking_tokens: int = 1024,
        timeout: float = 120.0,
    ):
        base_url = base_url or os.getenv("NEMOTRON_BASE_URL", "https://integrate.api.nvidia.com/v1")
        api_key = api_key or os.getenv("NVIDIA_API_KEY")
        self.model = model or os.getenv("NEMOTRON_MODEL", "nvidia/nvidia-nemotron-nano-9b-v2")

        if not api_key:
            raise ValueError(
                "NVIDIA_API_KEY is required. Set it in .env or pass api_key=... explicitly."
            )

        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.max_steps = max_steps
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        # Forwarded via extra_body — these are Nemotron-specific reasoning controls.
        self.extra_body = {
            "min_thinking_tokens": min_thinking_tokens,
            "max_thinking_tokens": max_thinking_tokens,
        }

    def run(
        self,
        system_prompt: str,
        user_prompt: str,
        registry: ToolRegistry,
        on_event: Optional[Callable[[TraceEvent], None]] = None,
    ) -> LoopResult:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        tools = registry.schemas()
        trace: List[TraceEvent] = []

        def emit(ev: TraceEvent):
            trace.append(ev)
            if on_event:
                on_event(ev)

        for step in range(1, self.max_steps + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    # "required" forces the model to call SOME tool each turn.
                    # `finish` is a tool, so the loop can still terminate via it.
                    # Prevents the reasoning model from rambling and exiting
                    # with no_tool_calls before doing any work.
                    tool_choice="required",
                    temperature=self.temperature,
                    top_p=self.top_p,
                    max_tokens=self.max_tokens,
                    extra_body=self.extra_body,
                )
            except Exception as e:
                emit(TraceEvent("error", {"step": step, "message": f"{type(e).__name__}: {e}"}))
                return LoopResult(
                    final_text="", report=registry.final_report, trace=trace,
                    steps=step, stop_reason="error",
                )

            msg = resp.choices[0].message
            reasoning = getattr(msg, "reasoning_content", None)
            content = msg.content or ""
            tool_calls = msg.tool_calls or []

            if reasoning:
                emit(TraceEvent("reasoning", {"step": step, "text": reasoning}))
            if content:
                emit(TraceEvent("model_text", {"step": step, "text": content}))

            if not tool_calls:
                emit(TraceEvent("stop", {"reason": "no_tool_calls", "step": step}))
                return LoopResult(
                    final_text=content, report=registry.final_report, trace=trace,
                    steps=step, stop_reason="no_tool_calls",
                )

            # Persist the assistant turn (with tool_calls converted to dict form)
            # so the next request carries the tool_call_ids that the role='tool'
            # replies will reference.
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [{
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
                } for tc in tool_calls],
            })

            terminated = False
            for call in tool_calls:
                name = call.function.name
                args = call.function.arguments or "{}"
                emit(TraceEvent("tool_call", {"step": step, "name": name, "arguments": args}))

                result = registry.dispatch(name, args)
                emit(TraceEvent("tool_result", {"step": step, "name": name, "result": result}))

                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": name,
                    "content": result,
                })

                if registry.is_terminal(name):
                    terminated = True

            if terminated:
                emit(TraceEvent("stop", {"reason": "finish_called", "step": step}))
                return LoopResult(
                    final_text=content, report=registry.final_report, trace=trace,
                    steps=step, stop_reason="finish_called",
                )

        emit(TraceEvent("stop", {"reason": "max_steps", "step": self.max_steps}))
        return LoopResult(
            final_text="", report=registry.final_report, trace=trace,
            steps=self.max_steps, stop_reason="max_steps",
        )
