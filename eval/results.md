# Evaluation results (38 labelled cases)

Ground truth is planted by construction in `data/generate_data.py` (not produced by the agent). Numbers below are exactly what `python eval/run_eval.py` printed.

## Headline comparison

| Metric | Naive baseline | Agent, no verifier | Agent, no cross-check | Agent (full) |
|---|---|---|---|---|
| Decision accuracy (3-class) | 65.8% | 97.4% | 92.1% | 100.0% |
| Index exact (determinate phases) | 89.2% | 97.8% | 100.0% | 100.0% |
| Total payout exact (determinate cases) | 80.8% | 100.0% | 100.0% | 100.0% |
| Abstention precision | n/a | 100.0% | 100.0% | 100.0% |
| Abstention recall | 0.0% | 91.7% | 75.0% | 100.0% |
| Unsafe-answer rate (answered when it should abstain) | 100.0% | 8.3% | 25.0% | 0.0% |
| Citation recall | n/a | 100.0% | 85.5% | 100.0% |
| Citation precision | n/a | 100.0% | 100.0% | 100.0% |
| Verifier catch rate on injected faults | n/a | 0.0% | 100.0% | 100.0% |

## Decision accuracy by category

| Category | baseline_naive | agent_no_verifier | agent_no_crosscheck | agent_full |
|---|---|---|---|---|
| clean | 100.0% | 100.0% | 100.0% | 100.0% |
| conflict | 25.0% | 100.0% | 25.0% | 100.0% |
| fault | 66.7% | 66.7% | 100.0% | 100.0% |
| integrity | 25.0% | 100.0% | 100.0% | 100.0% |
| missing | 33.3% | 100.0% | 100.0% | 100.0% |
| units | 60.0% | 100.0% | 100.0% | 100.0% |

## Cost of agency (agent_full)

- mean steps per run: 27.8; mean tool/retrieval calls: 13.3; mean verify loops: 0.08
- retrieval rewrite rate: 18.9% of policy lookups needed a rewritten query

## Cases where agent_full did not match the ground truth

None.

## Cases where the naive baseline was wrong

- M01 (missing): wrong decision - expected TRIGGER_NOT_MET, baseline said TRIGGER_MET
- M02 (missing): right decision (TRIGGER_MET) but wrong payout figure
- M03 (missing): wrong decision - expected CANNOT_DETERMINE, baseline said TRIGGER_MET
- M04 (missing): wrong decision - expected CANNOT_DETERMINE, baseline said TRIGGER_MET
- M06 (missing): wrong decision - expected CANNOT_DETERMINE, baseline said TRIGGER_NOT_MET
- U01 (units): right decision (TRIGGER_MET) but wrong payout figure
- U02 (units): right decision (TRIGGER_MET) but wrong payout figure
- U03 (units): wrong decision - expected CANNOT_DETERMINE, baseline said TRIGGER_MET
- U04 (units): wrong decision - expected CANNOT_DETERMINE, baseline said TRIGGER_MET
- U05 (units): right decision (TRIGGER_MET) but wrong payout figure
- D01 (integrity): wrong decision - expected CANNOT_DETERMINE, baseline said TRIGGER_NOT_MET
- D02 (integrity): wrong decision - expected CANNOT_DETERMINE, baseline said TRIGGER_MET
- D03 (integrity): wrong decision - expected CANNOT_DETERMINE, baseline said TRIGGER_NOT_MET
- X01 (conflict): wrong decision - expected CANNOT_DETERMINE, baseline said TRIGGER_MET
- X02 (conflict): wrong decision - expected CANNOT_DETERMINE, baseline said TRIGGER_NOT_MET
- X04 (conflict): wrong decision - expected CANNOT_DETERMINE, baseline said TRIGGER_MET
- F02 (fault): wrong decision - expected CANNOT_DETERMINE, baseline said TRIGGER_MET
