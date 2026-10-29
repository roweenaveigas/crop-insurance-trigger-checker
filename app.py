"""Streamlit UI:  streamlit run app.py

Pick a demo case (or upload two station CSVs), run the agent, then inspect the decision, the calculation,
the policy clauses it relied on, and the full step-by-step trace. Cases the agent cannot determine are flagged and referred (status AWAITING_HUMAN_REVIEW; the run does not wait)
for a human reviewer, whose disposition is stored in an audit trail.
"""
import json
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from crop_trigger import agent, observability, records
from crop_trigger.engine import FaultyCalculator
from crop_trigger.llm import get_llm
from crop_trigger.tracing import Tracer

ROOT = Path(__file__).resolve().parent
POLICY = ROOT / "data" / "policy_sample.txt"
CASES = json.loads((ROOT / "data" / "cases.json").read_text())["cases"]

st.set_page_config(page_title="Crop-Insurance Trigger Checker", layout="wide")
st.title("Parametric Crop-Insurance Trigger Checker")
st.caption("Agentic decision support on a SAMPLE policy and SYNTHETIC weather data. Indicative only: not a claim decision.")

with st.sidebar:
    st.header("Input")
    mode = st.radio("Source", ["Demo case", "Upload CSVs"])
    primary = secondary = None
    fault = None
    expected = None
    if mode == "Demo case":
        labels = {f"{c['id']} - {c['description']}": c for c in CASES}
        case = labels[st.selectbox("Case", list(labels))]
        primary, secondary = ROOT / case["primary"], ROOT / case["secondary"]
        expected = case["expected"]["decision"]
        fault = case["fault"]["mode"] if case.get("fault") else None
        if fault:
            st.info(f"This case injects a **{fault}** calculator bug into P1 to demonstrate the verifier.")
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
    st.header("Agent options")
    verify_on = st.checkbox("Independent verifier", value=True)
    cross_on = st.checkbox("Secondary-station cross-check", value=True)
    llm = get_llm()
    st.caption(f"LLM layer: {llm.name} (set CTC_LLM=anthropic|ollama to enable; works offline without it)")
    run_clicked = st.button("Run agent", type="primary", disabled=primary is None)

if run_clicked:
    kw = {"tracer": Tracer(out_dir=ROOT / "traces"), "llm": llm, "verify_enabled": verify_on, "crosscheck_enabled": cross_on}
    if fault:
        kw["calculator"] = FaultyCalculator(fault, "P1")
    state = agent.run(POLICY, primary, secondary, **kw)
    rec = records.to_record(state)
    records.save_record(rec, ROOT / "runs")
    st.session_state["state"], st.session_state["record"], st.session_state["expected"] = state, rec, expected

if "state" not in st.session_state:
    st.info("Choose a case in the sidebar and press **Run agent**.")
    st.stop()

state, rec = st.session_state["state"], st.session_state["record"]
data = state["report_data"]
decision = data["decision"]
box = {"TRIGGER_MET": st.success, "TRIGGER_NOT_MET": st.info, "CANNOT_DETERMINE": st.warning}[decision]
box(f"**{decision.replace('_', ' ')}** - {data['summary']}")
c1, c2, c3 = st.columns(3)
c1.metric("Indicative payout (INR)", data["total_payout_inr"] if data["total_payout_inr"] is not None else "not stated")
c2.metric("Agent steps", len(state["tracer"].events))
c3.metric("Verify loops", state["tracer"].count("loop"))
if st.session_state.get("expected"):
    ok = st.session_state["expected"] == decision
    st.caption(("Matches" if ok else "DIFFERS FROM") + f" the labelled expectation for this demo case ({st.session_state['expected']}).")

tab_rep, tab_trace, tab_human, tab_eval = st.tabs(["Report", "Trace", "Human review", "Evaluation"])

with tab_rep:
    rows = [{"Phase": p["phase"], "Clause": p["clause"], "Result": p["status"], "Index": f"{p.get('index', 'n/a')} {p.get('unit', '')}".strip(),
             "Strike": p["strike"], "Payout (INR)": p.get("payout", "n/a")} for p in data["phases"]]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.markdown(state["report_md"])

with tab_trace:
    ev = state["tracer"].events
    m = observability.run_metrics(ev)
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
        st.dataframe(pd.DataFrame(observability.node_table(ev)), hide_index=True, width="stretch")

    st.subheader("Timeline")
    shown = st.multiselect("Show event kinds", list(observability.KINDS) + ["node"], default=list(observability.KINDS) + ["node"], key="trace_kinds")
    st.download_button("Download trace (JSONL)", observability.events_to_jsonl(ev), file_name=f"{state['tracer'].run_id}.jsonl",
                       mime="application/x-ndjson", key="trace_download")
    table = pd.DataFrame([{"step": e["step"], "node": e["node"], "kind": e["kind"], "flag": observability.flag_for(e), "summary": e["summary"]}
                          for e in ev if e["kind"] in shown])
    colour = {k: v[1] for k, v in observability.HIGHLIGHT.items()}
    if len(table):
        styled = table.style.apply(lambda r: [f"background-color: {colour.get(r['kind'], '')}; color: #000" if r["kind"] in colour else ""] * len(r), axis=1)
        st.dataframe(styled, hide_index=True, width="stretch")
    else:
        st.info("No events match the selected kinds.")
    st.caption("LOOP = verifier sent the calculation back for a retry; GUARDRAIL = a safety check fired (colour and the flag column say the same thing).")
    st.subheader("Retrieval attempts")
    for e in ev:
        if e["kind"] == "retrieval" and "retrieval" in shown:
            n = len(e.get("data", {}).get("attempts", []))
            with st.expander(f"step {e['step']} - need '{e['data']['need']}' - {n} attempt(s), {max(0, n - 1)} rewrite(s)"):
                st.dataframe(pd.DataFrame(observability.attempts_of(e)), hide_index=True, width="stretch")
    st.subheader("Event data")
    for e in ev:
        if e.get("data") and e["kind"] != "retrieval" and e["kind"] in shown:
            with st.expander(f"step {e['step']} - {e['kind']} - {e['node']}"):
                st.json(e["data"])

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

with tab_eval:
    for name, label in (("results.md", "Labelled cases"), ("stress_results.md", "Randomised stress test"), ("retrieval_results.md", "Retrieval")):
        p = ROOT / "eval" / name
        if p.exists():
            with st.expander(label, expanded=(name == "results.md")):
                st.markdown(p.read_text())
