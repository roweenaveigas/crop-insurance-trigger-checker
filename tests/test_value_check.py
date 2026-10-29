"""Review 3: value-level cross-check. Default = INFO note that changes nothing; strict_value_check escalates."""
import csv
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

from tests.helpers import ROOT, POLICY

from crop_trigger import agent
from crop_trigger.tracing import Tracer


def case_files(cid):
    return ROOT / "data" / "cases" / f"{cid}_primary.csv", ROOT / "data" / "cases" / f"{cid}_secondary.csv"


def scaled_secondary(cid, factor, month_prefix, tmp):
    """Copy the case's secondary file with rainfall of the dates starting with month_prefix multiplied by factor."""
    _, sec = case_files(cid)
    with sec.open(newline="") as f:
        rows = list(csv.reader(f))
    out = [rows[0]]
    for r in rows[1:]:
        if r[0].startswith(month_prefix):
            r = [r[0], str((D(r[1]) * D(str(factor))).quantize(D("0.01"))), r[2], r[3]]
        out.append(r)
    p = Path(tmp) / "sec.csv"
    with p.open("w", newline="") as f:
        csv.writer(f).writerows(out)
    return p


def run(sec, **kw):
    pri, _ = case_files("C01")
    return agent.run(POLICY, pri, sec, tracer=Tracer(), **kw)


class RelativeGap(unittest.TestCase):
    def test_gap_arithmetic(self):
        self.assertEqual(agent._relative_gap(D("100"), D("100")), 0)
        self.assertEqual(agent._relative_gap(D("100"), D("90")), D("0.1"))
        self.assertEqual(agent._relative_gap(D("100"), D("125")), D("0.25"))
        self.assertEqual(agent._relative_gap(D("0"), D("3")), D("Infinity"))
        self.assertEqual(agent._relative_gap(D("0"), D("0")), 0)

    def test_default_tolerance_is_ten_percent_in_one_place(self):
        self.assertEqual(agent.VALUE_TOLERANCE, D("0.10"))


class DefaultIsNonBlocking(unittest.TestCase):
    def test_divergence_is_info_only_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            sec = scaled_secondary("C01", 1.2, "2026-07", tmp)           # P1 secondary index 150 -> 180; trigger outcome unchanged
            base = run(case_files("C01")[1])
            s = run(sec)
            self.assertEqual((s["decision"], s["total_payout"]), (base["decision"], base["total_payout"]))
            self.assertEqual(s["phase_final"], base["phase_final"])
            self.assertEqual(s["status"], "COMPLETE")                      # no human-review flag
            info = [r for r in s["review_reasons"] if r["code"] == "value_divergence"]
            self.assertEqual(len(info), 1)
            self.assertEqual((info[0]["severity"], info[0]["phase"]), ("info", "P1"))
            self.assertTrue(any("INFO value_divergence" in n for n in s["notes"]))
            ev = [e for e in s["tracer"].events if "value_divergence" in e.get("data", {})]
            self.assertEqual(len(ev), 1)
            self.assertIn("INFO value_divergence", ev[0]["summary"])
            self.assertEqual(len(s["tracer"].events), len(base["tracer"].events))     # no extra trace step
            self.assertIn("## Informational notes", s["report_md"])
            self.assertNotIn("## Needs human review", s["report_md"])
            self.assertIn("value_divergence (INFO)", __import__("crop_trigger.observability", fromlist=["x"]).run_metrics(s["tracer"].events)["review_reasons"])

    def test_no_divergence_means_no_note(self):
        s = run(case_files("C01")[1])
        self.assertFalse([r for r in s["review_reasons"] if r["code"] == "value_divergence"])
        self.assertNotIn("Informational", s["report_md"])

    def test_tolerance_is_configurable(self):
        with tempfile.TemporaryDirectory() as tmp:
            sec = scaled_secondary("C01", 1.2, "2026-07", tmp)             # 20% apart
            self.assertTrue([r for r in run(sec)["review_reasons"] if r["code"] == "value_divergence"])
            self.assertFalse([r for r in run(sec, value_tolerance=D("0.25"))["review_reasons"] if r["code"] == "value_divergence"])
            small = scaled_secondary("C01", 1.05, "2026-07", tmp)           # 5% apart: inside the default tolerance
            self.assertFalse([r for r in run(small)["review_reasons"] if r["code"] == "value_divergence"])


class StrictMode(unittest.TestCase):
    def test_strict_escalates_the_diverging_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            sec = scaled_secondary("C01", 1.2, "2026-07", tmp)
            s = run(sec, strict_value_check=True)
            self.assertEqual(s["decision"], "CANNOT_DETERMINE")
            self.assertEqual(s["phase_final"]["P1"]["code"], "value_divergence")
            self.assertEqual(s["phase_final"]["P2"]["status"], "NOT_MET")
            self.assertEqual(s["status"], "AWAITING_HUMAN_REVIEW")
            self.assertIsNone(s["total_payout"])
            self.assertIn("## Needs human review", s["report_md"])

    def test_strict_changes_nothing_when_values_agree(self):
        a, b = run(case_files("C01")[1]), run(case_files("C01")[1], strict_value_check=True)
        self.assertEqual((a["decision"], a["total_payout"]), (b["decision"], b["total_payout"]))

    def test_langgraph_accepts_strict_flag(self):
        try:
            import langgraph  # noqa: F401
        except ImportError:
            self.skipTest("langgraph not installed")
        pri, _ = case_files("C01")
        with tempfile.TemporaryDirectory() as tmp:
            s = agent.run_langgraph(POLICY, pri, scaled_secondary("C01", 1.2, "2026-07", tmp), tracer=Tracer(), strict_value_check=True)
        self.assertEqual(s["decision"], "CANNOT_DETERMINE")


if __name__ == "__main__":
    unittest.main()
