"""Read-only helpers that turn a run's trace events into metrics and tables (used by the CLI and the Streamlit UI).

Nothing here changes how the agent runs. Events are the dicts produced by `Tracer.event`; traces saved before the
optional `ts` field existed still load, because every field except step/kind/node/summary is read with a default.
"""
from __future__ import annotations

import json
from pathlib import Path

# kind -> (text label shown next to the colour, background colour); kinds not listed are shown plainly
HIGHLIGHT = {"loop": ("LOOP", "#FFE0B2"), "guardrail": ("GUARDRAIL", "#FFCDD2")}
KINDS = ("plan", "retrieval", "tool", "loop", "guardrail", "decision")


def load_events(path) -> list[dict]:
    """Load a trace saved as JSONL (one event per line); blank lines are ignored."""
    lines = Path(path).read_text(encoding="utf8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def events_to_jsonl(events) -> str:
    """Serialise events exactly like `Tracer.save` does, so the UI download equals the saved trace file."""
    return "".join(json.dumps(e, default=str) + "\n" for e in events)


def flag_for(event: dict) -> str:
    """Text label for events that deserve attention (LOOP / GUARDRAIL), else an empty string."""
    return HIGHLIGHT.get(event["kind"], ("", ""))[0]


def attempts_of(event: dict) -> list[dict]:
    """Rows describing every retrieval attempt of a retrieval event: query, grade and whether it was a rewrite."""
    out = []
    for i, a in enumerate(event.get("data", {}).get("attempts", []), 1):
        out.append({"attempt": i, "kind": "first query" if i == 1 else "rewrite", "query": a.get("query", ""),
                    "grade": "passed: " + ", ".join(a["passed"]) if a.get("passed") else "weak (no clause passed)",
                    "top_hits": ", ".join(f"{c} ({s})" for c, s in a.get("hits", [])) or "none"})
    return out


def run_metrics(events) -> dict:
    """Per-run numbers: steps, tool calls (tool + retrieval events), retrieval rewrites, verify loops, seconds,
    plan, final decision and the review-reason codes recorded on the decision event."""
    rewrites = sum(max(0, len(e.get("data", {}).get("attempts", [])) - 1) for e in events if e["kind"] == "retrieval")
    decision = next((e for e in reversed(events) if e["kind"] == "decision"), None)
    plan = next((e for e in events if e["kind"] == "plan"), None)
    return {"steps": len(events),
            "tool_calls": sum(1 for e in events if e["kind"] in ("tool", "retrieval")),
            "retrieval_rewrites": rewrites,
            "verify_loops": sum(1 for e in events if e["kind"] == "loop"),
            "guardrail_events": sum(1 for e in events if e["kind"] == "guardrail"),
            "seconds": round(max((e.get("t_ms", 0) for e in events), default=0) / 1000, 3),
            "plan": plan["summary"].removeprefix("plan: ") if plan else "n/a",
            "decision": decision["summary"].split(";")[0] if decision else "n/a",
            "review_reasons": (list(decision.get("data", {}).get("reasons", []))
                               + [c + " (INFO)" for c in decision.get("data", {}).get("info_reasons", [])]) if decision else []}


def node_table(events) -> list[dict]:
    """One row per node, in order of first appearance: events, loops, rewrites and milliseconds.
    Time of an event = time since the previous event, credited to the node that produced it."""
    rows, prev = {}, 0.0
    for e in events:
        r = rows.setdefault(e["node"], {"node": e["node"], "events": 0, "loops": 0, "rewrites": 0, "ms": 0.0})
        r["events"] += 1
        r["loops"] += e["kind"] == "loop"
        if e["kind"] == "retrieval":
            r["rewrites"] += max(0, len(e.get("data", {}).get("attempts", [])) - 1)
        t = e.get("t_ms", prev)
        r["ms"] += max(0.0, t - prev)
        prev = t
    return [{**r, "ms": round(r["ms"], 1)} for r in rows.values()]


def to_markdown(rows, columns) -> str:
    """Render a list of dicts as a GitHub-style markdown table with the given columns."""
    L = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    L += ["| " + " | ".join(str(r[c]).replace("|", "/") for c in columns) + " |" for r in rows]
    return "\n".join(L)
