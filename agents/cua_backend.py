"""Computer Use Agent backend — evidence enrichment for the Nemotron loop.

Optional sub-agent: when GRAFANA_URL and ANTHROPIC_API_KEY are present, the
real implementation would drive a browser via Anthropic's computer-use beta to
capture a Grafana panel screenshot. Without them, the tool degrades to a stub
that returns a synthetic, clearly-labeled response so the rest of the loop
keeps working in dev.

The seam for the real call is `_capture_real` — swap its body for an
Anthropic SDK call when ready.
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote


class CUAGrafanaBackend:
    def __init__(
        self,
        grafana_base_url: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
        screenshot_dir: Optional[str] = None,
    ):
        self.grafana_base_url = (grafana_base_url or os.getenv("GRAFANA_URL") or "").rstrip("/")
        self.anthropic_api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        self.screenshot_dir = Path(
            screenshot_dir or os.getenv("NEMOTRON_SCREENSHOT_DIR") or "/tmp/nemotron-screenshots"
        )

    def is_configured(self) -> bool:
        return bool(self.grafana_base_url and self.anthropic_api_key)

    def capture_panel(
        self,
        dashboard_uid: str,
        panel_id: int,
        what_to_look_for: str,
        from_minutes_ago: int = 30,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        from_ms = int(now.timestamp() * 1000) - from_minutes_ago * 60 * 1000
        to_ms = int(now.timestamp() * 1000)

        panel_url = (
            f"{self.grafana_base_url}/d/{dashboard_uid}"
            f"?viewPanel={panel_id}&from={from_ms}&to={to_ms}"
        ) if self.grafana_base_url else (
            f"<grafana_base_url unset>/d/{dashboard_uid}?viewPanel={panel_id}"
        )

        if not self.is_configured():
            return {
                "status": "stub",
                "mode": "stub",
                "configured": False,
                "panel_url": panel_url,
                "what_to_look_for": what_to_look_for,
                "time_range": {"from_ms": from_ms, "to_ms": to_ms},
                "note": (
                    "CUA not configured (GRAFANA_URL and/or ANTHROPIC_API_KEY missing). "
                    "Returning synthetic evidence reference only — no real screenshot was taken. "
                    "Cite the panel_url in your reasoning so a human can open it manually."
                ),
            }

        return self._capture_real(dashboard_uid, panel_id, panel_url, what_to_look_for, from_ms, to_ms)

    def _capture_real(
        self,
        dashboard_uid: str,
        panel_id: int,
        panel_url: str,
        what_to_look_for: str,
        from_ms: int,
        to_ms: int,
    ) -> Dict[str, Any]:
        # TODO: replace body with an Anthropic computer-use call that opens
        # `panel_url` in a headless browser, waits for the panel to render,
        # screenshots it, and returns a 1-sentence visual summary.
        # Until then this returns a deterministic placeholder that records
        # everything the real call would have used, so callers can trust the
        # shape of the response.
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_name = quote(f"{dashboard_uid}-{panel_id}-{ts}.png", safe="")
        screenshot_path = self.screenshot_dir / safe_name

        return {
            "status": "captured",
            "mode": "real-pending",
            "configured": True,
            "panel_url": panel_url,
            "screenshot_path": str(screenshot_path),
            "what_to_look_for": what_to_look_for,
            "time_range": {"from_ms": from_ms, "to_ms": to_ms},
            "note": (
                "Stub for real CUA path — wiring point is CUAGrafanaBackend._capture_real. "
                "When implemented, this will return a real PNG written to screenshot_path "
                "plus a visual_summary field describing what was on screen."
            ),
        }
