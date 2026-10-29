"""Value-level cross-check evaluation: what happens when the two stations agree on the trigger but not on the index value?

Compares the default agent (value divergence is an INFO note only) with `agent_strict_values` (divergence escalates to a human)
on the 38 labelled cases and the 500 stress cases (same generator and seed as stress_eval.py).
Writes eval/value_check_results.md.

Run:  python eval/value_check.py
"""
from __future__ import annotations

import random
import sys
import tempfile
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_eval  # noqa: E402
import stress_eval  # noqa: E402
from crop_trigger import agent  # noqa: E402
from crop_trigger.engine import FaultyCalculator  # noqa: E402

POLICY = ROOT / "data/policy_sample.txt"


def labelled():
    """Per labelled case: id, truth, (decision, payout_ok, diverged) for the default and the strict variant."""
    out = []
    for c in run_eval.load_cases():
        e = c["expected"]
        rows = {}
        for v in ("agent_full", "agent_strict_values"):
            r = run_eval.run_variant(v, c)
            ok = r["decision"] == e["decision"] and (e["total_payout"] is None or (r["total"] is not None and D(str(r["total"])) == D(e["total_payout"])))
            rows[v] = {"decision": r["decision"], "ok": ok, "diverged": "value_divergence" in r["reasons"]}
        out.append({"id": c["id"], "truth": e["decision"], **{k: v for k, v in rows.items()}})
    return out


def stress(n=500, seed=2026):
    """Same record shape for the stress cases."""
    rng = random.Random(seed)
    tmp = Path(tempfile.mkdtemp(prefix="valcheck_"))
    out = []
    for i in range(n):
        c = stress_eval.make_case(rng, i, tmp)
        rows = {}
        for v, strict in (("agent_full", False), ("agent_strict_values", True)):
            kw = {"calculator": FaultyCalculator(c["fault"], "P1")} if c["fault"] else {}
            s = agent.run(POLICY, c["primary"], c["secondary"], strict_value_check=strict, **kw)
            tot = s["total_payout"]
            ok = s["decision"] == c["decision"] and (c["total"] is None or (tot is not None and D(str(tot)) == c["total"].quantize(D("0.01"))))
            rows[v] = {"decision": s["decision"], "ok": ok, "diverged": any(r.get("code") == "value_divergence" for r in s["review_reasons"])}
        out.append({"id": c["id"], "truth": c["decision"], **rows})
    return out


def summarize(recs):
    """Counts: INFO divergences, default correctness, strict escalations, correct answers lost, abstentions that were already right."""
    cd = "CANNOT_DETERMINE"
    full, strict = "agent_full", "agent_strict_values"
    escalated = [r for r in recs if r[full]["decision"] != cd and r[strict]["decision"] == cd]
    return {"n": len(recs),
            "info_divergence_cases": sum(r[full]["diverged"] for r in recs),
            "default_fully_correct": sum(r[full]["ok"] for r in recs),
            "same_decision": sum(r[full]["decision"] == r[strict]["decision"] for r in recs),
            "strict_new_escalations": len(escalated),
            "lost_correct_answers": [r["id"] for r in escalated if r[full]["ok"] and r["truth"] != cd],
            "strict_wrongly_answered_unsafe": sum(r["truth"] == cd and r[strict]["decision"] != cd for r in recs),
            "strict_fully_correct": sum(r[strict]["ok"] for r in recs),
            "escalated_ids": [r["id"] for r in escalated]}


def main():
    """Evaluate both datasets, print and write eval/value_check_results.md."""
    L = ["# Value-level cross-check", "",
         "Default behaviour: when both stations give the same trigger outcome but their index values differ by more than the tolerance "
         "(10% of the Primary value), the agent adds an INFO note (`value_divergence`) to the trace, the report and the review-reason list. "
         "It does **not** change any decision or payout. `agent_strict_values` (`strict_value_check=True`) escalates such a phase to a human instead. "
         "Numbers are exactly what `python eval/value_check.py` printed.", ""]
    for title, recs in (("38 labelled cases", labelled()), ("500 randomised stress cases (seed 2026)", stress())):
        m = summarize(recs)
        L += [f"## {title}", "",
              "| Measure | Value |", "|---|---|",
              f"| Cases | {m['n']} |",
              f"| Cases showing an INFO value divergence (default agent) | {m['info_divergence_cases']} |",
              f"| Default agent fully correct (decision and payout) | {m['default_fully_correct']}/{m['n']} |",
              f"| Strict variant gives the same decision as default | {m['same_decision']}/{m['n']} |",
              f"| Cases the strict variant newly escalates | {m['strict_new_escalations']} |",
              f"| Previously correct answers that become abstentions | {len(m['lost_correct_answers'])} |",
              f"| Cases where truth is CANNOT_DETERMINE but strict answers | {m['strict_wrongly_answered_unsafe']} |",
              f"| Strict variant fully correct | {m['strict_fully_correct']}/{m['n']} |", ""]
        if m["lost_correct_answers"]:
            L += ["Correct answers lost to strict escalation: " + ", ".join(m["lost_correct_answers"][:25]) + (" ..." if len(m["lost_correct_answers"]) > 25 else ""), ""]
    L += ["## Reading", "",
          "Whether a divergence is a problem depends on the policy: clause 4.1 only asks the stations' *trigger outcomes* to agree, so an escalation "
          "on value alone is stricter than the policy. The strict variant is therefore a design option, not the default; its cost is the "
          "'previously correct answers that become abstentions' row above, judged against truth derived from the same trigger-outcome rule."]
    out = "\n".join(L) + "\n"
    (ROOT / "eval/value_check_results.md").write_text(out)
    print(out)


if __name__ == "__main__":
    main()
