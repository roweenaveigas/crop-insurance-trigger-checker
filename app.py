"""Streamlit UI:  streamlit run app.py

Pick a demo case (or upload two station CSVs), run the agent, then see at a glance how it decided: the verdict, the
step-by-step story built from the real trace (planning, tool use, RAG, feedback loop, guardrails), the flow diagram,
the full trace, a comparison of the four demo cases, the human-review form and the evaluation results.
Cases the agent cannot determine are flagged and referred (status AWAITING_HUMAN_REVIEW; the run does not wait)
for a human reviewer, whose disposition is stored in an audit trail. The UI only displays; it never changes the agent.
"""
import json
import tempfile
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from crop_trigger import agent, cli, observability, records, ui_helpers as ui
from crop_trigger.engine import FaultyCalculator
from crop_trigger.llm import get_llm
from crop_trigger.theme import apply_theme
from crop_trigger.tracing import Tracer

ROOT = Path(__file__).resolve().parent
POLICY = ROOT / "data" / "policy_sample.txt"
DEMO_IDS = list(ui.DEMO_CASES)

st.set_page_config(page_title="Crop-Insurance Trigger Checker", page_icon="🌾", layout="wide")
apply_theme()


@st.cache_data
def load_cases() -> list[dict]:
    """Read data/cases.json once per session (cached)."""
    return json.loads((ROOT / "data" / "cases.json").read_text())["cases"]


@st.cache_data
def read_eval(name: str, mtime: float) -> str:
    """Read one eval/*.md file (cached by modification time); empty string if it does not exist."""
    p = ROOT / "eval" / name
    return p.read_text(encoding="utf8") if p.exists() else ""


def eval_text(name: str) -> str:
    """Text of eval/<name> without recomputing anything."""
    p = ROOT / "eval" / name
    return read_eval(name, p.stat().st_mtime if p.exists() else 0.0)


def run_selected(case, primary, secondary, verify_on, cross_on, llm):
    """Run the agent on the chosen input, save trace and record as before, and remember the result in session_state.
    Shows a friendly message instead of a traceback if anything goes wrong."""
    kw = {"tracer": Tracer(out_dir=ROOT / "traces"), "llm": llm, "verify_enabled": verify_on, "crosscheck_enabled": cross_on}
    if case and case.get("fault"):
        kw["calculator"] = FaultyCalculator(case["fault"]["mode"], "P1")
    try:
        t0 = time.perf_counter()
        state = agent.run(POLICY, primary, secondary, **kw)
        rec = records.to_record(state)
        records.save_record(rec, ROOT / "runs")
    except FileNotFoundError as exc:
        st.error(f"A required file was not found ({Path(str(exc.filename)).name}). Check the case files under data/.")
        return
    except Exception as exc:  # noqa: BLE001 - the UI must not show a raw traceback
        st.error(f"The run could not be completed ({type(exc).__name__}: {exc}). Try another case or check the uploaded CSVs "
                 "(columns: date, rainfall, unit, station).")
        return
    st.session_state.update(state=state, record=rec, expected=case["expected"]["decision"] if case else None,
                            case_label=f"{case['id']} - {case['description']}" if case else "uploaded files",
                            run_seconds=round(time.perf_counter() - t0, 3))


def demo_rows() -> list[dict]:
    """Run the four demo cases exactly as `python -m crop_trigger.cli --compare C01 M01 F01 X01` does and return one row each."""
    rows = []
    for cid in DEMO_IDS:
        m = observability.run_metrics(cli._run_case(cid)["tracer"].events)
        rows.append({"case": cid, "plan": m["plan"], "steps": m["steps"], "tool_calls": m["tool_calls"],
                     "rewrites": m["retrieval_rewrites"], "loops": m["verify_loops"], "decision": m["decision"]})
    return rows


# ------------------------------------------------------------------------------------------ header
st.title("Parametric Crop-Insurance Trigger Checker")
st.markdown("An agent that decides whether weather evidence meets a crop-insurance trigger, and when it must hand the case to a human instead.")
st.markdown('<span class="notice">Synthetic data, fictional policy. Indicative only, not a claim decision.</span>', unsafe_allow_html=True)

try:
    CASES = load_cases()
except (OSError, ValueError):
    st.error("data/cases.json is missing or unreadable. Run `python data/generate_data.py` from the project folder, then reload.")
    st.stop()

# ------------------------------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Input")
    mode = st.radio("Source", ["Demo case", "Upload CSVs"], key="source")
    primary = secondary = case = None
    if mode == "Demo case":
        groups = ui.case_groups(CASES)
        group = st.selectbox("Case group", list(groups), key="case_group")
        labels = dict(groups[group])
        case = labels[st.selectbox("Case", list(labels), key="case_pick")]
        primary, secondary = ROOT / case["primary"], ROOT / case["secondary"]
        if case.get("fault"):
            st.info(f"This case injects a **{case['fault']['mode']}** calculator bug into P1 to demonstrate the verifier.")
    else:
        up_p = st.file_uploader("Primary station CSV (RWS-A)", type="csv")
        up_s = st.file_uploader("Secondary station CSV (RWS-B, optional)", type="csv")
        st.caption("Columns: date (YYYY-MM-DD), rainfall, unit, station")
        tmp = Path(tempfile.mkdtemp())
        if up_p:
            primary = tmp / "primary.csv"
            primary.write_bytes(up_p.getvalue())
        if up_s:
            secondary = tmp / "secondary.csv"
            secondary.write_bytes(up_s.getvalue())
    llm = get_llm()
    run_clicked = st.button("Run agent", type="primary", disabled=primary is None, key="run_btn", width="stretch")
    run_all_clicked = st.button("Run all 4 demo cases", key="run_all_btn", width="stretch")
    with st.expander("Agent options"):
        verify_on = st.checkbox("Independent verifier", value=True)
        cross_on = st.checkbox("Secondary-station cross-check", value=True)
        st.caption(f"LLM layer: {llm.name} (off by default; set CTC_LLM=anthropic|ollama to enable; everything works offline)")

if run_clicked:
    run_selected(case, primary, secondary, verify_on, cross_on, llm)
if run_all_clicked:
    with st.spinner("Running C01, M01, F01 and X01..."):
        st.session_state["compare_rows"] = demo_rows()
    if "state" not in st.session_state or case is None or case["id"] not in DEMO_IDS:
        pick = next(c for c in CASES if c["id"] == (case["id"] if case and case["id"] in DEMO_IDS else "F01"))
        run_selected(pick, ROOT / pick["primary"], ROOT / pick["secondary"], verify_on, cross_on, llm)

if "state" not in st.session_state:
    st.info("Choose a case in the sidebar and press **Run agent**, or **Run all 4 demo cases**. Start with F01 to see the feedback loop.")
    st.stop()

# ------------------------------------------------------------------------------------------ verdict
state, rec = st.session_state["state"], st.session_state["record"]
data, events = state["report_data"], state["tracer"].events
decision = data["decision"]
flagged = rec["status"] == "AWAITING_HUMAN_REVIEW"
st.caption(f"Showing: {st.session_state.get('case_label', '')}  |  run {state['tracer'].run_id}  |  "
           f"agent run took {st.session_state.get('run_seconds', 'n/a')} s")
st.markdown(ui.verdict_html(decision, data["summary"], data["total_payout_inr"], flagged, data["review_reasons"]), unsafe_allow_html=True)
if st.session_state.get("expected"):
    ok = st.session_state["expected"] == decision
    st.caption(("Matches" if ok else "DIFFERS FROM") + f" the labelled expectation for this demo case ({st.session_state['expected']}).")
cards = [ui.phase_card(p, data["citations"]) for p in data["phases"]]
for col, c in zip(st.columns(len(cards)), cards):
    col.markdown(ui.phase_card_html(c), unsafe_allow_html=True)
with st.expander("Cited policy clauses (text the agent retrieved)"):
    for c in cards:
        if c["clause"] in data["citations"]:
            st.markdown(f"**Clause {c['clause']}** ({c['title'].split(' ')[0]}): {data['citations'][c['clause']]}")

tab_res, tab_how, tab_trace, tab_cmp, tab_human, tab_eval = st.tabs(
    ["Result", "How it decided", "Trace", "Compare cases", "Human review", "Evaluation"])

# ------------------------------------------------------------------------------------------ result
with tab_res:
    rows = [{"Phase": p["phase"], "Clause": p["clause"], "Result": p["status"], "Index": f"{p.get('index', 'n/a')} {p.get('unit', '')}".strip(),
             "Strike": p["strike"], "Payout (INR)": p.get("payout", "n/a")} for p in data["phases"]]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.markdown(state["report_md"])

# ------------------------------------------------------------------------------------------ how it decided
with tab_how:
    story = ui.build_story(events)
    loops = ui.feedback_loops(events)
    st.subheader("Feedback loop")
    if loops:
        for fb in loops:
            if "attempt1" in fb:
                a, v, b = st.columns(3)
                a.metric(f"{fb['phase']}: attempt 1 (calculator)", fb["attempt1"])
                v.metric("Verifier says", fb["verifier"])
                b.metric(f"{fb['phase']}: attempt 2 (recompute)", fb["attempt2"] or "n/a")
            st.markdown(ui.badge_html("FEEDBACK LOOP") + " " + ui.esc(fb["sentence"]), unsafe_allow_html=True)
    else:
        st.info("No feedback loop was needed in this case.")
    left, right = st.columns([3, 2])
    with left:
        st.subheader("The story, step by step")
        st.caption(f"{len(story)} steps shown, built only from the {len(events)} trace events. Step numbers match the Trace tab.")
        for s in story:
            span = f"trace step {s['steps'][0]}" if len(s["steps"]) == 1 else f"trace steps {s['steps'][0]}-{s['steps'][-1]}"
            detail = f'<div class="story-detail">{ui.esc(s["detail"]).replace(chr(10), "<br>")}</div>' if s["detail"] else ""
            st.markdown(f'<div class="story-step {"story-hl" if s["highlight"] else ""}">{ui.badge_html(s["badge"])} '
                        f'<b>{ui.esc(s["title"])}</b> <span style="opacity:.7">({span})</span>{detail}</div>', unsafe_allow_html=True)
            if s["rows"]:
                with st.expander("Every retrieval attempt (query, grade, rewrite, clause found)", expanded=s["highlight"]):
                    st.dataframe(pd.DataFrame(s["rows"]), hide_index=True, width="stretch")
    with right:
        st.subheader("Agent flow")
        st.graphviz_chart(ui.flow_dot(events, agent.NODES, agent.EDGES), width="stretch")
        st.caption("Green and labelled 'ran' = the node ran in this case; grey 'not run' = it did not. "
                   "Bold green edges were taken. The red RETRY edge appears only when the verifier sent the calculation back.")
        arch = ROOT / "docs" / "architecture.png"
        if arch.exists():
            with st.expander("Architecture diagram"):
                st.image(str(arch))

# ------------------------------------------------------------------------------------------ trace
with tab_trace:
    m = observability.run_metrics(events)
    st.caption(f"Run {state['tracer'].run_id}. Saved to traces/ as JSONL.")
    st.subheader("Run metrics")
    r1 = st.columns(4)
    r1[0].metric("Steps", m["steps"])
    r1[1].metric("Tool calls", m["tool_calls"])
    r1[2].metric("Retrieval rewrites", m["retrieval_rewrites"])
    r1[3].metric("Verify loops", m["verify_loops"])
    r2 = st.columns(3)
    r2[0].metric("Wall-clock (s)", m["seconds"])
    r2[1].metric("Final decision", m["decision"])
    r2[2].metric("Review reasons", len(m["review_reasons"]))
    st.write("Plan: " + m["plan"] + ".  Review reasons: " + (", ".join(m["review_reasons"]) or "none") + ".")
    with st.expander("Per-node summary"):
        st.dataframe(pd.DataFrame(observability.node_table(events)), hide_index=True, width="stretch")

    st.subheader("Timeline")
    shown = st.multiselect("Show event kinds", list(observability.KINDS) + ["node"], default=list(observability.KINDS) + ["node"], key="trace_kinds")
    st.download_button("Download trace (JSONL)", observability.events_to_jsonl(events), file_name=f"{state['tracer'].run_id}.jsonl",
                       mime="application/x-ndjson", key="trace_download")
    table = pd.DataFrame([r for r in ui.trace_rows(events) if r["kind"] in shown])
    if len(table):
        styled = table.style.apply(lambda r: [f"background-color: {ui.ROW_FLAGS[r['flag']]}; color: #000" if r["flag"] else ""] * len(r), axis=1)
        st.dataframe(styled, hide_index=True, width="stretch", height=min(36 * (len(table) + 1) + 4, 640),
                     column_config={"step": st.column_config.NumberColumn("step", width="small"),
                                    "flag": st.column_config.TextColumn("flag", width="medium"),
                                    "capability": st.column_config.TextColumn("capability", width="small"),
                                    "summary": st.column_config.TextColumn("summary", width="large")})
    else:
        st.info("No events match the selected kinds.")
    st.caption("LOOP = verifier sent the calculation back; GUARDRAIL = a safety check fired; RAG REWRITE = a policy lookup "
               "needed a rewritten query. Colour and the flag column say the same thing.")
    st.subheader("Retrieval attempts")
    for e in events:
        if e["kind"] == "retrieval" and "retrieval" in shown:
            n = len(e.get("data", {}).get("attempts", []))
            with st.expander(f"step {e['step']} - need '{e['data']['need']}' - {n} attempt(s), {max(0, n - 1)} rewrite(s)"):
                st.dataframe(pd.DataFrame(observability.attempts_of(e)), hide_index=True, width="stretch")
    st.subheader("Event data")
    for e in events:
        if e.get("data") and e["kind"] != "retrieval" and e["kind"] in shown:
            with st.expander(f"step {e['step']} - {e['kind']} - {e['node']}"):
                st.json(e["data"])

# ------------------------------------------------------------------------------------------ compare
with tab_cmp:
    st.caption("Same numbers as `python -m crop_trigger.cli --compare C01 M01 F01 X01`.")
    if st.button("Run the 4 demo cases", key="compare_btn"):
        st.session_state["compare_rows"] = demo_rows()
    if "compare_rows" in st.session_state:
        df = pd.DataFrame(st.session_state["compare_rows"])
        df["note"] = [("feedback loop fired" if r["loops"] else "abstained, referred to a human" if r["decision"] == "CANNOT_DETERMINE"
                       else "retrieval rewrite" if r["rewrites"] > 1 else "") for r in st.session_state["compare_rows"]]
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption("The plan differs per case. F01 has one verify loop; X01 abstains (CANNOT_DETERMINE) instead of picking a station.")
    else:
        st.info("Press the button (or **Run all 4 demo cases** in the sidebar) to fill the table.")

# ------------------------------------------------------------------------------------------ human review
with tab_human:
    if rec["status"] == "AWAITING_HUMAN_REVIEW":
        st.warning("This case was flagged for human review. The agent stated no payout figure.")
        with st.form("review"):
            who = st.text_input("Reviewer name")
            action = st.selectbox("Disposition", list(records.REVIEW_ACTIONS))
            note = st.text_area("Note (required)")
            if st.form_submit_button("Record review"):
                try:
                    st.session_state["record"] = records.apply_human_review(rec, who, action, note)
                    records.save_record(st.session_state["record"], ROOT / "runs")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    else:
        st.write(f"Status: **{rec['status']}**")
    if rec["human_review"]:
        st.subheader("Audit trail")
        st.dataframe(pd.DataFrame(rec["human_review"]), hide_index=True, width="stretch")

# ------------------------------------------------------------------------------------------ evaluation
with tab_eval:
    st.caption("Read from the saved eval/*.md files; nothing is recomputed here. Re-run the scripts in eval/ to refresh them.")
    shown_any = False
    for title, fname, heading, only_table in (
            ("Headline: naive baseline vs no verifier vs no cross-check vs full agent (38 labelled cases)", "results.md", "Headline comparison", True),
            ("Planning ablation: planned vs fixed pipeline", "plan_ablation_results.md", "", True),
            ("Abstention: coverage and safety (38 labelled cases)", "abstention_results.md", "38 labelled cases", True)):
        text = eval_text(fname)
        body = ui.md_section(text, heading) if heading else text
        body = ui.first_table(body) if only_table else body
        if body:
            shown_any = True
            st.subheader(title)
            st.markdown(body)
            st.caption(f"Source: eval/{fname}")
    if not shown_any:
        st.info("No eval results found in eval/. Run `python eval/run_eval.py` first.")
    for name, label in (("results.md", "Labelled cases (full)"), ("stress_results.md", "Randomised stress test"), ("retrieval_results.md", "Retrieval"),
                        ("plan_ablation_results.md", "Planning ablation (full)"), ("abstention_results.md", "Abstention (full)")):
        if eval_text(name):
            with st.expander(label):
                st.markdown(eval_text(name))
