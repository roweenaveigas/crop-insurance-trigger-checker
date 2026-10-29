"""Review 3: the selective-prediction metric arithmetic (hand-checked tiny sets) and one real run on the labelled cases."""
import sys
import unittest

from tests.helpers import ROOT  # noqa: F401

sys.path.insert(0, str(ROOT / "eval"))
import abstention_eval as A  # noqa: E402

CD = "CANNOT_DETERMINE"


def rec(truth, got, ok, *cats):
    return {"truth": truth, "got": got, "ok": ok, "cats": list(cats) or ["x"]}


class MetricArithmetic(unittest.TestCase):
    def test_hand_checked_metrics(self):
        rs = [rec("TRIGGER_MET", "TRIGGER_MET", True), rec("TRIGGER_MET", "TRIGGER_NOT_MET", False),     # answered: 1 of 2 correct
              rec("TRIGGER_NOT_MET", CD, False),                                                           # over-abstention
              rec(CD, CD, True), rec(CD, "TRIGGER_MET", False)]                                            # one unsafe answer
        m = A.metrics(rs)
        self.assertEqual(m["coverage"], 3 / 5)
        self.assertEqual(m["selective_accuracy"], 1 / 3)       # answered = rows 1, 2, 5; only row 1 correct
        self.assertEqual(m["unsafe"], 1 / 2)
        self.assertEqual(m["over_abstention"], 1 / 3)

    def test_never_answering_gives_none_for_selective_accuracy(self):
        m = A.metrics([rec(CD, CD, True), rec("TRIGGER_MET", CD, False)])
        self.assertEqual(m["coverage"], 0)
        self.assertIsNone(m["selective_accuracy"])

    def test_escalation_by_category_counts_multi_flag_cases_in_each_category(self):
        rs = [rec(CD, CD, True, "a", "b"), rec("TRIGGER_MET", "TRIGGER_MET", True, "a"), rec(CD, "TRIGGER_MET", False, "b")]
        esc = A.escalation_by_category(rs)
        self.assertEqual(esc["a"], (2, 1 / 2, 1 / 2))
        self.assertEqual(esc["b"], (2, 1 / 2, 1))


class RealLabelledRun(unittest.TestCase):
    def test_full_agent_never_answers_when_it_should_abstain(self):
        recs = A.labelled_records()
        full, base = A.metrics(recs["agent_full"]), A.metrics(recs["baseline_naive"])
        self.assertEqual(full["unsafe"], 0)
        self.assertEqual(full["selective_accuracy"], 1.0)
        self.assertEqual(base["coverage"], 1.0)             # the baseline never abstains
        self.assertEqual(base["unsafe"], 1.0)
        self.assertEqual(full["n"], 38)


if __name__ == "__main__":
    unittest.main()
