"""Telemetry recording for research runs."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .records import utc_now


@dataclass
class TelemetryRecorder:
    events: list[dict[str, Any]] = field(default_factory=list)

    def record_step(self, event: dict[str, Any]) -> None:
        payload = {"timestamp": utc_now(), **event}
        self.events.append(payload)

    def record_metric(self, name: str, value: Any, step: int | None = None) -> None:
        self.record_step(
            {
                "event_type": "metric",
                "step": step,
                "name": name,
                "value": value,
            }
        )

    def flush(self, path: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for event in self.events:
                handle.write(json.dumps(event, sort_keys=True))
                handle.write("\n")

    def summary(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        last_cycle: dict[str, Any] | None = None
        event_counts: Counter[str] = Counter()
        for event in self.events:
            event_type = str(event.get("event_type", "unknown"))
            event_counts[event_type] += 1
            if event.get("event_type") == "metric":
                metrics[event["name"]] = event["value"]
            elif event.get("event_type") == "cycle":
                last_cycle = event
        return {
            "event_count": len(self.events),
            "event_type_counts": dict(event_counts),
            "latest_metrics": metrics,
            "last_cycle": None
            if last_cycle is None
            else {
                "cycle": last_cycle.get("cycle"),
                "psi": last_cycle.get("psi"),
                "q": last_cycle.get("q"),
                "collapse_method": last_cycle.get("collapse_method"),
                "active_constraints": last_cycle.get("graph_size", {}).get("active_constraints"),
            },
        }
