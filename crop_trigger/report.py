"""Builds the explainable report (structured dict + markdown) from the final agent state."""
from __future__ import annotations

import re

DEFAULT_DISCLAIMER = ("This is an indicative trigger assessment only. It is not a claim approval, a claim rejection "
                      "or a guarantee of compensation.")

NEXT_STEP = {
    "missing_exceeds_limit": "Obtain the missing Primary Station readings from an official source and re-run the check.",
    "secondary_also_missing": "Obtain valid readings for the missing days from either station and re-run the check.",
    "no_secondary_data": "Provide a Secondary Station file for the same period so short gaps can be filled under the policy, then re-run.",
    "station_mismatch": "Confirm which station the uploaded file comes from and supply the Primary Station file.",
    "station_disagreement": "Refer the case to the Claims Review Committee. The Primary Station reading is not overridden automatically.",
    "calc_mismatch": "The calculation could not be independently verified. Do not rely on a number; escalate to the system owner.",
    "rule_not_grounded": "A person must read the cited clause and confirm the rule parameters before any figure is used.",
    "rule_llm_disagreement": "Two independent readings of the clause disagree. A person must confirm the rule.",
    "rule_extraction_failed": "The clause could not be parsed into a rule. A person must read it.",
    "policy_rules_not_found": "No rule clause was found. Check that the correct policy document was supplied.",
    "required_clause_not_found": "A required clause could not be located. A person must check the policy.",
    "input_missing": "Supply the missing input file and re-run.",
    "input_invalid": "Fix the file format (columns: date, rainfall, unit, station) and re-run.",
    "policy_unreadable": "Supply a policy document with numbered clauses.",
    "step_limit": "The run exceeded its step limit. Escalate to the system owner.",
    "value_divergence": "The two stations agree on the trigger but their index values differ by more than the tolerance. A person should check the station data.",
}


def _nums(text: str) -> set[str]:
    return {m.replace(",", "") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def _template_summary(state, decision, final) -> str:
    if decision == "CANNOT_DETERMINE":
        why = sorted({r["code"].replace("_", " ") for r in state.get("review_reasons", []) if r.get("severity") != "info"})
        return ("The trigger could not be determined from the supplied evidence and the case needs human review. "
                f"Reasons: {', '.join(why)}.")
    if decision == "TRIGGER_MET":
        met = [f"{k} (index {v['index']} {v['unit']})" for k, v in final.items() if v["status"] == "MET"]
        return (f"Under the sample policy, the trigger condition is met for {', '.join(met)}. "
                f"The indicative payout is INR {state['total_payout']}. This is not a claim decision.")
    return "Under the sample policy, no phase trigger is met for the supplied data. This is not a claim decision."


def _llm_summary(state, facts: str):
    llm = state.get("llm")
    if not llm or not getattr(llm, "available", False):
        return None, None
    try:
        text = llm.complete("You write 2-3 plain sentences for an insurance support analyst. Use ONLY the numbers given. "
                            "Never say a claim is approved or rejected.", facts).strip()
    except Exception as e:
        return None, f"LLM summary unavailable ({type(e).__name__})"
    extra = _nums(text) - _nums(facts)
    if extra:
        return None, f"LLM summary rejected: contains numbers not in the computed facts {sorted(extra)}"
    return text, None


def build_report(state):
    """Turn the final state into (report_data, report_md): decision, phase table, calculation steps, assumptions,
    human-review reasons and the policy clauses relied on. Numbers come from the state, never from the LLM."""
    final = state.get("phase_final", {})
    decision = state["decision"]
    rules = {r.phase_id: r for r in state.get("rules") or []}
    results = state.get("results") or {}
    facts = f"Decision: {decision}. " + " ".join(
        f"{k}: {v['status']}" + (f", index {v['index']} {v['unit']}, payout INR {v['payout']}" if v["status"] != "UNDETERMINED" else "")
        for k, v in final.items())
    summary = _template_summary(state, decision, final)
    llm_text, llm_note = _llm_summary(state, facts)
    if llm_text:
        summary = llm_text
    if llm_note:
        state["tracer"].event("guardrail", "write_report", llm_note)

    clause_text = state.get("clause_text", {})
    disclaimer = clause_text.get("5.2", DEFAULT_DISCLAIMER)
    phases = []
    for pid, v in final.items():
        r = rules[pid]
        row = {"phase": pid, "name": r.name, "clause": r.clause_id, "status": v["status"],
               "strike": str(r.strike), "window": f"{r.start} to {r.end}"}
        if v["status"] != "UNDETERMINED":
            row.update(index=str(v["index"]), unit=v["unit"], payout=str(v["payout"]), steps=list(results[pid].steps))
        else:
            row["why"] = v.get("code")
        phases.append(row)
    reasons = [{**x, "next_step": NEXT_STEP.get(x["code"], "A person must review this case.")} for x in state.get("review_reasons", [])]
    data = {"decision": decision, "status": state.get("status"), "summary": summary, "phases": phases,
            "total_payout_inr": None if state["total_payout"] is None else str(state["total_payout"]),
            "determinate_phases_payout_inr": str(state["determinate_payout"]),
            "fills": state.get("fills", []), "notes": state.get("notes", []), "review_reasons": reasons,
            "citations": {c: clause_text.get(c, "") for c in state.get("cited", []) if c in clause_text},
            "trace_id": state["tracer"].run_id, "disclaimer": disclaimer}

    L = [f"# Trigger assessment: {decision.replace('_', ' ')}", "", f"**{summary}**", ""]
    if decision == "CANNOT_DETERMINE" and state["determinate_payout"] > 0:
        L += [f"_Phases that could be assessed would indicate INR {state['determinate_payout']}, but no total is stated while any phase is undetermined._", ""]
    L += ["## Phase results", "", "| Phase | Clause | Window | Strike | Observed index | Result | Indicative payout (INR) |", "|---|---|---|---|---|---|---|"]
    for p in phases:
        obs = f"{p['index']} {p['unit']}" if "index" in p else "n/a"
        pay = p.get("payout", "n/a")
        L.append(f"| {p['phase']} {p['name']} | {p['clause']} | {p['window']} | {p['strike']} | {obs} | {p['status'].replace('_', ' ')} | {pay} |")
    L += ["", "## How each number was calculated", ""]
    for p in phases:
        if "steps" in p:
            L.append(f"**{p['phase']}**")
            L += [f"- {s}" for s in p["steps"]]
            L.append("")
    if data["total_payout_inr"] is not None:
        L += [f"Total after overall cap (clause 5.1): INR {data['total_payout_inr']}", ""]
    if data["fills"] or data["notes"]:
        L += ["## Data handling and assumptions", ""]
        if data["fills"]:
            by = {}
            for f in data["fills"]:
                by.setdefault(f["phase"], []).append(f"{f['date']} = {f['value_mm']} mm")
            for ph, items in by.items():
                L.append(f"- {ph}: {len(items)} missing Primary Station day(s) filled from {state['stations'][1]} under clause 4.1: " + ", ".join(items))
        L += [f"- {n}" for n in data["notes"]]
        L.append("")
    blocking = [x for x in reasons if x.get("severity") != "info"]
    info = [x for x in reasons if x.get("severity") == "info"]
    if blocking:
        L += ["## Needs human review", ""]
        for x in blocking:
            cl = f" (clause {', '.join(x['clauses'])})" if x["clauses"] else ""
            L.append(f"- **{x['code'].replace('_', ' ')}**{cl}: {x['detail']}. Next step: {x['next_step']}")
        L.append("")
    if info:
        L += ["## Informational notes (these do not change the decision)", ""]
        L += [f"- **INFO {x['code'].replace('_', ' ')}**: {x['detail']}" for x in info]
        L.append("")
    if data["citations"]:
        L += ["## Policy clauses relied on", ""]
        for cid, text in sorted(data["citations"].items()):
            L.append(f"- **Clause {cid}**: {text}")
        L.append("")
    L += ["---", f"_{disclaimer}_  ", f"_Trace: {data['trace_id']}_"]
    return data, "\n".join(L)
