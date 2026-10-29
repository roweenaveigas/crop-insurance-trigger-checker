# Planning ablation (38 labelled cases)

`agent_full` builds its plan from what the data looks like (unit conversion only if non-mm labels exist, gap filling only if gaps exist, cross-check only if a secondary file exists). `agent_no_plan` runs the fixed full pipeline for every case. Numbers are exactly what `python eval/plan_ablation.py` printed.

| Metric | agent_full (planned) | agent_no_plan (fixed pipeline) |
|---|---|---|
| Decision accuracy | 100.0% | 100.0% |
| Total payout exact | 100.0% | 100.0% |
| Unsafe-answer rate | 0.0% | 0.0% |
| Mean steps per run | 27.8 | 27.8 |
| Mean tool/retrieval calls per run | 13.3 | 14.9 |

## By category

| Category | Accuracy planned | Accuracy fixed | Mean steps planned | Mean steps fixed | Mean tool calls planned | Mean tool calls fixed |
|---|---|---|---|---|---|---|
| clean | 100.0% | 100.0% | 28.0 | 28.0 | 13.0 | 15.0 |
| conflict | 100.0% | 100.0% | 28.0 | 28.0 | 13.0 | 15.0 |
| fault | 100.0% | 100.0% | 31.7 | 31.7 | 16.0 | 18.0 |
| integrity | 100.0% | 100.0% | 25.5 | 25.5 | 11.8 | 13.2 |
| missing | 100.0% | 100.0% | 27.8 | 27.8 | 13.8 | 14.8 |
| units | 100.0% | 100.0% | 26.8 | 26.8 | 13.2 | 13.8 |

## Reading

The two variants made the same decision on every case.
Accuracy is equal, so on these cases planning buys **cost, not correctness**: the fixed pipeline makes 1.6 more tool/retrieval calls per run (policy lookups for clauses the case does not need) and +0.0 trace steps (each skipped step logs a 'skipped' event and each extra lookup logs a retrieval event, so step counts barely move). The saving is small on this one policy.
Caveat: both variants share the same code and the same hand-written cases, so this shows what the plan saves, not that it generalises.
