"""Command line: run the agent on one case and print the report and the trace.

  python -m crop_trigger.cli --case M01
  python -m crop_trigger.cli --primary a.csv --secondary b.csv [--policy data/policy_sample.txt]
  options: --engine native|langgraph   --trace   --save   --fault transient|persistent
  python -m crop_trigger.cli --trace-summary M01          (or a saved traces/<run>.jsonl): per-node table
  python -m crop_trigger.cli --compare C01 M01 F01 X01    one row per case: plan, steps, tool calls, rewrites, loops, decision
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import agent, observability, records
from .engine import FaultyCalculator
from .llm import get_llm
from .tracing import Tracer

ROOT = Path(__file__).resolve().parent.parent


def _rewrite_detail(events) -> str:
    """Display only: for each retrieval that needed a rewritten query, list every attempt and what it matched."""
    lines = []
    for e in events:
        attempts = e.get("data", {}).get("attempts", []) if e["kind"] == "retrieval" else []
        if len(attempts) < 2:
            continue
        lines.append(f"- need '{e['data']['need']}':")
        for i, a in enumerate(attempts, 1):
            top = ", ".join(f"{cid} ({score})" for cid, score in a["hits"]) or "no hits"
            outcome = f"matched clause {', '.join(a['passed'])}" if a["passed"] else "weak, no clause passed the grade"
            lines.append(f"  - attempt {i}: {outcome}; query '{a['query']}'; top hits {top}")
    if not lines:
        return ""
    return "## Retrieval rewrites (attempt detail)\n\n" + "\n".join(lines) + "\n"


def _run_case(case_id: str, engine: str = "native"):
    """Run one labelled case from data/cases.json (with its injected fault, if any) and return the final state."""
    case = next((c for c in json.loads((ROOT / "data/cases.json").read_text())["cases"] if c["id"] == case_id), None)
    if not case:
        raise SystemExit(f"unknown case {case_id}")
    kw = {"tracer": Tracer(), "llm": get_llm()}
    if case.get("fault"):
        kw["calculator"] = FaultyCalculator(case["fault"]["mode"], "P1")
    run = agent.run if engine == "native" else agent.run_langgraph
    return run(ROOT / "data/policy_sample.txt", ROOT / case["primary"], ROOT / case["secondary"], **kw)


def trace_summary(target: str, engine: str = "native") -> str:
    """Compact report for one run: headline metrics plus a per-node table. `target` is a saved .jsonl trace or a case id."""
    path = Path(target)
    if path.suffix == ".jsonl" or path.exists():
        events, label = observability.load_events(path), str(path)
    else:
        events, label = _run_case(target, engine)["tracer"].events, f"case {target}"
    m = observability.run_metrics(events)
    head = (f"Trace summary: {label}\n"
            f"decision {m['decision']}; plan {m['plan']}; steps {m['steps']}; tool calls {m['tool_calls']}; "
            f"rewrites {m['retrieval_rewrites']}; verify loops {m['verify_loops']}; guardrail events {m['guardrail_events']}; "
            f"wall-clock {m['seconds']} s\n")
    return head + "\n" + observability.to_markdown(observability.node_table(events), ["node", "events", "loops", "rewrites", "ms"])


def compare_cases(case_ids, engine: str = "native") -> str:
    """Run each case and return one markdown row per case: plan, steps, tool calls, rewrites, loops, decision."""
    rows = []
    for cid in case_ids:
        m = observability.run_metrics(_run_case(cid, engine)["tracer"].events)
        rows.append({"case": cid, "plan": m["plan"], "steps": m["steps"], "tool_calls": m["tool_calls"],
                     "rewrites": m["retrieval_rewrites"], "loops": m["verify_loops"], "decision": m["decision"]})
    return observability.to_markdown(rows, ["case", "plan", "steps", "tool_calls", "rewrites", "loops", "decision"])


def main(argv=None):
    """Parse arguments, run one case (native or LangGraph engine), then print the optional trace and the report."""
    ap = argparse.ArgumentParser(description="Parametric Crop-Insurance Trigger Checker")
    ap.add_argument("--case", help="id from data/cases.json, e.g. M01")
    ap.add_argument("--policy", default=str(ROOT / "data/policy_sample.txt"))
    ap.add_argument("--primary")
    ap.add_argument("--secondary")
    ap.add_argument("--engine", choices=["native", "langgraph"], default="native")
    ap.add_argument("--fault", choices=["transient", "persistent"], help="inject a calculator bug into P1 (demo of the verifier)")
    ap.add_argument("--trace", action="store_true", help="print the step-by-step trace")
    ap.add_argument("--save", action="store_true", help="save trace (traces/) and record (runs/)")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--strict-value-check", action="store_true", help="escalate to a human when station index values diverge (default: INFO note only)")
    ap.add_argument("--trace-summary", metavar="CASE_OR_JSONL", help="print a compact per-node table for a case id or a saved trace file")
    ap.add_argument("--compare", nargs="+", metavar="CASE", help="one summary row per case, e.g. --compare C01 M01 F01 X01")
    a = ap.parse_args(argv)
    if a.trace_summary:
        print(trace_summary(a.trace_summary, a.engine))
        return
    if a.compare:
        print(compare_cases(a.compare, a.engine))
        return

    primary, secondary, fault = a.primary, a.secondary, a.fault
    if a.case:
        case = next((c for c in json.loads((ROOT / "data/cases.json").read_text())["cases"] if c["id"] == a.case), None)
        if not case:
            raise SystemExit(f"unknown case {a.case}")
        primary, secondary = ROOT / case["primary"], ROOT / case["secondary"]
        if case.get("fault") and not fault:
            fault = case["fault"]["mode"]
        print(f"[case {case['id']}] {case['description']}\n[expected] {case['expected']['decision']}\n")
    if not primary:
        raise SystemExit("give --case or --primary")
    kw = {"tracer": Tracer(out_dir=ROOT / "traces" if a.save else None), "llm": get_llm(), "verify_enabled": not a.no_verify,
          "strict_value_check": a.strict_value_check}
    if fault:
        kw["calculator"] = FaultyCalculator(fault, "P1")
    run = agent.run if a.engine == "native" else agent.run_langgraph
    s = run(a.policy, primary, secondary, **kw)
    if a.trace:
        print(s["tracer"].markdown(), "\n")
        print(_rewrite_detail(s["tracer"].events))
    print(s["report_md"])
    if a.save:
        print("\nsaved:", records.save_record(records.to_record(s), ROOT / "runs"))


if __name__ == "__main__":
    main()
