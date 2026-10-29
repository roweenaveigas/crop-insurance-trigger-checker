"""Planning ablation: does the data-driven plan matter?  agent_full (plan from the data) vs agent_no_plan (the same
fixed full pipeline for every case) on the 38 labelled cases. Writes eval/plan_ablation_results.md.

Run:  python eval/plan_ablation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # so `import run_eval` works from any directory
import run_eval  # noqa: E402

ROOT = run_eval.ROOT
VARIANTS = ["agent_full", "agent_no_plan"]


def by_category(rows, key):
    """Mean of rows[key] per category (decision_ok is averaged as a share)."""
    cats = sorted({r["category"] for r in rows})
    return {c: sum(r[key] for r in rows if r["category"] == c) / sum(1 for r in rows if r["category"] == c) for c in cats}


def main():
    """Score both variants on the labelled cases, print the comparison and write the results file."""
    cases = run_eval.load_cases()
    rows = {v: run_eval.score(v, cases) for v in VARIANTS}
    summ = {v: run_eval.summarize(rows[v]) for v in VARIANTS}
    pct = run_eval.pct
    L = [f"# Planning ablation ({len(cases)} labelled cases)", "",
         "`agent_full` builds its plan from what the data looks like (unit conversion only if non-mm labels exist, gap filling only if "
         "gaps exist, cross-check only if a secondary file exists). `agent_no_plan` runs the fixed full pipeline for every case. "
         "Numbers are exactly what `python eval/plan_ablation.py` printed.", "",
         "| Metric | agent_full (planned) | agent_no_plan (fixed pipeline) |", "|---|---|---|",
         f"| Decision accuracy | {pct(summ['agent_full']['decision_accuracy'])} | {pct(summ['agent_no_plan']['decision_accuracy'])} |",
         f"| Total payout exact | {pct(summ['agent_full']['payout_exact'])} | {pct(summ['agent_no_plan']['payout_exact'])} |",
         f"| Unsafe-answer rate | {pct(summ['agent_full']['unsafe_answer_rate'])} | {pct(summ['agent_no_plan']['unsafe_answer_rate'])} |",
         f"| Mean steps per run | {summ['agent_full']['mean_steps']:.1f} | {summ['agent_no_plan']['mean_steps']:.1f} |",
         f"| Mean tool/retrieval calls per run | {summ['agent_full']['mean_tool_calls']:.1f} | {summ['agent_no_plan']['mean_tool_calls']:.1f} |",
         "", "## By category", "",
         "| Category | Accuracy planned | Accuracy fixed | Mean steps planned | Mean steps fixed | Mean tool calls planned | Mean tool calls fixed |",
         "|---|---|---|---|---|---|---|"]
    acc = {v: by_category(rows[v], "decision_ok") for v in VARIANTS}
    stp = {v: by_category(rows[v], "steps") for v in VARIANTS}
    tl = {v: by_category(rows[v], "tools") for v in VARIANTS}
    for c in acc["agent_full"]:
        L.append(f"| {c} | {pct(acc['agent_full'][c])} | {pct(acc['agent_no_plan'][c])} | {stp['agent_full'][c]:.1f} | {stp['agent_no_plan'][c]:.1f} "
                 f"| {tl['agent_full'][c]:.1f} | {tl['agent_no_plan'][c]:.1f} |")
    diff = [(a["id"], a["got"], b["got"]) for a, b in zip(rows["agent_full"], rows["agent_no_plan"]) if a["got"] != b["got"]]
    same_acc = summ["agent_full"]["decision_accuracy"] == summ["agent_no_plan"]["decision_accuracy"]
    L += ["", "## Reading", ""]
    if diff:
        L.append("Cases where the two variants decided differently: " + "; ".join(f"{i}: planned {a}, fixed {b}" for i, a, b in diff) + ".")
    else:
        L.append("The two variants made the same decision on every case.")
    d_steps = summ["agent_no_plan"]["mean_steps"] - summ["agent_full"]["mean_steps"]
    d_tools = summ["agent_no_plan"]["mean_tool_calls"] - summ["agent_full"]["mean_tool_calls"]
    if same_acc:
        L.append(f"Accuracy is equal, so on these cases planning buys **cost, not correctness**: the fixed pipeline makes {d_tools:.1f} more "
                 f"tool/retrieval calls per run (policy lookups for clauses the case does not need) and {d_steps:+.1f} trace steps "
                 "(each skipped step logs a 'skipped' event and each extra lookup logs a retrieval event, so step counts barely move). The saving is small on this one policy.")
    else:
        L.append("Accuracy differs between the variants; see the table above.")
    L.append("Caveat: both variants share the same code and the same hand-written cases, so this shows what the plan saves, not that it generalises.")
    out = "\n".join(L) + "\n"
    (ROOT / "eval/plan_ablation_results.md").write_text(out)
    print(out)


if __name__ == "__main__":
    main()
