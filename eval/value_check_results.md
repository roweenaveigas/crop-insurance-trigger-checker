# Value-level cross-check

Default behaviour: when both stations give the same trigger outcome but their index values differ by more than the tolerance (10% of the Primary value), the agent adds an INFO note (`value_divergence`) to the trace, the report and the review-reason list. It does **not** change any decision or payout. `agent_strict_values` (`strict_value_check=True`) escalates such a phase to a human instead. Numbers are exactly what `python eval/value_check.py` printed.

## 38 labelled cases

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

## 500 randomised stress cases (seed 2026)

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

## Reading

Whether a divergence is a problem depends on the policy: clause 4.1 only asks the stations' *trigger outcomes* to agree, so an escalation on value alone is stricter than the policy. The strict variant is therefore a design option, not the default; its cost is the 'previously correct answers that become abstentions' row above, judged against truth derived from the same trigger-outcome rule.
