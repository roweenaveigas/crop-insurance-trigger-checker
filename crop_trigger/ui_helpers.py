"""Pure helpers for the Streamlit UI: they turn a run's trace events into badges, a plain-language story,
feedback-loop comparisons, a flow-diagram description and small HTML cards.

Nothing here runs the agent or changes it. Everything is derived from the real trace events (`Tracer.event` dicts),
so the story can never describe something that did not happen. No Streamlit import, so it is unit-testable.
"""
from __future__ import annotations

import html
import re

from .observability import attempts_of

# capability badge -> CSS class (colours live in theme.py). Text is always shown on the badge, colour is only a second cue.
BADGES = {"PLANNING": "planning", "TOOL USE": "tooluse", "RAG": "rag", "FEEDBACK LOOP": "loop",
          "GUARDRAIL": "guardrail", "DECISION": "decision"}
# row flag (text) -> row background for the Trace table
ROW_FLAGS = {"LOOP": "#FFE0B2", "GUARDRAIL": "#FFCDD2", "RAG REWRITE": "#DCEDC8"}
VERDICTS = {  # decision -> (card class, plain-language label); the classes are styled in theme.py
    "TRIGGER_MET": ("met", "Trigger met"),
    "TRIGGER_NOT_MET": ("notmet", "Trigger not met"),
    "CANNOT_DETERMINE": ("review", "Cannot determine: a human must look"),
}
STATUS_CLASS = {"MET": "met", "NOT MET": "notmet", "UNDETERMINED": "review"}   # phase status text -> card class
PHASE_EMOJI = {"P1": "\U0001F331", "P2": "\U0001F33F", "P3": "\U0001F33C"}   # establishment, vegetative growth, flowering
DEMO_CASES = {"C01": "Clean season, nothing triggers", "M01": "Missing days, filled from the backup station",
              "F01": "Calculator bug, caught by the verifier", "X01": "Stations disagree, referred to a human"}
CATEGORY_NAMES = {"clean": "Clean data", "missing": "Missing readings", "units": "Unit problems",
                  "integrity": "Data integrity problems", "conflict": "Stations disagree", "fault": "Calculator bug (verifier demo)"}
TOOL_TITLES = {"rule_extractor": "Turned the policy clauses into machine-checkable rules",
               "load_weather": "Loaded and profiled the weather files",
               "remediate": "Repaired the data and checked each phase is ready to compute"}
# trace node name -> graph node name (the trace names some nodes after their tool)
_NODE_ALIAS = {"load_weather": "load_validate", "calculator": "compute", "rag": None, "rule_extractor": None}

_CALC = re.compile(r"attempt (\d+) (P\d): index (\S+) ?(\S*?); triggered=(\w+); payout INR ([\d.]+)")
_MISMATCH = re.compile(r"(P\d): index mismatch \(calculator (\S+) vs verifier (\S+)\)")


def esc(text) -> str:
    """HTML-escape any event text before it is placed in an HTML string."""
    return html.escape(str(text), quote=True)


def badge_for(event: dict) -> str | None:
    """Capability badge of one trace event (PLANNING, TOOL USE, RAG, FEEDBACK LOOP, GUARDRAIL, DECISION),
    or None for plain bookkeeping steps (intake, report writing) that the story leaves out."""
    kind, node, text = event["kind"], event["node"], event["summary"]
    by_kind = {"plan": "PLANNING", "tool": "TOOL USE", "retrieval": "RAG", "loop": "FEEDBACK LOOP",
               "guardrail": "GUARDRAIL", "decision": "DECISION"}
    if kind in by_kind:
        return by_kind[kind]
    if node == "remediate":
        return "PLANNING" if "skipped" in text else "TOOL USE"
    if node == "cross_check":
        return "TOOL USE"
    if node in ("verify", "human_gate"):
        return "GUARDRAIL"
    return None


def badge_html(label: str) -> str:
    """HTML badge (CSS class from theme.py) that carries its label as text (never colour alone)."""
    return f'<span class="badge {BADGES.get(label, "")}">{esc(label)}</span>'


def row_flag(event: dict) -> str:
    """Text flag for rows the Trace tab highlights: LOOP, GUARDRAIL or RAG REWRITE; otherwise an empty string."""
    if event["kind"] == "loop":
        return "LOOP"
    if event["kind"] == "guardrail":
        return "GUARDRAIL"
    if event["kind"] == "retrieval" and len(event.get("data", {}).get("attempts", [])) > 1:
        return "RAG REWRITE"
    return ""


def trace_rows(events) -> list[dict]:
    """One table row per event: step, node, kind, capability badge text, flag and summary."""
    return [{"step": e["step"], "node": e["node"], "kind": e["kind"], "capability": badge_for(e) or "pipeline",
             "flag": row_flag(e), "summary": e["summary"]} for e in events]


def retrieval_rows(event: dict) -> list[dict]:
    """Every attempt of one retrieval event as rows: need, attempt, first query or rewrite, query, grade, clause found."""
    need = event.get("data", {}).get("need", "?")
    rows = []
    for r, a in zip(attempts_of(event), event.get("data", {}).get("attempts", [])):
        rows.append({"need": need, "attempt": r["attempt"], "kind": r["kind"],
                     "grade": "passed" if a.get("passed") else "weak",
                     "clause found": ", ".join(a.get("passed", [])) or "none", "query": r["query"]})
    return rows


def calc_attempts(events) -> list[dict]:
    """Calculator results per attempt, parsed from the calculator events: [{attempt, phases: {P1: '91.0 mm'}}]."""
    out: dict[int, dict] = {}
    for e in events:
        m = _CALC.match(e["summary"]) if e["node"] == "calculator" else None
        if m:
            n, ph, idx, unit = int(m[1]), m[2], m[3], m[4]
            out.setdefault(n, {})[ph] = f"{idx} {unit}".strip()
    return [{"attempt": n, "phases": p} for n, p in sorted(out.items())]


def feedback_loops(events) -> list[dict]:
    """One entry per verify-to-compute loop that fired. For an index mismatch: phase, the first attempt's value,
    the verifier's value and the next attempt's value; otherwise the verifier's problem text only."""
    calcs = {c["attempt"]: c["phases"] for c in calc_attempts(events)}
    loops, n = [], 0
    for e in events:
        if e["kind"] != "loop":
            continue
        n += 1
        for prob in e.get("data", {}).get("problems", []) or [e["summary"]]:
            m = _MISMATCH.search(prob)
            entry = {"loop": n, "problem": prob}
            if m:
                ph, unit = m[1], ""
                first, second = calcs.get(n, {}).get(ph, ""), calcs.get(n + 1, {}).get(ph, "")
                unit = (first.split(" ", 1) + [""])[1]
                entry.update(phase=ph, attempt1=first or f"{m[2]} {unit}".strip(), verifier=f"{m[3]} {unit}".strip(), attempt2=second,
                             fixed=bool(second) and second.split(" ")[0] == m[3])
                entry["sentence"] = (f"{ph}: attempt 1 computed {entry['attempt1']}, the verifier says {entry['verifier']}, "
                                     f"attempt 2 computed {second or 'n/a'}" + (" (matches the verifier)" if entry["fixed"] else ""))
            else:
                entry["sentence"] = prob
            loops.append(entry)
    return loops


def _step(badge, title, detail="", events=(), rows=None, highlight=False, kind="") -> dict:
    return {"badge": badge, "title": title, "detail": detail, "steps": [e["step"] for e in events], "rows": rows or [],
            "highlight": highlight, "kind": kind}


def build_story(events) -> list[dict]:
    """Plain-language step list built only from the events. Each step: badge, title, detail, trace step numbers,
    optional table rows (every retrieval attempt) and a highlight flag (rewrite, loop, guardrail, abstention).
    Consecutive routine steps of the same kind are merged (6 first-try lookups, the 3 phases of one calculator attempt)."""
    story: list[dict] = []
    for e in events:
        b = badge_for(e)
        if b is None:
            continue
        kind, node, text, data = e["kind"], e["node"], e["summary"], e.get("data", {})
        prev = story[-1] if story else None
        if kind == "retrieval":
            rows = retrieval_rows(e)
            rewrote = len(rows) > 1
            found = rows[-1]["clause found"] if rows else "none"
            if rewrote:
                story.append(_step(b, f"Policy lookup for '{data['need']}' needed a rewrite: attempt 1 was weak, "
                                      f"attempt {len(rows)} found clause {found}", "", [e], rows, True, "rag_rewrite"))
            elif prev and prev["kind"] == "rag_ok":
                prev["rows"] += rows
                prev["steps"].append(e["step"])
                prev["title"] = f"Looked up {len(prev['rows'])} policy clauses; each was found on the first query"
            else:
                story.append(_step(b, "Looked up 1 policy clause; found on the first query", "", [e], rows, False, "rag_ok"))
            if found == "none" and rows:
                story[-1].update(highlight=True, title=f"Policy lookup for '{data['need']}' found nothing usable")
        elif node == "calculator":
            m = _CALC.match(text)
            att = int(m[1]) if m else 0
            if prev and prev["kind"] == f"calc{att}":
                prev["detail"] += "\n" + text
                prev["steps"].append(e["step"])
            else:
                story.append(_step(b, f"Calculator, attempt {att}", text, [e], kind=f"calc{att}"))
        elif node == "cross_check" and kind == "node":
            if prev and prev["kind"] == "cross":
                prev["detail"] += "\n" + text
                prev["steps"].append(e["step"])
            else:
                story.append(_step(b, "Compared with the secondary station", text, [e], kind="cross"))
        elif kind == "plan":
            story.append(_step(b, text.replace("plan: ", "Plan chosen from what the data looks like: "),
                               "\n".join(data.get("thoughts", [])), [e], kind="plan"))
        elif node == "remediate" and "skipped" in text:
            if prev and prev["kind"] == "skip":
                prev["detail"] += "\n" + text
                prev["steps"].append(e["step"])
            else:
                story.append(_step(b, "The plan skipped steps this case does not need", text, [e], kind="skip"))
        elif kind == "loop":
            story.append(_step(b, "The verifier disagreed, so the calculation was sent back: " + text.split("-> ")[-1],
                               "\n".join(data.get("problems", [])), [e], highlight=True, kind="loop"))
        elif node == "verify":
            story.append(_step(b, "The independent verifier agreed with the calculator", text, [e], kind="verify"))
        elif kind == "guardrail":
            story.append(_step(b, "Guardrail: " + text, "", [e], highlight=node != "rule_extractor", kind="guardrail"))
        elif kind == "decision":
            story.append(_step(b, "Decision: " + text.split(";")[0], text, [e], kind="decision"))
        elif node == "human_gate":
            story.append(_step(b, "Human gate: no referral needed", text, [e], kind="gate"))
        elif kind == "tool" or node == "remediate":
            key = f"tool_{node}"
            if prev and prev["kind"] == key:
                prev["detail"] += "\n" + text
                prev["steps"].append(e["step"])
            else:
                story.append(_step(b, TOOL_TITLES.get(node, f"Tool: {node}"), text, [e], kind=key))
        else:
            story.append(_step(b, text.split(":")[0], text, [e], kind="other"))
    return story


def nodes_ran(events) -> list[str]:
    """Graph nodes that ran, in execution order (consecutive repeats collapsed; a retry repeats compute and verify)."""
    seq: list[str] = []
    for e in events:
        n = _NODE_ALIAS.get(e["node"], e["node"])
        if n and (not seq or seq[-1] != n):
            seq.append(n)
    return seq


def flow_dot(events, nodes: dict, edges: dict) -> str:
    """Graphviz DOT for the agent graph. `nodes`/`edges` are the agent's own NODES and EDGES tables.
    Nodes that ran are filled and labelled 'ran'; others are grey and labelled 'not run'; edges taken are bold;
    the verify to compute retry edge is red and labelled RETRY (fired) when a loop happened."""
    seq = nodes_ran(events)
    ran, taken = set(seq), {(a, b) for a, b in zip(seq, seq[1:])}
    fired = any(e["kind"] == "loop" for e in events)
    out = ['digraph G {', 'rankdir=TB; bgcolor="transparent"; nodesep=0.25; ranksep=0.3;',
           'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=13, margin="0.12,0.06"];',
           'edge [fontname="Helvetica", fontsize=11, color="#777777"];']
    for n in nodes:
        label = f"{n}\\n{'ran' if n in ran else 'not run'}"
        fill, pen = ("#C8E6C9", "3") if n in ran else ("#EEEEEE", "1")
        out.append(f'"{n}" [label="{label}", fillcolor="{fill}", fontcolor="#111111", penwidth={pen}, '
                   f'color="{"#2E7D32" if n in ran else "#9E9E9E"}"];')
    out.append('"__end__" [label="end", shape=circle, style=filled, fillcolor="#EEEEEE", fontcolor="#111111"];')
    for a, (_, targets) in edges.items():
        for b in targets:
            if (a, b) == ("verify", "compute"):
                attrs = 'color="#C62828", fontcolor="#C62828", penwidth=3, label="RETRY (fired)"' if fired \
                    else 'color="#B0B0B0", style=dashed, label="retry (not fired)"'
            elif (a, b) in taken:
                attrs = 'color="#2E7D32", penwidth=3'
            else:
                attrs = 'color="#C8C8C8", style=dashed'
            out.append(f'"{a}" -> "{b}" [{attrs}];')
    out.append("}")
    return "\n".join(out)


def verdict_html(decision: str, summary: str, payout, flagged: bool, reasons=()) -> str:
    """The big verdict card: decision text (coloured and labelled), payout or reason, and the human-review line."""
    cls, label = VERDICTS.get(decision, ("", decision))
    pay = f"Indicative payout: INR {esc(payout)}" if payout is not None else "No payout figure is stated (see reasons below)"
    flag = ""
    if flagged:
        why = "; ".join(esc(r.get("detail", r.get("code", ""))) if isinstance(r, dict) else esc(r) for r in reasons)
        flag = (f'<div class="verdict-flag">FLAGGED FOR HUMAN REVIEW'
                f'{": " + why if why else ""}</div>')
    return (f'<div class="card verdict {cls}">'
            f'<div class="verdict-title">{esc(decision)}</div>'
            f'<div class="verdict-label">{esc(label)}</div>'
            f'<div class="verdict-pay">{pay}</div>'
            f'<div class="verdict-summary">{esc(summary)}</div>{flag}</div>')


def phase_card(p: dict, citations: dict) -> dict:
    """Display values for one phase card: name, status, index vs threshold, payout, cited clause and its first words."""
    unit = p.get("unit") or ("days" if "Dry Spell" in p.get("name", "") else "mm")
    determinate = "index" in p
    clause = p.get("clause", "")
    return {"title": f"{p['phase']} {p.get('name', '')}".strip(), "status": p["status"].replace("_", " "),
            "index": f"{p['index']} {unit}" if determinate else "not computed",
            "threshold": f"{p['strike']} {unit}", "payout": f"INR {p['payout']}" if p.get("payout") is not None else "not stated",
            "emoji": PHASE_EMOJI.get(p["phase"], ""), "why": p.get("why", ""), "clause": clause, "clause_text": (citations.get(clause, "")[:110] + "...") if citations.get(clause) else ""}


def phase_card_html(c: dict) -> str:
    """HTML for one phase card (status shown as text as well as colour)."""
    why = f'<div>Reason: {esc(c["why"].replace("_", " "))}</div>' if c["why"] else ""
    return (f'<div class="card phase {STATUS_CLASS.get(c["status"], "")}">'
            f'<div class="phase-title"><span class="phase-emoji">{c.get("emoji", "")}</span>{esc(c["title"])}</div>'
            f'<div class="phase-status">{esc(c["status"])}</div>'
            f'<div>Index: <b>{esc(c["index"])}</b> &nbsp; Threshold: <b>{esc(c["threshold"])}</b></div>'
            f'<div>Payout: <b>{esc(c["payout"])}</b></div>{why}'
            f'<div class="phase-cited">Cited: clause {esc(c["clause"])}</div></div>')


def case_groups(cases) -> dict[str, list[tuple[str, dict]]]:
    """Case picker structure: 'Demo cases' first (C01, M01, F01, X01 pinned), then one group per category.
    Each entry is (label, case); the label starts with the case id and uses plain language."""
    by_id = {c["id"]: c for c in cases}
    groups = {"Demo cases": [(f"{i} - {t}", by_id[i]) for i, t in DEMO_CASES.items() if i in by_id]}
    for cat, name in CATEGORY_NAMES.items():
        items = [(f"{c['id']} - {c['description']}", c) for c in cases if c["category"] == cat]
        if items:
            groups[name] = items
    return groups


def md_section(text: str, heading: str) -> str:
    """The body of the markdown section whose heading line contains `heading` (up to the next heading of the same
    or higher level); an empty string if there is no such heading."""
    lines, out, level, on = text.splitlines(), [], 0, False
    for ln in lines:
        m = re.match(r"(#+)\s+(.*)", ln)
        if m and not on and heading.lower() in m[2].lower():
            on, level = True, len(m[1])
            continue
        if on and m and len(m[1]) <= level:
            break
        if on:
            out.append(ln)
    return "\n".join(out).strip()


def first_table(text: str) -> str:
    """The first markdown table in `text` (consecutive lines starting with '|'), or an empty string."""
    out = []
    for ln in text.splitlines():
        if ln.startswith("|"):
            out.append(ln)
        elif out:
            break
    return "\n".join(out)
