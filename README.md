# Parametric Crop-Insurance Trigger Checker

## Run in 5 commands

```bash
git clone https://github.com/roweenaveigas/crop-insurance-trigger-checker.git && cd crop-insurance-trigger-checker
python -m venv .venv && .venv/Scripts/activate        # Windows (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
python -m unittest discover -s tests -t .             # 85 tests
python -m crop_trigger.cli --case F01 --trace         # live demo; then: streamlit run app.py
```

## Review 3 checklist

| Item | Files | Exact command |
|---|---|---|
| Tool use | `crop_trigger/tools.py`, `engine.py`, `rules.py` | `python -m crop_trigger.cli --case C01 --trace` (look for `tool` events) |
| RAG | `crop_trigger/rag.py` (BM25, grade, rewrite, abstain) | `python -m crop_trigger.cli --case M01 --trace` (retrieval rewrite, attempt 1 weak, attempt 2 clause 4.1) |
| Planning | `crop_trigger/agent.py` (`make_plan`) | `python -m crop_trigger.cli --compare C01 M01 F01 X01`; `python eval/plan_ablation.py` |
| Feedback loop | `agent.py` verify to compute retry, `verify.py` | `python -m crop_trigger.cli --case F01 --trace` (calculator 91.0, verifier 90.0, recompute) |
| Observability | `tracing.py`, `observability.py`, `app.py` Trace tab | `python -m crop_trigger.cli --trace-summary X01`; `streamlit run app.py` then Trace tab |

Traces are written to `traces/` at run time (not committed); regenerate them with the commands above.

An agentic decision-support system for weather-index crop insurance (Agentic AI mini-project, 26CD7PEAAI).
For a policy and two weather-station files it works out **whether the evidence satisfies the policy's weather trigger,
and if not, exactly why a human has to look**. It explains the clause, the data, the arithmetic and every assumption.

> Sample policy and **synthetic** data only. The output is an indicative assessment, never a claim decision (policy clause 5.2).

## The one decision

`TRIGGER_MET` / `TRIGGER_NOT_MET` / `CANNOT_DETERMINE` (abstain and escalate), per phase and overall.
The agent's value is not the arithmetic (that is deterministic code). It is deciding **whether the evidence is good enough to do the arithmetic**.

## Quick start

Run all commands from the project root folder.

```bash
pip install -r requirements.txt          # pandas + pydantic are enough to run everything except the UI / LangGraph
python data/generate_data.py             # regenerates data/cases/*.csv and data/cases.json (already included)
python -m crop_trigger.cli --case M01 --trace      # missing data: agent fills gaps from the secondary station
python -m crop_trigger.cli --case F01 --trace      # injected calculator bug: verifier catches it, retry fixes it
python -m crop_trigger.cli --case X01 --trace      # stations disagree: refuses to pick a side, refers to a human
streamlit run app.py                     # UI: report, trace, human-review form, evaluation tabs
python -m unittest discover -s tests -t .          # or: pytest
python eval/run_eval.py                  # 38 labelled cases, agent vs ablations vs naive baseline
python eval/stress_eval.py               # 500 randomised cases
python eval/retrieval_eval.py            # retrieval loop vs single-shot lookup
python eval/mutation_check.py            # plant bugs, confirm the stress test notices
```

Optional LLM layer: `CTC_LLM=anthropic ANTHROPIC_API_KEY=... ` or `CTC_LLM=ollama`. Everything runs offline without it.
LangGraph: `python -m crop_trigger.cli --case M01 --engine langgraph` (after `pip install langgraph`).

## How it maps to the course checklist

| Concept (tier) | Where | Evidence |
|---|---|---|
| Tool use (M) | `tools.py` (CSV load/profile/series), `engine.py` (calculator), `rules.py` (clause to rule) | `kind=tool` events in the trace |
| Agentic RAG (M) | `rag.py`: BM25, **grade** against must-have phrases, **rewrite**, retry, **abstain** | `eval/retrieval_eval.py`; `kind=retrieval` events with every attempt |
| Planning and reasoning loop (M) | `agent.py` `make_plan` chooses steps from what the data looks like and the plan drives the route: `remediate` converts units / fills gaps only if the plan lists `units` / `missing`, and `verify` goes to `cross_check` only if it lists `cross`, else straight to `decide`; `verify` to `compute` retry loop | `kind=plan` and `kind=loop` events; tests `test_planning_is_data_driven`, `PlanDrivesRoute`, `test_transient_fault...` |
| Observability / tracing (M) | `tracing.py`: every run saved as JSONL in `traces/` | `python -m crop_trigger.cli --case F01 --trace` |
| Evaluation (M) | `eval/`: labelled cases, ablations, baseline, stress test, mutation check | `eval/*.md` |
| Human-in-the-loop and guardrails (B) | `human_gate`, `records.py` audit trail; bounded loops (2 compute attempts, 40 steps; on LangGraph the recursion limit also escalates with reason `step_limit`); grounding check; LLM-output guard (an unreachable or rambling LLM is logged and the parser kept; only valid JSON that disagrees halts) | `tests/test_agent.py` |
| Memory / state (B) | explicit run state (`AgentState`); persisted records in `runs/` | `records.py` |
| Experimentation (B) | agent vs naive baseline, and verifier / cross-check ablations | `eval/results.md` |
| Multi-agent (B) | not claimed. The verifier is a separate component, not a conversing agent | |

## Results (what the scripts actually printed)

| | Naive baseline | Agent |
|---|---|---|
| 38 labelled cases: decision accuracy | 65.8% | 100% |
| 500 random cases: fully correct | 46.8% (decision only) | 100% (500/500) |
| Answers when it should abstain | 100% of such cases | 0% |
| Retrieval, in-scope questions | 55% (single shot) | 100% |

Ablations on the 38 cases: without the verifier accuracy falls to 97.4% (the injected faults get through); without the cross-check it falls to 92.1% (station conflicts get through).

**Read these numbers honestly.**
- The 38 cases were written by the same person who built the agent, around the failure modes it was built for. 100% there means "implements the spec", not "generalises".
- The stress test is independent code derived from the policy text and was built so that it *can* fail (see `mutation_check.py`: 4 of 4 planted bugs caught, each on 200 randomised cases). Still, it shares my reading of the policy, so a misreading of the policy would be invisible to both.
- The retrieval grader's must-have phrases were written by me with the policy in view, which favours it over the single-shot baseline. The question set is small (25).
- The data is synthetic and the policy fictional. Nothing here says how it would do on a real policy PDF; rule extraction is regex-based and is written for this clause format.
- Rule extraction from a *different* policy layout would need new patterns (or the optional LLM extractor wired in as the primary). That is the main piece of future work.

## Not verified in the build environment (test these first on your laptop)

The build workspace could not install packages, so these were written but never executed there. Status after running them on a laptop (Python 3.14.4, langgraph 1.2.17, streamlit 1.66.1, pandas 3.1.0, pydantic 2.14.1):
1. The LangGraph path (`build_langgraph`, `run_langgraph`): **verified**. `tests.test_langgraph_parity` passes (same decisions, payouts and phase statuses as the built-in runner on every case in cases.json) and `--engine langgraph` runs.
2. `app.py` (Streamlit): **verified headlessly** with `streamlit.testing.v1.AppTest` for C02, M01, U01, X01, F01 and F02 (no exceptions; all four tabs render; the human-review form rejects empty input and writes the audit trail to `runs/`), and the server starts and serves. Not checked by eye in a browser. The deprecated `use_container_width` was replaced by `width="stretch"`.
3. The Ollama client in `llm.py`: **verified** against a live local Ollama (`CTC_MODEL=qwen2.5:3b`; the default `llama3.1` must be pulled or overridden). The Anthropic client is **still untested** (no API key was available). The surrounding logic is also unit-tested with fake LLMs (disagreement, garbage output, network failure, invented numbers).

## Data sources and tool plan

Data (all synthetic, regenerated by `python data/generate_data.py`):
- `data/policy_sample.txt`: one fictional policy, WI-SAMPLE-001, 11 clauses.
- Two station files per case (`data/cases/<ID>_primary.csv` for RWS-A, `<ID>_secondary.csv` for RWS-B).
- 38 generated labelled cases in `data/cases.json` (clean, missing, units, integrity, conflict, fault) with the expected answer planted by construction.

Tools in `crop_trigger/` (the agent chooses and orders them; none of the arithmetic is done by an LLM):
- `rag.py`: policy clause retrieval (BM25, grade, rewrite, abstain).
- `rules.py`: turns clause text into rules (regex; the optional LLM only cross-checks).
- `tools.py`: load, profile and clean the station CSVs.
- `engine.py`: Decimal index, trigger and payout calculator.
- `verify.py`: independent recompute and grounding check.
- `report.py`, `records.py`, `tracing.py`: report, audit trail, trace.

## Layout

```
crop_trigger/   engine.py (Decimal calculator)  verify.py (independent recompute + grounding)  rag.py  rules.py
                tools.py  agent.py (nodes, routers, runners)  report.py  records.py  tracing.py  observability.py  llm.py  baseline.py  cli.py
data/           policy_sample.txt  generate_data.py  cases.json  cases/*.csv
eval/           run_eval.py  stress_eval.py  retrieval_eval.py  mutation_check.py  *_results.md
                plan_ablation.py  abstention_eval.py  value_check.py  heldout_questions_TEMPLATE.csv   (Review 3)
tests/          engine, rag/rules, agent, langgraph parity
docs/           architecture.png  make_diagram.py
traces/ runs/   written at run time
```

## Review demo script (about 5 minutes)

1. `--case C01 --trace`: clean run; point at plan, retrieval, calculator, verify, decision.
2. `--case M01 --trace`: the plan now includes the missing-data step; note the retrieval **rewrite** (attempt 1 weak, attempt 2 finds clause 4.1), the fill from RWS-B, and that a naive script would have wrongly triggered.
3. `--case F01 --trace`: the `loop` event; calculator said 91.0, verifier said 90.0, recompute fixed it.
4. `--case X01`: stations disagree; no payout figure; flagged and referred (status AWAITING_HUMAN_REVIEW; the run does not wait). In the UI, record a review. A true pause (a LangGraph interrupt that waits for the reviewer and resumes) is future work.
5. Show `eval/results.md` and the ablation table.

## Review 3 demo runbook (8 minutes max)

Run everything from the project root. Times are measured on the build laptop; key lines are what the commands really printed.

| # | Minutes | Command | Say / show | Key line to look for |
|---|---|---|---|---|
| 1 | 1 | `python -m crop_trigger.cli --compare C01 M01 F01 X01` | one row per case: the plan differs per case, F01 has a loop, X01 abstains | `M01 | missing -> cross -> compute -> verify`, `F01 ... | 1 | TRIGGER_MET`, `X01 ... | CANNOT_DETERMINE` |
| 2 | 1 | `python -m crop_trigger.cli --case M01 --trace` | plan, then the retrieval rewrite section at the end | `## Retrieval rewrites (attempt detail)`, `attempt 1: weak ...`, `attempt 2: matched clause 4.1`, `P1: filled 2 missing day(s) from RWS-B` |
| 3 | 1 | `python -m crop_trigger.cli --case F01 --trace` | the verify-to-compute loop | `loop | verify | verifier found 1 problem(s) -> recompute (attempt 2 of 2)`, index 91.0 then 90.0 |
| 4 | 1 | `python -m crop_trigger.cli --case X01 --trace` then `python -m crop_trigger.cli --trace-summary X01` | refuses to pick a side; per-node table | `FLAGGED FOR HUMAN REVIEW: case referred for human review; no payout figure is stated` |
| 5 | 2 | `streamlit run app.py`, pick F01, **Run agent**, open the **Trace** tab | run metrics panel; filter kinds to `loop` (one orange row labelled LOOP); expand a retrieval step to see every attempt; **Download trace (JSONL)** | metrics: Verify loops 1, Retrieval rewrites 1, Final decision TRIGGER_MET |
| 6 | 1 | `python eval/plan_ablation.py` (1 s) | planning matters for cost, not accuracy | decision accuracy 100.0% vs 100.0%; tool/retrieval calls 13.3 vs 14.9 |
| 7 | 1 | `python eval/abstention_eval.py` (about 25 s; or open `eval/abstention_results.md`) | the agent trades coverage for safety | stress cases: full agent coverage 48.8%, selective accuracy 100.0%, unsafe-answer rate 0.0%; baseline 100% coverage, 29.2% selective accuracy |

Also available: `python eval/value_check.py` (value-level cross-check, about 20 s) and `python -m unittest discover -s tests -t .`.

New in Review 3 (all behind flags or in new files; the Review 2 default behaviour and results are unchanged):
- `--compare`, `--trace-summary`, the UI Trace tab, `crop_trigger/observability.py`; trace events now carry an optional wall-clock `ts`.
- `plan_enabled=False` ablation (`eval/plan_ablation.py`), `strict_value_check=True` and the INFO `value_divergence` note (`eval/value_check.py`), selective-prediction metrics (`eval/abstention_eval.py`).
- Held-out retrieval scaffold: copy `eval/heldout_questions_TEMPLATE.csv` to `eval/heldout_questions.csv` and have a **teammate** write the questions; `python eval/retrieval_eval.py` then adds a separate held-out section (`eval/heldout_retrieval_results.md`). Until then it prints a one-line note.
- See `REVIEW3_STATUS.md` for the tables, honest limits and what is left for Review 4.

## Contribution table (fill in for your team)

| Member | Owns |
|---|---|
| | |
