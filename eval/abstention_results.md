# Selective-prediction (abstention) metrics

An answer is *correct* when the decision and the total payout both equal the truth. Coverage is the share of cases answered; the agent is allowed to refuse, so accuracy is judged only on what it answered. Numbers are exactly what `python eval/abstention_eval.py` printed.

## 38 labelled cases

38 cases; truth is CANNOT_DETERMINE in 12 and determinate in 26.

| Metric | Naive baseline | Agent, no verifier | Agent, no cross-check | Agent (full) |
|---|---|---|---|---|
| Coverage (share answered) | 100.0% | 71.1% | 76.3% | 68.4% |
| Selective accuracy (correct among answered) | 55.3% | 96.3% | 89.7% | 100.0% |
| Unsafe-answer rate | 100.0% | 8.3% | 25.0% | 0.0% |
| Over-abstention rate | 0.0% | 0.0% | 0.0% | 0.0% |

### Escalation rate by defect category (share of the category sent to a human; last column = share where the truth requires it)

| Category | Cases | Baseline | No verifier | No cross-check | Full | Truth needs referral |
|---|---|---|---|---|---|---|
| clean | 16 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| conflict | 4 | 0.0% | 75.0% | 0.0% | 75.0% | 75.0% |
| fault | 3 | 0.0% | 0.0% | 33.3% | 33.3% | 33.3% |
| integrity | 4 | 0.0% | 75.0% | 75.0% | 75.0% | 75.0% |
| missing | 6 | 0.0% | 50.0% | 50.0% | 50.0% | 50.0% |
| units | 5 | 0.0% | 40.0% | 40.0% | 40.0% | 40.0% |

## 500 randomised stress cases (seed 2026)

500 cases; truth is CANNOT_DETERMINE in 256 and determinate in 244.

| Metric | Naive baseline | Agent, no verifier | Agent, no cross-check | Agent (full) |
|---|---|---|---|---|
| Coverage (share answered) | 100.0% | 54.8% | 50.0% | 48.8% |
| Selective accuracy (correct among answered) | 29.2% | 89.1% | 97.6% | 100.0% |
| Unsafe-answer rate | 100.0% | 11.7% | 2.3% | 0.0% |
| Over-abstention rate | 0.0% | 0.0% | 0.0% | 0.0% |

### Escalation rate by defect category (share of the category sent to a human; last column = share where the truth requires it)

| Category | Cases | Baseline | No verifier | No cross-check | Full | Truth needs referral |
|---|---|---|---|---|---|---|
| clean | 58 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| conflicting_duplicates | 35 | 0.0% | 71.4% | 71.4% | 71.4% | 71.4% |
| fault_persistent | 53 | 0.0% | 43.4% | 100.0% | 100.0% | 100.0% |
| fault_transient | 56 | 0.0% | 44.6% | 44.6% | 44.6% | 44.6% |
| identical_duplicates | 43 | 0.0% | 51.2% | 55.8% | 58.1% | 58.1% |
| missing | 258 | 0.0% | 75.2% | 76.7% | 76.7% | 76.7% |
| secondary_gap_on_missing_day | 95 | 0.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| secondary_gaps | 70 | 0.0% | 47.1% | 48.6% | 50.0% | 50.0% |
| station_conflict_P1 | 28 | 0.0% | 75.0% | 64.3% | 75.0% | 75.0% |
| station_conflict_P2 | 20 | 0.0% | 40.0% | 35.0% | 40.0% | 40.0% |
| station_conflict_P3 | 21 | 0.0% | 38.1% | 38.1% | 47.6% | 47.6% |
| unit_bad | 15 | 0.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| unit_blank | 25 | 0.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| unit_cm | 65 | 0.0% | 41.5% | 52.3% | 53.8% | 53.8% |
| unit_in | 50 | 0.0% | 2.0% | 8.0% | 8.0% | 8.0% |
| unit_mixed | 47 | 0.0% | 44.7% | 55.3% | 57.4% | 57.4% |
| wrong_station | 13 | 0.0% | 100.0% | 100.0% | 100.0% | 100.0% |

## Reading

A system that never abstains has coverage 100% but an unsafe-answer rate of 100% on cases that need a human. The full agent trades coverage for safety: it refuses where the evidence is not good enough, so its selective accuracy is judged on a smaller, safer set. Over-abstention is the share of answerable cases a variant refused. For the full agent it is 0.0% on the labelled cases and 0.0% on the stress cases, i.e. its lower coverage comes only from cases whose truth is CANNOT_DETERMINE (a lower coverage than the baseline is the intended behaviour, not a loss). Ablations show where each safeguard matters (no verifier: wrong answers on injected faults; no cross-check: station conflicts answered). Caveat: truth comes from the generator/oracle that shares the author's reading of the policy.
