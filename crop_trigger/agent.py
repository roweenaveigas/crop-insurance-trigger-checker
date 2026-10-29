"""The agent: a state graph of nodes with conditional routing, a bounded verify->recompute loop and a human gate.

Graph (conditional edges marked ?):

  intake ? retrieve_rules ? load_validate ? make_plan -> retrieve_support ? remediate -> compute -> verify
        verify ? compute (retry, bounded) | cross_check (only if the plan has 'cross') | decide
        cross_check -> decide -> human_gate -> write_report -> END
  The plan (make_plan) drives the route: remediate and verify act only on the steps it lists.
  Any node that cannot continue safely sets `halt`, which routes straight to `decide` (abstain + explain).

The same node functions run on a tiny built-in runner (`run`, no dependencies) or on LangGraph
(`build_langgraph`, needs `pip install langgraph`). Nodes read the state and return a dict of updates.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any, TypedDict

from . import rag, rules as R, tools, verify as V
from .engine import MissingDataError, apply_overall_cap, compute_phase, D
from .llm import NullLLM
from .report import build_report
from .tracing import Tracer

MAX_STEPS = 40            # hard cap on node executions per run (guardrail against runaway loops)
MAX_COMPUTE_ATTEMPTS = 2  # first try + one retry after a verifier mismatch
VALUE_TOLERANCE = D("0.10")  # cross-check: relative gap |primary - secondary| / |primary| above this raises a value_divergence note


class AgentState(TypedDict, total=False):
    """Shared run state. Every node reads it and returns a dict of updates; the runner merges them in.
    Keys are grouped below: inputs/configuration, working memory, then outputs."""
    # inputs / configuration
    policy_path: str
    primary_csv: str
    secondary_csv: str | None
    tracer: Any
    calculator: Any
    llm: Any
    verify_enabled: bool
    crosscheck_enabled: bool
    strict_value_check: bool      # False (default): value divergence is an INFO note; True: it escalates the phase to a human
    value_tolerance: Any          # relative tolerance override (Decimal); None means VALUE_TOLERANCE
    plan_enabled: bool            # False = ablation: run the fixed full pipeline instead of the data-driven plan
    # working memory
    halt: bool
    step_count: int
    policy_text: str
    index: Any
    clause_text: dict
    retrievals: dict
    rules: list
    stations: tuple
    period: tuple
    overall_cap: Any
    factors: dict
    fill_limit: int | None
    df_primary: Any
    df_secondary: Any
    prof_primary: dict
    prof_secondary: dict | None
    plan_steps: list
    series_primary: dict
    series_secondary: dict
    dq: dict
    phase_series: dict
    phase_status: dict
    fills: list
    notes: list
    results: dict
    sec_results: dict
    compute_attempts: int
    verify_problems: list
    retry: bool
    review_reasons: list
    cited: list
    # outputs
    decision: str
    phase_final: dict
    total_payout: Any
    determinate_payout: Any
    status: str
    report_data: dict
    report_md: str


def _t(s) -> Tracer:
    return s["tracer"]


def _reason(code, detail, phase=None, clauses=(), severity=None):
    """A review reason. `severity="info"` marks a note that never blocks a decision; reasons without it block."""
    r = {"code": code, "phase": phase, "detail": detail, "clauses": list(clauses)}
    if severity:
        r["severity"] = severity
    return r


def _blocking(reasons):
    """The reasons that can stop a decision (everything except INFO notes)."""
    return [r for r in reasons if r.get("severity") != "info"]


def _relative_gap(primary, secondary):
    """|primary - secondary| / |primary| as a Decimal; 0 if equal; Infinity if primary is 0 and secondary is not."""
    if primary == secondary:
        return D(0)
    if primary == 0:
        return D("Infinity")
    return abs(primary - secondary) / abs(primary)


def _uniq(seq):
    out = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out


def _retrieve(state, name) -> rag.Retrieval:
    r = rag.retrieve(state["index"], rag.NEEDS[name])
    _t(state).event("retrieval", "rag", f"need '{name}': {r.status}; clauses {r.clause_ids}; rewrites {r.rewrites}",
                    need=name, attempts=r.attempts)
    return r


def _remember(state, name, r, clause_text, retrievals, cited):
    retrievals[name] = {"status": r.status, "clauses": r.clause_ids, "rewrites": r.rewrites, "attempts": len(r.attempts)}
    for c in r.chunks:
        clause_text[c.clause_id] = c.text
    cited.extend(r.clause_ids)


# ------------------------------------------------------------------------------------------ nodes
def intake(state):
    t = _t(state)
    reasons = []
    for key, label in (("policy_path", "policy file"), ("primary_csv", "primary weather file")):
        p = state.get(key)
        if not p or not Path(p).exists():
            reasons.append(_reason("input_missing", f"{label} not found: {p}"))
    base = {"review_reasons": [], "cited": [], "retrievals": {}, "clause_text": {}, "fills": [], "notes": [],
            "compute_attempts": 0, "retry": False, "halt": False, "results": {}, "phase_status": {},
            "fill_limit": None, "factors": {"mm": D(1)}}
    if reasons:
        t.event("guardrail", "intake", "input validation failed -> halt", reasons=reasons)
        return {**base, "halt": True, "review_reasons": reasons}
    text = Path(state["policy_path"]).read_text()
    index = rag.PolicyIndex.from_text(text)
    if not index.chunks:
        r = [_reason("policy_unreadable", "no 'Clause N.N' sections found in the policy text")]
        t.event("guardrail", "intake", "policy has no recognisable clauses -> halt")
        return {**base, "halt": True, "review_reasons": r}
    sec = state.get("secondary_csv")
    sec = sec if sec and Path(sec).exists() else None
    t.event("node", "intake", f"policy loaded ({len(index.chunks)} clauses); primary={Path(state['primary_csv']).name}; "
                              f"secondary={Path(sec).name if sec else 'none'}")
    return {**base, "policy_text": text, "index": index, "secondary_csv": sec}


def retrieve_rules(state):
    """Node 2. Use agentic retrieval (grade, rewrite, retry) to find the phase, station, period, cap and dry-day clauses,
    parse them into PhaseRule objects, and halt (-> decide) if a needed clause cannot be found or parsed."""
    t = _t(state)
    retrievals, clause_text, cited = dict(state["retrievals"]), dict(state["clause_text"]), list(state["cited"])
    reasons = list(state["review_reasons"])

    def halt(code, detail, clauses=()):
        reasons.append(_reason(code, detail, clauses=clauses))
        t.event("guardrail", "retrieve_rules", f"{code}: {detail} -> halt")
        return {"halt": True, "review_reasons": reasons, "retrievals": retrievals, "clause_text": clause_text, "cited": _uniq(cited)}

    ph = _retrieve(state, "phases")
    _remember(state, "phases", ph, clause_text, retrievals, cited)
    if ph.status != "ok":
        return halt("policy_rules_not_found", "no clause describing an observation window and strike was found")
    needs = {}
    for name in ("stations", "period", "overall_cap", "disclaimer"):
        needs[name] = _retrieve(state, name)
        _remember(state, name, needs[name], clause_text, retrievals, cited)
    chunks = sorted(ph.chunks, key=lambda c: c.clause_id)
    dry = None
    if any("dry spell" in c.title.lower() for c in chunks):
        dr = _retrieve(state, "dry_day")
        _remember(state, "dry_day", dr, clause_text, retrievals, cited)
        if dr.status != "ok":
            return halt("required_clause_not_found", "dry-day definition not found")
        dry = R.extract_dry_threshold(dr.chunks[0].text)
    for name in ("stations", "period", "overall_cap"):
        if needs[name].status != "ok":
            return halt("required_clause_not_found", f"clause for '{name}' not found")
    try:
        rules = [R.extract_phase_rule(c, i, dry) for i, c in enumerate(chunks, 1)]
        stations = R.extract_stations(needs["stations"].chunks[0].text)
        cap = R.extract_overall_cap(needs["overall_cap"].chunks[0].text)
        period = R.extract_period(needs["period"].chunks[0].text)
    except R.ExtractionError as e:
        return halt("rule_extraction_failed", str(e), [c.clause_id for c in chunks])
    t.event("tool", "rule_extractor", f"extracted {len(rules)} phase rule(s): " + "; ".join(
        f"{r.phase_id}={r.index_type} {r.start}..{r.end} strike {r.strike}" for r in rules),
        rules=[{"phase": r.phase_id, "clause": r.clause_id, "type": r.index_type, "strike": r.strike} for r in rules])

    llm = state.get("llm") or NullLLM()
    if llm.available:
        for rule, chunk in zip(rules, chunks):
            try:
                diffs = R.llm_rule_check(llm, chunk, rule)
            except R.LLMOutputError as e:   # LLM gave no usable opinion: not a disagreement, keep the parser result
                t.event("guardrail", "rule_extractor", f"LLM output unusable for {rule.phase_id} ({e}); parser result kept")
                continue
            except Exception as e:  # network / provider failure must not break the run
                t.event("guardrail", "rule_extractor", f"LLM cross-check unavailable ({type(e).__name__}); parser result kept")
                break
            if diffs:
                return halt("rule_llm_disagreement", f"{rule.phase_id}: " + "; ".join(diffs), [chunk.clause_id])
            t.event("guardrail", "rule_extractor", f"LLM cross-check agrees on {rule.phase_id} ({llm.name})")
    else:
        t.event("guardrail", "rule_extractor", "no LLM configured: deterministic parser only")
    t.event("node", "retrieve_rules", f"reference stations {stations}; overall cap INR {cap}; period {period[0]}..{period[1]}")
    return {"rules": rules, "stations": stations, "overall_cap": cap, "period": period, "retrievals": retrievals,
            "clause_text": clause_text, "cited": _uniq(cited)}


def load_validate(state):
    t = _t(state)
    reasons = list(state["review_reasons"])
    out = {}
    try:
        dfp = tools.load_weather_csv(state["primary_csv"])
    except tools.WeatherFileError as e:
        reasons.append(_reason("input_invalid", f"primary file: {e}"))
        t.event("tool", "load_weather", f"primary file rejected: {e} -> halt")
        return {"halt": True, "review_reasons": reasons}
    pp = tools.profile(dfp)
    t.event("tool", "load_weather", f"primary: {pp['rows']} rows, stations {pp['stations']}, units {pp['units']}, "
                                    f"{pp['first_date']}..{pp['last_date']}", profile=pp)
    out.update(df_primary=dfp, prof_primary=pp, df_secondary=None, prof_secondary=None)
    if state.get("secondary_csv"):
        try:
            dfs = tools.load_weather_csv(state["secondary_csv"])
            ps = tools.profile(dfs)
            t.event("tool", "load_weather", f"secondary: {ps['rows']} rows, stations {ps['stations']}, units {ps['units']}", profile=ps)
            out.update(df_secondary=dfs, prof_secondary=ps)
        except tools.WeatherFileError as e:
            state["tracer"].event("tool", "load_weather", f"secondary file unusable: {e}")
            out["notes"] = list(state["notes"]) + [f"secondary file unusable: {e}"]
    return out


def make_plan(state):
    """Decide which extra checks this particular case needs, from what the data actually looks like."""
    t = _t(state)
    if not state.get("plan_enabled", True):
        # ablation: no looking at the data; every case gets the same fixed pipeline (units, gaps, cross-check, always)
        steps = ["units", "missing"] + (["cross"] if state.get("crosscheck_enabled", True) else []) + ["compute", "verify"]
        t.event("plan", "make_plan", "plan: " + " -> ".join(steps) + " (planning disabled: fixed full pipeline)",
                thoughts=["plan_enabled=False: run every step for every case regardless of what the data looks like"])
        out = {"plan_steps": steps}
        if "cross" not in steps:
            out["notes"] = list(state["notes"]) + ["no cross-check against the Secondary Station was possible: outcome is uncorroborated"]
        return out
    pp, ps = state["prof_primary"], state["prof_secondary"]
    labels = set(pp["units"]) | (set(ps["units"]) if ps else set())
    steps = []
    thoughts = []
    if labels - {"mm"}:
        steps.append("units")
        thoughts.append(f"unit labels other than mm present {sorted(labels - {'mm'})} -> must read the units clause before trusting any number")
    probe = {u: D(1) for u in tools.KNOWN_UNIT_LABELS}      # detection only; real factors come from the policy clause
    sp, issues = tools.build_series(state["df_primary"], probe)
    gaps = {r.phase_id: [d for d in r.window() if d not in sp] for r in state["rules"]}
    n_gap = sum(len(v) for v in gaps.values())
    if n_gap:
        steps.append("missing")
        thoughts.append(f"{n_gap} day(s) without a usable primary reading inside observation windows "
                        f"({', '.join(f'{k}:{len(v)}' for k, v in gaps.items() if v)}) -> need the missing-data clause")
    if state.get("df_secondary") is not None and state.get("crosscheck_enabled", True):
        steps.append("cross")
        thoughts.append("secondary station available -> cross-verify trigger outcomes (clause on station disagreement)")
    steps += ["compute", "verify"]
    thoughts.append("then compute indices deterministically and verify them independently; retry once on mismatch, otherwise escalate")
    skipped = [s for s in ("units", "missing", "cross") if s not in steps]
    if skipped:
        thoughts.append(f"not needed for this case, so skipped: {skipped}")
    t.event("plan", "make_plan", "plan: " + " -> ".join(steps), thoughts=thoughts)
    out = {"plan_steps": steps}
    if "cross" not in steps:   # the plan now decides the route, so the 'uncorroborated' note is recorded here
        out["notes"] = list(state["notes"]) + ["no cross-check against the Secondary Station was possible: outcome is uncorroborated"]
    return out


def retrieve_support(state):
    t = _t(state)
    retrievals, clause_text, cited = dict(state["retrievals"]), dict(state["clause_text"]), list(state["cited"])
    reasons = list(state["review_reasons"])
    factors, limit = dict(state["factors"]), state["fill_limit"]
    for name in [s for s in state["plan_steps"] if s in rag.NEEDS]:
        r = _retrieve(state, name)
        _remember(state, name, r, clause_text, retrievals, cited)
        if r.status != "ok":
            reasons.append(_reason("required_clause_not_found", f"could not find the policy clause for '{name}'"))
            t.event("guardrail", "retrieve_support", f"clause for '{name}' not found after {len(r.attempts)} attempt(s) -> abstain")
            return {"halt": True, "review_reasons": reasons, "retrievals": retrievals, "clause_text": clause_text, "cited": _uniq(cited)}
        try:
            if name == "units":
                factors = R.extract_unit_factors(r.chunks[0].text)
            elif name == "missing":
                limit = R.extract_fill_limit(r.chunks[0].text)
        except R.ExtractionError as e:
            reasons.append(_reason("rule_extraction_failed", str(e), clauses=r.clause_ids))
            return {"halt": True, "review_reasons": reasons, "retrievals": retrievals, "clause_text": clause_text, "cited": _uniq(cited)}
    t.event("node", "retrieve_support", f"unit factors {({k: str(v) for k, v in factors.items()})}; fill limit {limit}")
    return {"retrievals": retrievals, "clause_text": clause_text, "cited": _uniq(cited), "factors": factors, "fill_limit": limit}


def remediate(state):
    """Clean the data the way the policy allows: convert units, fill short gaps from the secondary station, or abstain."""
    t = _t(state)
    reasons, notes = list(state["review_reasons"]), list(state["notes"])
    # Only do what the plan lists: unit factors apply only if 'units' is planned (else plain mm),
    # and gap filling is allowed only if 'missing' is planned (else any gap withholds the phase).
    plan = state["plan_steps"]
    fac = state["factors"] if "units" in plan else {"mm": D(1)}
    limit = state["fill_limit"] if "missing" in plan else None
    if "units" not in plan:
        t.event("node", "remediate", "unit conversion skipped: 'units' not in plan (all labels are mm)")
    if "missing" not in plan:
        t.event("node", "remediate", "gap filling skipped: 'missing' not in plan (no gaps seen in the primary file)")
    p_station, s_station = state["stations"]
    ser_p, iss_p = tools.build_series(state["df_primary"], fac)
    dfs = state.get("df_secondary")
    ser_s, iss_s = tools.build_series(dfs, fac) if dfs is not None else ({}, {})
    if iss_p["converted"]:
        notes.append(f"primary readings converted to mm: {iss_p['converted']} day(s) (clause 2.1)")
    if iss_p["deduped_days"]:
        notes.append(f"{iss_p['deduped_days']} identical duplicate day(s) in primary file were collapsed")
    if iss_p["conflicting_dates"]:
        notes.append(f"{len(iss_p['conflicting_dates'])} day(s) with conflicting duplicate readings treated as invalid")
    if iss_p["unsupported_units"]:
        notes.append(f"readings with unsupported/blank unit treated as invalid: {iss_p['unsupported_units']} (clause 2.1)")
    fills, status, pseries = [], {}, {}
    sec_ok = dfs is not None and set(state["prof_secondary"]["stations"]) == {s_station}
    if dfs is not None and not sec_ok:
        notes.append(f"secondary file station(s) {state['prof_secondary']['stations']} are not the policy's Secondary Station {s_station}; not used")
    if set(state["prof_primary"]["stations"]) != {p_station}:
        reasons.append(_reason("station_mismatch", f"primary file station(s) {state['prof_primary']['stations']} but the policy's Primary Station is {p_station}", clauses=["1.3"]))
        for r in state["rules"]:
            status[r.phase_id] = {"status": "UNDETERMINED", "code": "station_mismatch"}
            pseries[r.phase_id] = {}
    else:
        for r in state["rules"]:
            win = r.window()
            series = {d: ser_p[d] for d in win if d in ser_p}
            missing = [d for d in win if d not in ser_p]
            pseries[r.phase_id] = series
            if not missing:
                status[r.phase_id] = {"status": "READY", "code": None}
                continue
            code = detail = None
            if limit is None:
                code, detail = "required_clause_not_found", "gaps found but the missing-data limit is unknown"
            elif not sec_ok:
                code, detail = "no_secondary_data", f"{len(missing)} missing day(s) and no usable Secondary Station file"
            elif len(missing) > limit:
                code, detail = "missing_exceeds_limit", f"{len(missing)} missing day(s) exceeds the limit of {limit} per phase"
            else:
                absent = [d for d in missing if d not in ser_s]
                if absent:
                    code, detail = "secondary_also_missing", f"Secondary Station also has no valid reading on {', '.join(map(str, absent))}"
            if code:
                reasons.append(_reason(code, f"{r.phase_id}: {detail}", phase=r.phase_id, clauses=["4.1"]))
                status[r.phase_id] = {"status": "UNDETERMINED", "code": code}
                t.event("guardrail", "remediate", f"{r.phase_id}: {detail} -> phase withheld for human review")
                continue
            for d in missing:
                series[d] = ser_s[d]
                fills.append({"phase": r.phase_id, "date": d.isoformat(), "value_mm": str(ser_s[d]), "source": s_station})
            status[r.phase_id] = {"status": "READY", "code": None}
            t.event("tool", "remediate", f"{r.phase_id}: filled {len(missing)} missing day(s) from {s_station} (clause 4.1, limit {limit})",
                    days=[d.isoformat() for d in missing])
    ready = [k for k, v in status.items() if v["status"] == "READY"]
    t.event("node", "remediate", f"phases ready to compute: {ready}; withheld: {[k for k in status if k not in ready]}")
    return {"series_primary": ser_p, "series_secondary": ser_s if sec_ok else {}, "phase_series": pseries, "phase_status": status,
            "fills": fills, "notes": notes, "review_reasons": reasons, "dq": {"primary": iss_p, "secondary": iss_s}}


def compute(state):
    t = _t(state)
    calc = state.get("calculator") or compute_phase
    if hasattr(calc, "new_attempt"):
        calc.new_attempt()
    attempt = state["compute_attempts"] + 1
    results = {}
    for r in state["rules"]:
        if state["phase_status"].get(r.phase_id, {}).get("status") != "READY":
            continue
        try:
            res = calc(r, state["phase_series"][r.phase_id])
        except MissingDataError as e:   # should be impossible after remediate; treat as a hard stop for this phase
            t.event("guardrail", "compute", f"{r.phase_id}: unexpected missing data {e}")
            continue
        results[r.phase_id] = res
        t.event("tool", "calculator", f"attempt {attempt} {r.phase_id}: index {res.index} {res.index_unit}; triggered={res.triggered}; payout INR {res.payout}",
                steps=list(res.steps))
    return {"results": results, "compute_attempts": attempt}


def verify(state):
    """Run the verifier; if no retry follows and the plan has no 'cross' step, say so in the trace (route goes to decide)."""
    out = _verify(state)
    if not out.get("retry") and "cross" not in state["plan_steps"]:
        _t(state).event("node", "verify", "cross_check not in plan -> routing straight to decide")
    return out


def _verify(state):
    t = _t(state)
    if not state.get("verify_enabled", True):
        t.event("guardrail", "verify", "verifier DISABLED (ablation run)")
        return {"retry": False, "verify_problems": []}
    reasons, status = list(state["review_reasons"]), {k: dict(v) for k, v in state["phase_status"].items()}
    calc_problems, ground = [], []
    dry_text = state["clause_text"].get("2.2", "")
    for r in state["rules"]:
        res = state["results"].get(r.phase_id)
        if res is None:
            continue
        calc_problems += V.check_result(r, state["phase_series"][r.phase_id], res)
        gp = V.grounding_problems(r, state["clause_text"].get(r.clause_id, ""), dry_text)
        if gp and status[r.phase_id].get("code") != "rule_not_grounded":
            ground += gp
            reasons.append(_reason("rule_not_grounded", "; ".join(gp), phase=r.phase_id, clauses=[r.clause_id]))
            status[r.phase_id] = {"status": "UNDETERMINED", "code": "rule_not_grounded"}
    attempts = state["compute_attempts"]
    if calc_problems and attempts < MAX_COMPUTE_ATTEMPTS:
        t.event("loop", "verify", f"verifier found {len(calc_problems)} problem(s) -> recompute (attempt {attempts + 1} of {MAX_COMPUTE_ATTEMPTS})",
                problems=calc_problems)
        return {"retry": True, "verify_problems": calc_problems, "review_reasons": reasons, "phase_status": status}
    if calc_problems:
        bad = sorted({p.split(":")[0] for p in calc_problems})
        for pid in bad:
            reasons.append(_reason("calc_mismatch", f"{pid}: calculator and independent verifier disagree after {attempts} attempt(s)",
                                   phase=pid, clauses=[]))
            status[pid] = {"status": "UNDETERMINED", "code": "calc_mismatch"}
        t.event("guardrail", "verify", f"mismatch persists after {attempts} attempts -> escalate {bad}", problems=calc_problems)
    else:
        t.event("node", "verify", f"all {len(state['results'])} computed phase(s) verified (independent recompute + invariants + rule grounding)")
    return {"retry": False, "verify_problems": calc_problems, "review_reasons": reasons, "phase_status": status}


def cross_check(state):
    """Node 9. Recompute each ready phase from the Secondary Station and compare the trigger outcome with the Primary's;
    if they differ, mark the phase UNDETERMINED (station_disagreement) instead of picking a side."""
    t = _t(state)
    notes, reasons, status = list(state["notes"]), list(state["review_reasons"]), {k: dict(v) for k, v in state["phase_status"].items()}
    sec = state.get("series_secondary") or {}
    sec_results = {}
    if not state.get("crosscheck_enabled", True) or not sec:
        notes.append("no cross-check against the Secondary Station was possible: outcome is uncorroborated")
        t.event("node", "cross_check", "skipped (no usable secondary series or disabled)")
        return {"notes": notes}
    for r in state["rules"]:
        res = state["results"].get(r.phase_id)
        if res is None or status[r.phase_id]["status"] != "READY":
            continue
        if not all(d in sec for d in r.window()):
            notes.append(f"{r.phase_id}: Secondary Station incomplete for this window; outcome uncorroborated")
            continue
        s_res = compute_phase(r, {d: sec[d] for d in r.window()})
        sec_results[r.phase_id] = s_res
        if s_res.triggered != res.triggered:
            reasons.append(_reason("station_disagreement",
                                   f"{r.phase_id}: Primary index {res.index} {res.index_unit} (triggered={res.triggered}) vs Secondary index {s_res.index} {s_res.index_unit} (triggered={s_res.triggered})",
                                   phase=r.phase_id, clauses=["4.1"]))
            status[r.phase_id] = {"status": "UNDETERMINED", "code": "station_disagreement"}
            t.event("guardrail", "cross_check", f"{r.phase_id}: stations disagree on the trigger -> refer to Claims Review Committee")
            continue
        tol = state.get("value_tolerance") or VALUE_TOLERANCE
        gap = _relative_gap(res.index, s_res.index)
        if gap <= tol:
            t.event("node", "cross_check", f"{r.phase_id}: Secondary Station agrees (index {s_res.index} {s_res.index_unit})")
            continue
        # same trigger outcome, but the index values differ by more than the tolerance
        detail = (f"{r.phase_id}: trigger outcomes agree but index values differ: Primary {res.index} {res.index_unit} vs "
                  f"Secondary {s_res.index} {s_res.index_unit} ({'infinite' if gap == D('Infinity') else f'{gap:.1%}'} apart, tolerance {tol:.0%})")
        vd = {"phase": r.phase_id, "primary": res.index, "secondary": s_res.index, "relative_gap": str(gap), "tolerance": tol}
        if state.get("strict_value_check", False):
            reasons.append(_reason("value_divergence", detail, phase=r.phase_id, clauses=["4.1"]))
            status[r.phase_id] = {"status": "UNDETERMINED", "code": "value_divergence"}
            t.event("guardrail", "cross_check", f"{r.phase_id}: value divergence -> refer (strict_value_check). " + detail, value_divergence=vd)
        else:
            reasons.append(_reason("value_divergence", detail, phase=r.phase_id, clauses=["4.1"], severity="info"))
            notes.append("INFO value_divergence (does not change the decision): " + detail)
            t.event("node", "cross_check", f"{r.phase_id}: Secondary Station agrees on the trigger; INFO value_divergence: "
                    f"{res.index} vs {s_res.index} {s_res.index_unit}", value_divergence=vd)
    return {"notes": notes, "review_reasons": reasons, "phase_status": status, "sec_results": sec_results}


def decide(state):
    """Node 10. Combine the phase statuses into TRIGGER_MET / TRIGGER_NOT_MET / CANNOT_DETERMINE and apply the overall
    cap (clause 5.1). Any undetermined phase or global problem gives CANNOT_DETERMINE and no payout figure."""
    t = _t(state)
    reasons = _blocking(state["review_reasons"])     # INFO notes (value_divergence) never influence the decision
    rules = state.get("rules") or []
    status, results = state.get("phase_status") or {}, state.get("results") or {}
    final = {}
    for r in rules:
        st = status.get(r.phase_id, {"status": "UNDETERMINED", "code": "not_evaluated"})
        if st["status"] != "READY" or r.phase_id not in results:
            final[r.phase_id] = {"status": "UNDETERMINED", "code": st.get("code") or "not_evaluated"}
        else:
            res = results[r.phase_id]
            final[r.phase_id] = {"status": "MET" if res.triggered else "NOT_MET", "index": res.index, "unit": res.index_unit,
                                 "payout": res.payout}
    global_issue = bool(reasons) and (state.get("halt") or any(x["phase"] is None for x in reasons))
    if global_issue or not rules or any(v["status"] == "UNDETERMINED" for v in final.values()):
        decision = "CANNOT_DETERMINE"
    elif any(v["status"] == "MET" for v in final.values()):
        decision = "TRIGGER_MET"
    else:
        decision = "TRIGGER_NOT_MET"
    paid = sum((v["payout"] for v in final.values() if v["status"] == "MET"), D(0))
    cap = state.get("overall_cap")
    determinate_payout = apply_overall_cap(paid, cap)
    total = determinate_payout if decision != "CANNOT_DETERMINE" else None
    t.event("decision", "decide", f"{decision}; phases { {k: v['status'] for k, v in final.items()} }; "
                                  f"payout INR {total if total is not None else 'not stated'}", reasons=[r['code'] for r in reasons],
            **({"info_reasons": [r['code'] for r in state['review_reasons'] if r.get('severity') == 'info']}
               if any(r.get('severity') == 'info' for r in state['review_reasons']) else {}))
    return {"decision": decision, "phase_final": final, "total_payout": total, "determinate_payout": determinate_payout}


def human_gate(state):
    t = _t(state)
    if state["decision"] == "CANNOT_DETERMINE":
        t.event("guardrail", "human_gate", "FLAGGED FOR HUMAN REVIEW: case referred for human review; no payout figure is stated")
        return {"status": "AWAITING_HUMAN_REVIEW"}
    t.event("node", "human_gate", "no escalation needed; assessment is advisory only (clause 5.2)")
    return {"status": "COMPLETE"}


def write_report(state):
    data, md = build_report(state)
    _t(state).event("node", "write_report", f"report built ({len(md.splitlines())} lines); trace {_t(state).run_id}")
    return {"report_data": data, "report_md": md}


# ------------------------------------------------------------------------------------------ graph
NODES = {
    "intake": intake, "retrieve_rules": retrieve_rules, "load_validate": load_validate, "make_plan": make_plan,
    "retrieve_support": retrieve_support, "remediate": remediate, "compute": compute, "verify": verify,
    "cross_check": cross_check, "decide": decide, "human_gate": human_gate, "write_report": write_report,
}


def _halt_or(nxt):
    return lambda s: "decide" if s.get("halt") else nxt


def _after_verify(s):
    """Retry the calculation if asked; else cross-check only if the plan lists 'cross'; else decide."""
    if s.get("retry"):
        return "compute"
    return "cross_check" if "cross" in s["plan_steps"] else "decide"


# name -> (router, possible targets). Static edges use a router returning a constant.
EDGES = {
    "intake": (_halt_or("retrieve_rules"), ["decide", "retrieve_rules"]),
    "retrieve_rules": (_halt_or("load_validate"), ["decide", "load_validate"]),
    "load_validate": (_halt_or("make_plan"), ["decide", "make_plan"]),
    "make_plan": (lambda s: "retrieve_support", ["retrieve_support"]),
    "retrieve_support": (_halt_or("remediate"), ["decide", "remediate"]),
    "remediate": (lambda s: "compute", ["compute"]),
    "compute": (lambda s: "verify", ["verify"]),
    "verify": (_after_verify, ["compute", "cross_check", "decide"]),
    "cross_check": (lambda s: "decide", ["decide"]),
    "decide": (lambda s: "human_gate", ["human_gate"]),
    "human_gate": (lambda s: "write_report", ["write_report"]),
    "write_report": (lambda s: "__end__", ["__end__"]),
}
START_NODE = "intake"


def _initial(policy_path, primary_csv, secondary_csv=None, tracer=None, calculator=None, llm=None,
             verify_enabled=True, crosscheck_enabled=True, plan_enabled=True, strict_value_check=False,
             value_tolerance=None) -> AgentState:
    return AgentState(policy_path=str(policy_path), primary_csv=str(primary_csv),
                      secondary_csv=str(secondary_csv) if secondary_csv else None,
                      tracer=tracer or Tracer(), calculator=calculator, llm=llm or NullLLM(),
                      verify_enabled=verify_enabled, crosscheck_enabled=crosscheck_enabled, plan_enabled=plan_enabled,
                      strict_value_check=strict_value_check, value_tolerance=value_tolerance, step_count=0)


def _force_escalation(state, limit):
    """Halt the run with a step_limit reason so that decide() abstains and the case goes to a human (both runners)."""
    state["review_reasons"] = list(state.get("review_reasons", [])) + [_reason("step_limit", f"more than {limit} steps")]
    state["halt"] = True


def run(policy_path, primary_csv, secondary_csv=None, **kw) -> AgentState:
    """Run the agent on the built-in runner (no extra dependencies)."""
    state = _initial(policy_path, primary_csv, secondary_csv, **kw)
    node = START_NODE
    allowed = set(AgentState.__annotations__)
    forced = False
    while node != "__end__":
        state["step_count"] += 1
        if state["step_count"] > MAX_STEPS and not forced and node not in ("decide", "human_gate", "write_report"):
            _t(state).event("guardrail", node, f"step limit {MAX_STEPS} exceeded -> force escalation")
            _force_escalation(state, MAX_STEPS)
            node, forced = "decide", True
            continue
        upd = NODES[node](state)
        bad = set(upd) - allowed
        assert not bad, f"node {node} returned undeclared state keys {bad}"
        state.update(upd)
        node = EDGES[node][0](state)
    _t(state).save()
    return state


def build_langgraph():
    """Same nodes and routers on LangGraph. Requires `pip install langgraph`."""
    from langgraph.graph import END, START, StateGraph
    g = StateGraph(AgentState)
    for name, fn in NODES.items():
        g.add_node(name, fn)
    g.add_edge(START, START_NODE)
    for name, (router, targets) in EDGES.items():
        mapping = {tg: (END if tg == "__end__" else tg) for tg in targets}
        g.add_conditional_edges(name, router, mapping)
    return g.compile()


def run_langgraph(policy_path, primary_csv, secondary_csv=None, recursion_limit=None, **kw) -> AgentState:
    """Run on LangGraph. If LangGraph's recursion limit is hit, escalate like the built-in runner instead of crashing."""
    from langgraph.errors import GraphRecursionError
    limit = recursion_limit or MAX_STEPS + 5
    app = build_langgraph()
    last = _initial(policy_path, primary_csv, secondary_csv, **kw)
    try:
        # stream the full state after every step, so the last good state is still ours if the limit is hit
        for last in app.stream(last, {"recursion_limit": limit}, stream_mode="values"):
            pass
    except GraphRecursionError:
        last = dict(last)
        _t(last).event("guardrail", "langgraph", f"recursion limit {limit} exceeded -> force escalation")
        _force_escalation(last, limit)
        for name in ("decide", "human_gate", "write_report"):   # same tail as the built-in runner's forced exit
            last.update(NODES[name](last))
    _t(last).save()
    return last
