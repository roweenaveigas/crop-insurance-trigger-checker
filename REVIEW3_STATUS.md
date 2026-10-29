# Review 3 status (Prototype and Observability)

Everything new is behind a flag, a new function or a new file. Review 2 default behaviour and eval numbers are unchanged (proof in section 3).
All numbers below are copied from the scripts' real output, not typed by hand.

## 1. What was added

| Task | What | Where |
|---|---|---|
| 1 Observability | Trace tab: timeline table with kind filter, LOOP and GUARDRAIL rows highlighted by colour **and** a text label, retrieval attempts expandable (query, grade, rewrite), JSONL download, per-run metrics panel (steps, tool calls, rewrites, verify loops, wall-clock, decision, review reasons); `--trace-summary`; `--compare`; optional wall-clock `ts` on trace events | `app.py`, `crop_trigger/observability.py`, `crop_trigger/cli.py`, `crop_trigger/tracing.py` |
| 2 Planning ablation | `plan_enabled=False` runs the fixed full pipeline; variant `agent_no_plan` | `crop_trigger/agent.py`, `eval/run_eval.py`, `eval/plan_ablation.py` |
| 3 Abstention metrics | coverage, selective accuracy, unsafe-answer, over-abstention, escalation rate by category | `eval/abstention_eval.py` |
| 4 Value-level cross-check | INFO `value_divergence` note (tolerance `VALUE_TOLERANCE` = 10% in `agent.py`, optional `value_tolerance` override); `strict_value_check=True` escalates; variant `agent_strict_values` | `crop_trigger/agent.py`, `crop_trigger/report.py`, `eval/value_check.py` |
| 5 Held-out retrieval scaffold | template CSV, plus a separate held-out section when `eval/heldout_questions.csv` exists | `eval/heldout_questions_TEMPLATE.csv`, `eval/retrieval_eval.py` |
| 6 Runbook and status | README runbook, this file | `README.md`, `REVIEW3_STATUS.md` |

## 2. New tables (real outputs)

### 2.1 `python -m crop_trigger.cli --compare C01 M01 F01 X01`

| case | plan | steps | tool_calls | rewrites | loops | decision |
|---|---|---|---|---|---|---|
| C01 | cross -> compute -> verify | 28 | 13 | 1 | 0 | TRIGGER_NOT_MET |
| M01 | missing -> cross -> compute -> verify | 29 | 15 | 2 | 0 | TRIGGER_NOT_MET |
| F01 | cross -> compute -> verify | 32 | 16 | 1 | 1 | TRIGGER_MET |
| X01 | cross -> compute -> verify | 28 | 13 | 1 | 0 | CANNOT_DETERMINE |

### 2.2 Planning ablation (`python eval/plan_ablation.py`, 38 labelled cases)

| Metric | agent_full (planned) | agent_no_plan (fixed pipeline) |
|---|---|---|
| Decision accuracy | 100.0% | 100.0% |
| Total payout exact | 100.0% | 100.0% |
| Unsafe-answer rate | 0.0% | 0.0% |
| Mean steps per run | 27.8 | 27.8 |
| Mean tool/retrieval calls per run | 13.3 | 14.9 |

## Reading

The two variants made the same decision on every case.
Accuracy is equal, so on these cases planning buys **cost, not correctness**: the fixed pipeline makes 1.6 more tool/retrieval calls per run (policy lookups for clauses the case does not need) and +0.0 trace steps (each skipped step logs a 'skipped' event and each extra lookup logs a retrieval event, so step counts barely move). The saving is small on this one policy.
Caveat: both variants share the same code and the same hand-written cases, so this shows what the plan saves, not that it generalises.

### 2.3 Abstention metrics (`python eval/abstention_eval.py`)

38 labelled cases:

| Metric | Naive baseline | Agent, no verifier | Agent, no cross-check | Agent (full) |
|---|---|---|---|---|
| Coverage (share answered) | 100.0% | 71.1% | 76.3% | 68.4% |
| Selective accuracy (correct among answered) | 55.3% | 96.3% | 89.7% | 100.0% |
| Unsafe-answer rate | 100.0% | 8.3% | 25.0% | 0.0% |
| Over-abstention rate | 0.0% | 0.0% | 0.0% | 0.0% |

500 stress cases (seed 2026):

| Metric | Naive baseline | Agent, no verifier | Agent, no cross-check | Agent (full) |
|---|---|---|---|---|
| Coverage (share answered) | 100.0% | 54.8% | 50.0% | 48.8% |
| Selective accuracy (correct among answered) | 29.2% | 89.1% | 97.6% | 100.0% |
| Unsafe-answer rate | 100.0% | 11.7% | 2.3% | 0.0% |
| Over-abstention rate | 0.0% | 0.0% | 0.0% | 0.0% |

Escalation rate by defect category: see `eval/abstention_results.md`.

### 2.4 Value-level cross-check (`python eval/value_check.py`)

38 labelled cases:

| Measure | Value |
|---|---|
| Cases | 38 |
| Cases showing an INFO value divergence (default agent) | 0 |
| Default agent fully correct (decision and payout) | 38/38 |
| Strict variant gives the same decision as default | 38/38 |
| Cases the strict variant newly escalates | 0 |
| Previously correct answers that become abstentions | 0 |
| Cases where truth is CANNOT_DETERMINE but strict answers | 0 |
| Strict variant fully correct | 38/38 |

500 stress cases:

| Measure | Value |
|---|---|
| Cases | 500 |
| Cases showing an INFO value divergence (default agent) | 20 |
| Default agent fully correct (decision and payout) | 500/500 |
| Strict variant gives the same decision as default | 486/500 |
| Cases the strict variant newly escalates | 14 |
| Previously correct answers that become abstentions | 14 |
| Cases where truth is CANNOT_DETERMINE but strict answers | 0 |
| Strict variant fully correct | 486/500 |

Correct answers lost to strict escalation: S078, S098, S107, S113, S132, S136, S139, S171, S201, S289, S307, S383, S400, S488

Honest reading: the labelled cases never exercise a value divergence (0 cases), so the claim that the default changes nothing is backed there by the unchanged results and, for the divergence path itself, by unit tests that scale a secondary file (`tests/test_value_check.py`). The strict variant is stricter than clause 4.1 (which compares trigger outcomes only); it is a design option, not the default.

### 2.5 Held-out retrieval

No held-out numbers yet: the questions must be written by a teammate. The scaffold is ready (`eval/heldout_questions_TEMPLATE.csv`); until `eval/heldout_questions.csv` exists the script prints a one-line note.

## 3. Proof that Review 2 results are unchanged

Baseline recorded before any change (backup of the project: `../crop_trigger_checker_backup_pre_r3`). After every task the tests were re-run and every eval script was re-run, then the md5 was compared. `eval/mutation_check.py` writes no results file (it prints only), so it has no md5; it still prints `4/4 planted bugs were caught by the stress test`.

| File | Baseline md5 (before Review 3) | Now | Same? |
|---|---|---|---|
| eval/results.md | 64cc4c2707c525c0c3fdc581470bd91b | 64cc4c2707c525c0c3fdc581470bd91b | yes |
| eval/retrieval_results.md | 5dcd7750c1186dc0db0d0805f9164948 | 5dcd7750c1186dc0db0d0805f9164948 | yes |
| eval/stress_results.md | 64cc5599f008e5a94ceaf34579abc316 | 64cc5599f008e5a94ceaf34579abc316 | yes |
| eval/results.json | 19aee8b9a542cfcf6ee30586812cda7f | 19aee8b9a542cfcf6ee30586812cda7f | yes |

Tests: **53 before, 85 now, all passing, 0 failures**. New test files: `test_observability.py` (10), `test_plan_ablation.py` (5), `test_abstention_eval.py` (4), `test_value_check.py` (8), `test_heldout_scaffold.py` (5).

One change is visible outside the eval files: trace events (and so saved `traces/*.jsonl`) now carry an extra optional `ts` field. Old traces without it still load (tested).

## 4. Honest limits (what is still untested or weak)

- **The Anthropic client is still untested** (no API key). The Ollama client was only tested earlier against one local model.
- **The UI has not been seen in a browser.** It is verified headlessly: Streamlit `AppTest` for C01, M01, F01 and X01 (no exceptions; metrics, filter and retrieval expanders present) and a live server start (HTTP 200, health ok, no traceback in the log). Colours, layout and the download click were not checked by eye.
- **The human gate does not truly pause.** It flags and refers (status AWAITING_HUMAN_REVIEW); nothing waits or resumes.
- Planning ablation: accuracy is **equal** (100% vs 100%); planning only saves tool/retrieval calls (small, on one policy).
- Abstention and value-check truths come from the same author's reading of the policy and the same generator (shared blind spot, as noted in Review 2).
- The value check is exercised by 0 of the 38 labelled cases and 20 of 500 stress cases; the risk that it changes a default result is therefore covered mostly by synthetic tests plus the unchanged eval files.
- The held-out set is not written yet; its agentic method uses the grader of the need implied by the expected clause, which slightly favours the agent (stated in the output).
- Streamlit `AppTest` tests write trace and run files into `traces/` and `runs/` of the project folder.
- `docs/make_diagram.py` needs matplotlib, which is not in `requirements.txt` (nothing else needs it).
- The wall-clock metric is the last event's offset from the start of the run (in milliseconds), not an externally timed duration.

## 5. Remaining for Review 4 (prioritised)

1. **LLM-only baseline**: give the same policy text and CSVs to an LLM with no tools and compare it on the 38 cases and the stress set. Needs an API key or a local model.
2. **Held-out retrieval questions** written by a teammate, then report the separate section.
3. **A second policy layout** (different wording and clause numbering) to test the regex rule extractor honestly, or wire the LLM extractor in as a fallback.
4. **LangGraph interrupt at the human gate** so the run truly pauses and resumes with the reviewer's decision.
5. **A third evidence source** (for example a satellite or a nearby-gauge series) and the cross-check logic that goes with it.
6. Look at the UI in a browser and fix whatever layout issues appear; test the Anthropic client once a key is available.
