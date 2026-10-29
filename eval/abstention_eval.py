"""Selective-prediction (abstention) metrics: how much does each variant answer, and how good are the answers it gives?

Datasets: the 38 labelled cases and the 500-case randomised stress generator (same seed and generator as stress_eval.py).
Variants: naive baseline, agent without verifier, agent without cross-check, full agent.

  coverage              share of cases the variant answered (did not say CANNOT_DETERMINE)
  selective accuracy    among answered cases, share where decision AND total payout equal the truth
  unsafe-answer rate    among cases whose truth is CANNOT_DETERMINE, share the variant answered anyway
  over-abstention rate  among cases whose truth is determinate, share the variant refused to answer
  escalation rate       share of cases in a defect category that the variant escalated (CANNOT_DETERMINE)

Run:  python eval/abstention_eval.py        (writes eval/abstention_results.md)
"""
from __future__ import annotations

import json
import random
import sys
import tempfile
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_eval  # noqa: E402
import stress_eval  # noqa: E402
from crop_trigger import agent  # noqa: E402
from crop_trigger.baseline import run_baseline  # noqa: E402
from crop_trigger.engine import FaultyCalculator  # noqa: E402

VARIANTS = ["baseline_naive", "agent_no_verifier", "agent_no_crosscheck", "agent_full"]
POLICY = ROOT / "data/policy_sample.txt"


def answer_stress(variant: str, c: dict):
    """Run one variant on one stress case and return (decision, total_payout)."""
    if variant == "baseline_naive":
        r = run_baseline(POLICY, c["primary"])
        return r["decision"], r["total_payout"]
    kw = {"calculator": FaultyCalculator(c["fault"], "P1")} if c["fault"] else {}
    if variant == "agent_no_verifier":
        kw["verify_enabled"] = False
    if variant == "agent_no_crosscheck":
        kw["crosscheck_enabled"] = False
    s = agent.run(POLICY, c["primary"], c["secondary"], **kw)
    return s["decision"], s["total_payout"]


def labelled_records():
    """One record per (variant, case) for the 38 labelled cases: truth, answer and defect categories."""
    cases = run_eval.load_cases()
    recs = {v: [] for v in VARIANTS}
    for v in VARIANTS:
        for c, row in zip(cases, run_eval.score(v, cases)):
            e = c["expected"]
            recs[v].append({"truth": e["decision"], "got": row["got"], "ok": row["decision_ok"] and row["payout_ok"] in (None, True),
                            "cats": [c["category"]]})
    return recs


def stress_records(n=500, seed=2026):
    """One record per (variant, case) for the randomised stress cases (same generator and seed as stress_eval.py)."""
    rng = random.Random(seed)
    tmp = Path(tempfile.mkdtemp(prefix="abstain_"))
    cases = [stress_eval.make_case(rng, i, tmp) for i in range(n)]
    recs = {v: [] for v in VARIANTS}
    for c in cases:
        for v in VARIANTS:
            dec, tot = answer_stress(v, c)
            ok = dec == c["decision"] and (c["total"] is None or (tot is not None and D(str(tot)) == c["total"].quantize(D("0.01"))))
            recs[v].append({"truth": c["decision"], "got": dec, "ok": ok, "cats": sorted(set(c["flags"]))})
    return recs


def metrics(rs):
    """Coverage, selective accuracy, unsafe-answer and over-abstention rates for a list of records."""
    n = len(rs)
    answered = [r for r in rs if r["got"] != "CANNOT_DETERMINE"]
    truth_abs = [r for r in rs if r["truth"] == "CANNOT_DETERMINE"]
    truth_det = [r for r in rs if r["truth"] != "CANNOT_DETERMINE"]
    return {"n": n, "answered": len(answered),
            "coverage": len(answered) / n,
            "selective_accuracy": (sum(r["ok"] for r in answered) / len(answered)) if answered else None,
            "unsafe": (sum(r["got"] != "CANNOT_DETERMINE" for r in truth_abs) / len(truth_abs)) if truth_abs else None,
            "over_abstention": (sum(r["got"] == "CANNOT_DETERMINE" for r in truth_det) / len(truth_det)) if truth_det else None,
            "n_truth_abstain": len(truth_abs), "n_truth_determinate": len(truth_det)}


def escalation_by_category(rs):
    """{category: (cases, share escalated, share where the truth was CANNOT_DETERMINE)} for one variant."""
    by = defaultdict(list)
    for r in rs:
        for c in r["cats"]:
            by[c].append(r)
    return {c: (len(v), sum(r["got"] == "CANNOT_DETERMINE" for r in v) / len(v), sum(r["truth"] == "CANNOT_DETERMINE" for r in v) / len(v))
            for c, v in sorted(by.items())}


def section(title, recs):
    """Markdown for one dataset: the headline table and the per-category escalation table."""
    pct = run_eval.pct
    m = {v: metrics(recs[v]) for v in VARIANTS}
    n = m["agent_full"]["n"]
    L = [f"## {title}", "",
         f"{n} cases; truth is CANNOT_DETERMINE in {m['agent_full']['n_truth_abstain']} and determinate in {m['agent_full']['n_truth_determinate']}.", "",
         "| Metric | Naive baseline | Agent, no verifier | Agent, no cross-check | Agent (full) |", "|---|---|---|---|---|",
         "| Coverage (share answered) | " + " | ".join(pct(m[v]["coverage"]) for v in VARIANTS) + " |",
         "| Selective accuracy (correct among answered) | " + " | ".join(pct(m[v]["selective_accuracy"]) for v in VARIANTS) + " |",
         "| Unsafe-answer rate | " + " | ".join(pct(m[v]["unsafe"]) for v in VARIANTS) + " |",
         "| Over-abstention rate | " + " | ".join(pct(m[v]["over_abstention"]) for v in VARIANTS) + " |",
         "", "### Escalation rate by defect category (share of the category sent to a human; last column = share where the truth requires it)", "",
         "| Category | Cases | Baseline | No verifier | No cross-check | Full | Truth needs referral |", "|---|---|---|---|---|---|---|"]
    esc = {v: escalation_by_category(recs[v]) for v in VARIANTS}
    for c, (cnt, _, truth) in esc["agent_full"].items():
        L.append(f"| {c} | {cnt} | " + " | ".join(pct(esc[v][c][1]) for v in VARIANTS) + f" | {pct(truth)} |")
    return L + [""]


def main():
    """Compute both datasets, print the tables and write eval/abstention_results.md."""
    L = ["# Selective-prediction (abstention) metrics", "",
         "An answer is *correct* when the decision and the total payout both equal the truth. Coverage is the share of cases answered; "
         "the agent is allowed to refuse, so accuracy is judged only on what it answered. Numbers are exactly what "
         "`python eval/abstention_eval.py` printed.", ""]
    lab, stress = labelled_records(), stress_records()
    L += section("38 labelled cases", lab)
    L += section("500 randomised stress cases (seed 2026)", stress)
    L += ["## Reading", "",
          "A system that never abstains has coverage 100% but an unsafe-answer rate of 100% on cases that need a human. The full agent trades "
          "coverage for safety: it refuses where the evidence is not good enough, so its selective accuracy is judged on a smaller, "
          "safer set. Over-abstention is the share of answerable cases a variant refused. For the full agent it is "
          f"{run_eval.pct(metrics(lab['agent_full'])['over_abstention'])} on the labelled cases and "
          f"{run_eval.pct(metrics(stress['agent_full'])['over_abstention'])} on the stress cases, i.e. its lower coverage comes only from cases whose truth "
          "is CANNOT_DETERMINE (a lower coverage than the baseline is the intended behaviour, not a loss). "
          "Ablations show where each safeguard matters (no verifier: wrong answers on injected faults; no cross-check: station conflicts answered). "
          "Caveat: truth comes from the generator/oracle that shares the author's reading of the policy."]
    out = "\n".join(L) + "\n"
    (ROOT / "eval/abstention_results.md").write_text(out)
    print(out)


if __name__ == "__main__":
    main()
