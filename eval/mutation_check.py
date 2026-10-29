"""Is the evaluation able to fail? Plant a deliberate bug in the agent, re-run the stress test, expect mismatches.

If a mutant survives (0 mismatches) the test suite is blind to that kind of bug.
Run:  python eval/mutation_check.py
"""
import sys
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

import stress_eval  # noqa: E402
from crop_trigger import engine, rules as R  # noqa: E402

orig_units, orig_dry = R.extract_unit_factors, R.extract_dry_threshold

MUTANTS = {
    "dry-day threshold read as 2.6 mm instead of 2.5 (acts like <=)": ("crop_trigger.rules.extract_dry_threshold", lambda t: D("2.6")),
    "missing-day fill limit read as 4 instead of 3": ("crop_trigger.rules.extract_fill_limit", lambda t: 4),
    "inch factor read as 25 instead of 25.4": ("crop_trigger.rules.extract_unit_factors", lambda t: {**orig_units(t), "in": D(25)}),
    "fill limit ignored (no cap on gaps)": ("crop_trigger.rules.extract_fill_limit", lambda t: 999),
}


def main():
    base = stress_eval.main(200, 7, write=False, quiet=True)
    print(f"unmodified agent: {base} mismatches out of 200")
    survived = 0
    for name, (target, fn) in MUTANTS.items():
        with mock.patch(target, fn):
            m = stress_eval.main(200, 7, write=False, quiet=True)
        print(f"{'CAUGHT  ' if m else 'SURVIVED'} {m:3d} mismatches  <- {name}")
        survived += m == 0
    print(f"\n{len(MUTANTS) - survived}/{len(MUTANTS)} planted bugs were caught by the stress test")


if __name__ == "__main__":
    main()
