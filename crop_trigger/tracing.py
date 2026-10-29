"""Run tracing: every step of every run is captured as an ordered list of events and saved as JSONL.

Event kinds: node, tool, retrieval, plan, loop, guardrail, decision.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path


def _default(o):
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


class Tracer:
    def __init__(self, run_id: str | None = None, out_dir: str | Path | None = None):
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.out_dir = Path(out_dir) if out_dir else None
        self.events: list[dict] = []
        self._t0 = time.perf_counter()

    def event(self, kind: str, node: str, summary: str, **data) -> dict:
        ev = {"step": len(self.events) + 1, "t_ms": round((time.perf_counter() - self._t0) * 1000, 1),
              "kind": kind, "node": node, "summary": summary,
              "ts": round(time.time(), 3)}   # wall-clock epoch seconds; optional, traces saved before it existed lack it
        if data:
            ev["data"] = json.loads(json.dumps(data, default=_default))
        self.events.append(ev)
        return ev

    def count(self, kind: str) -> int:
        return sum(1 for e in self.events if e["kind"] == kind)

    def save(self) -> Path | None:
        if not self.out_dir:
            return None
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{self.run_id}.jsonl"
        with open(path, "w") as f:
            for ev in self.events:
                f.write(json.dumps(ev, default=_default) + "\n")
        return path

    def markdown(self) -> str:
        lines = [f"# Trace {self.run_id}", "", "| # | ms | kind | node | summary |", "|---|---|---|---|---|"]
        for e in self.events:
            lines.append(f"| {e['step']} | {e['t_ms']} | {e['kind']} | {e['node']} | {e['summary'].replace('|', '/')} |")
        return "\n".join(lines)
