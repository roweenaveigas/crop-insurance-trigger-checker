"""Evaluate the agent (and ablations / baseline) on the labelled cases in data/cases.json.

Variants:
  agent_full         everything on
  agent_no_verifier  verifier disabled (ablation)
  agent_no_crosscheck  secondary-station cross-check disabled (ablation)
  agent_strict_values  value-level cross-check escalates instead of noting (used by eval/value_check.py)
  agent_no_plan      planning disabled: fixed full pipeline for every case (used by eval/plan_ablation.py)
  baseline_naive     one fixed pass: assume mm, fill gaps with 0, ignore secondary, never abstain

Metrics (per variant, overall and by category):
  decision_accuracy        3-class: TRIGGER_MET / TRIGGER_NOT_MET / CANNOT_DETERMINE
  index_exact              of phases that are determinate in the ground truth, share where the reported index equals the truth exactly
  payout_exact             of cases that are determinate in the ground truth, share where the total INR equals the truth exactly
  abstain_precision/recall CANNOT_DETERMINE treated as the positive class
  unsafe_answer_rate       share of cases where the truth is CANNOT_DETERMINE but the variant stated a payout decision
  citation_recall/precision  clauses cited vs. clauses that should be cited (agent variants only)
  verifier_catch_rate      fault cases where a calculator fault was flagged before reporting
  steps / tool_calls / loops  mean per run (agent variants only)

Run:  python eval/run_eval.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crop_trigger import agent  # noqa: E402
from crop_trigger.baseline import run_baseline  # noqa: E402
from crop_trigger.engine import FaultyCalculator  # noqa: E402
from crop_trigger.tracing import Tracer  # noqa: E402

ALLOWED_EXTRA = {"1.1", "1.3", "5.1", "5.2", "4.1"}


def load_cases():
    return json.loads((ROOT / "data" / "cases.json").read_text())["cases"]


def run_variant(variant: str, case: dict, save_trace: bool = False):
    pol, pri, sec = ROOT / "data/policy_sample.txt", ROOT / case["primary"], ROOT / case["secondary"]
    if variant == "baseline_naive":
        r = run_baseline(pol, pri)
        return {"decision": r["decision"], "total": r["total_payout"], "phases": r["phase_final"], "cited": [], "trace": None}
    kw = {"tracer": Tracer(run_id=f"{variant}-{case['id']}", out_dir=ROOT / "traces" if save_trace else None)}
    if case.get("fault"):
        kw["calculator"] = FaultyCalculator(case["fault"]["mode"], case["fault"]["phase"])
    if variant == "agent_no_verifier":
        kw["verify_enabled"] = False
    if variant == "agent_no_crosscheck":
        kw["crosscheck_enabled"] = False
    if variant == "agent_no_plan":
        kw["plan_enabled"] = False
    if variant == "agent_strict_values":
        kw["strict_value_check"] = True
    s = agent.run(pol, pri, sec, **kw)
    t = s["tracer"]
    flagged = any(e["kind"] == "loop" for e in t.events) or any(e["kind"] == "guardrail" and "mismatch persists" in e["summary"] for e in t.events)
    return {"decision": s["decision"], "total": s["total_payout"], "phases": s["phase_final"], "cited": s["cited"],
            "steps": len(t.events), "tools": t.count("tool") + t.count("retrieval"), "loops": t.count("loop"), "flagged": flagged,
            "rewrites": sum(v["rewrites"] for v in s["retrievals"].values()), "needs": len(s["retrievals"]),
            "trace": t.run_id, "reasons": [r["code"] for r in s["review_reasons"]]}


def score(variant: str, cases, save_trace=False):
    rows = []
    for c in cases:
        r = run_variant(variant, c, save_trace)
        e = c["expected"]
        row = {"id": c["id"], "category": c["category"], "variant": variant, "expected": e["decision"], "got": r["decision"],
               "decision_ok": r["decision"] == e["decision"]}
        # index exactness on ground-truth-determinate phases
        idx_total = idx_ok = 0
        for pid, ep in e["phases"].items():
            if ep["status"] == "UNDETERMINED":
                continue
            idx_total += 1
            gp = r["phases"].get(pid)
            if gp and gp.get("status") != "UNDETERMINED" and gp.get("index") is not None and D(str(gp["index"])) == D(ep["index"]):
                idx_ok += 1
        row["idx_total"], row["idx_ok"] = idx_total, idx_ok
        if e["total_payout"] is not None:
            row["payout_ok"] = r["total"] is not None and D(str(r["total"])) == D(e["total_payout"])
        else:
            row["payout_ok"] = None
        row["unsafe"] = e["decision"] == "CANNOT_DETERMINE" and r["decision"] != "CANNOT_DETERMINE"
        if variant.startswith("agent"):
            need = set(e["cited_clauses"])
            got = set(r["cited"])
            row["cite_recall"] = len(need & got) / len(need)
            allowed = need | ALLOWED_EXTRA
            row["cite_precision"] = len(got & allowed) / len(got) if got else 0.0
            row.update(steps=r["steps"], tools=r["tools"], loops=r["loops"], rewrites=r["rewrites"], needs=r["needs"])
            if c.get("fault"):
                row["fault_flagged"] = r["flagged"]
            row["trace"] = r["trace"]
        rows.append(row)
    return rows


def summarize(rows):
    n = len(rows)
    tp = sum(1 for r in rows if r["expected"] == "CANNOT_DETERMINE" and r["got"] == "CANNOT_DETERMINE")
    pred = sum(1 for r in rows if r["got"] == "CANNOT_DETERMINE")
    act = sum(1 for r in rows if r["expected"] == "CANNOT_DETERMINE")
    pay = [r for r in rows if r["payout_ok"] is not None]
    it = sum(r["idx_total"] for r in rows)
    out = {"cases": n,
           "decision_accuracy": sum(r["decision_ok"] for r in rows) / n,
           "index_exact": (sum(r["idx_ok"] for r in rows) / it) if it else None,
           "payout_exact": (sum(1 for r in pay if r["payout_ok"]) / len(pay)) if pay else None,
           "abstain_precision": (tp / pred) if pred else None,
           "abstain_recall": (tp / act) if act else None,
           "unsafe_answer_rate": (sum(1 for r in rows if r["unsafe"]) / act) if act else None}
    if "steps" in rows[0]:
        out["citation_recall"] = sum(r["cite_recall"] for r in rows) / n
        out["citation_precision"] = sum(r["cite_precision"] for r in rows) / n
        out["mean_steps"] = sum(r["steps"] for r in rows) / n
        out["mean_tool_calls"] = sum(r["tools"] for r in rows) / n
        out["mean_loops"] = sum(r["loops"] for r in rows) / n
        nn = sum(r["needs"] for r in rows)
        out["retrieval_rewrite_rate"] = sum(r["rewrites"] for r in rows) / nn if nn else 0
        f = [r for r in rows if "fault_flagged" in r]
        out["verifier_catch_rate"] = (sum(1 for r in f if r["fault_flagged"]) / len(f)) if f else None
    return out


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def main():
    cases = load_cases()
    variants = ["baseline_naive", "agent_no_verifier", "agent_no_crosscheck", "agent_full"]
    allrows, summary = {}, {}
    for v in variants:
        rows = score(v, cases, save_trace=(v == "agent_full"))
        allrows[v] = rows
        summary[v] = summarize(rows)
    by_cat = {}
    cats = sorted({c["category"] for c in cases})
    for v in variants:
        by_cat[v] = {cat: sum(r["decision_ok"] for r in allrows[v] if r["category"] == cat) / sum(1 for r in allrows[v] if r["category"] == cat) for cat in cats}

    (ROOT / "eval").mkdir(exist_ok=True)
    (ROOT / "eval/results.json").write_text(json.dumps({"summary": summary, "by_category_decision_accuracy": by_cat, "rows": allrows}, indent=2, default=str))

    L = [f"# Evaluation results ({len(cases)} labelled cases)", "",
         "Ground truth is planted by construction in `data/generate_data.py` (not produced by the agent). Numbers below are exactly what `python eval/run_eval.py` printed.", "",
         "## Headline comparison", "",
         "| Metric | Naive baseline | Agent, no verifier | Agent, no cross-check | Agent (full) |", "|---|---|---|---|---|"]
    def line(label, key, fmt=pct):
        L.append(f"| {label} | " + " | ".join(fmt(summary[v].get(key)) if summary[v].get(key) is not None or key in summary[v] else "n/a" for v in variants) + " |")
    line("Decision accuracy (3-class)", "decision_accuracy")
    line("Index exact (determinate phases)", "index_exact")
    line("Total payout exact (determinate cases)", "payout_exact")
    line("Abstention precision", "abstain_precision")
    line("Abstention recall", "abstain_recall")
    line("Unsafe-answer rate (answered when it should abstain)", "unsafe_answer_rate")
    line("Citation recall", "citation_recall")
    line("Citation precision", "citation_precision")
    line("Verifier catch rate on injected faults", "verifier_catch_rate")
    L += ["", "## Decision accuracy by category", "", "| Category | " + " | ".join(variants) + " |", "|---|" + "---|" * len(variants)]
    for cat in cats:
        L.append(f"| {cat} | " + " | ".join(pct(by_cat[v][cat]) for v in variants) + " |")
    f = summary["agent_full"]
    L += ["", "## Cost of agency (agent_full)", "",
          f"- mean steps per run: {f['mean_steps']:.1f}; mean tool/retrieval calls: {f['mean_tool_calls']:.1f}; mean verify loops: {f['mean_loops']:.2f}",
          f"- retrieval rewrite rate: {pct(f['retrieval_rewrite_rate'])} of policy lookups needed a rewritten query",
          "", "## Cases where agent_full did not match the ground truth", ""]
    bad = [r for r in allrows["agent_full"] if not (r["decision_ok"] and (r["payout_ok"] in (None, True)))]
    if not bad:
        L.append("None.")
    for r in bad:
        L.append(f"- {r['id']} ({r['category']}): expected {r['expected']}, got {r['got']}, payout_ok={r['payout_ok']}")
    L += ["", "## Cases where the naive baseline was wrong", ""]
    for r in allrows["baseline_naive"]:
        if not r["decision_ok"]:
            L.append(f"- {r['id']} ({r['category']}): wrong decision - expected {r['expected']}, baseline said {r['got']}")
        elif r["payout_ok"] is False:
            L.append(f"- {r['id']} ({r['category']}): right decision ({r['got']}) but wrong payout figure")
    (ROOT / "eval/results.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
