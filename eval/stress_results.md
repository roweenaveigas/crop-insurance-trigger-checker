# Randomised stress test (500 cases, seed 2026)

Expected answers come from an independent brute-force implementation of the policy text (see `eval/stress_eval.py`), not from the agent.

- Agent fully correct (decision, every phase status, every index, total payout): **100.0%** (500/500)
- Naive baseline decision accuracy: 46.8% (234/500)
- Agent index exactness on determinate phases: 100.0%; total payout exact: 100.0%
- Cases where the truth is CANNOT_DETERMINE: 256; agent gave an unsafe answer on 0 of them

| Defect present | Cases | Agent fully correct | Baseline decision correct |
|---|---|---|---|
| clean | 58 | 100.0% | 100.0% |
| conflicting_duplicates | 35 | 100.0% | 22.9% |
| fault_persistent | 53 | 100.0% | 0.0% |
| fault_transient | 56 | 100.0% | 51.8% |
| identical_duplicates | 43 | 100.0% | 41.9% |
| missing | 258 | 100.0% | 22.5% |
| secondary_gap_on_missing_day | 95 | 100.0% | 0.0% |
| secondary_gaps | 70 | 100.0% | 50.0% |
| station_conflict_P1 | 28 | 100.0% | 17.9% |
| station_conflict_P2 | 20 | 100.0% | 60.0% |
| station_conflict_P3 | 21 | 100.0% | 52.4% |
| unit_bad | 15 | 100.0% | 0.0% |
| unit_blank | 25 | 100.0% | 0.0% |
| unit_cm | 65 | 100.0% | 41.5% |
| unit_in | 50 | 100.0% | 84.0% |
| unit_mixed | 47 | 100.0% | 42.6% |
| wrong_station | 13 | 100.0% | 0.0% |

## Mismatches (0)

