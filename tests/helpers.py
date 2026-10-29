import sys
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crop_trigger import rag, rules as R  # noqa: E402

POLICY = ROOT / "data" / "policy_sample.txt"


def policy_rules():
    idx = rag.PolicyIndex.from_text(POLICY.read_text())
    ch = {c.clause_id: c for c in idx.chunks}
    dry = R.extract_dry_threshold(ch["2.2"].text)
    return [R.extract_phase_rule(ch[c], i, dry) for i, c in enumerate(["3.1", "3.2", "3.3"], 1)]


def series_for(rule, values):
    """values: list of Decimal/str/float for each day of the window (shorter lists are padded with 5.0 mm)."""
    days = rule.window()
    vals = [D(str(v)) for v in values] + [D("5.0")] * (len(days) - len(values))
    return dict(zip(days, vals))
