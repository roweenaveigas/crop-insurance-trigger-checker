"""Runs only if `pip install langgraph` has been done. Checks that LangGraph and the built-in runner agree on every case."""
import json
import unittest

try:
    import langgraph  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False

from tests.helpers import ROOT, POLICY
from crop_trigger import agent
from crop_trigger.engine import FaultyCalculator

CASES = json.loads((ROOT / "data" / "cases.json").read_text())["cases"]


@unittest.skipUnless(HAVE, "langgraph not installed")
class Parity(unittest.TestCase):
    def test_same_decisions_and_numbers(self):
        for c in CASES:
            with self.subTest(case=c["id"]):
                def kw():
                    return {"calculator": FaultyCalculator(c["fault"]["mode"], c["fault"]["phase"])} if c.get("fault") else {}
                a = agent.run(POLICY, ROOT / c["primary"], ROOT / c["secondary"], **kw())
                b = agent.run_langgraph(POLICY, ROOT / c["primary"], ROOT / c["secondary"], **kw())
                self.assertEqual(a["decision"], b["decision"])
                self.assertEqual(a["total_payout"], b["total_payout"])
                self.assertEqual({k: v["status"] for k, v in a["phase_final"].items()},
                                 {k: v["status"] for k, v in b["phase_final"].items()})

    def test_recursion_limit_escalates_like_the_builtin_runner(self):
        c = CASES[0]
        # limits 1..4 stop the graph early (even before intake finishes); the run must still end escalated, not crash
        for limit in (1, 2, 3, 4, 8):
            with self.subTest(limit=limit):
                s = agent.run_langgraph(POLICY, ROOT / c["primary"], ROOT / c["secondary"], recursion_limit=limit)
                self.assertEqual(s["decision"], "CANNOT_DETERMINE")
                self.assertIn("step_limit", [r["code"] for r in s["review_reasons"]])
                self.assertEqual(s["status"], "AWAITING_HUMAN_REVIEW")
                self.assertIsNone(s["total_payout"])
                self.assertTrue(any("recursion limit" in e["summary"] for e in s["tracer"].events))

    def test_graph_compiles(self):
        self.assertIsNotNone(agent.build_langgraph())


if __name__ == "__main__":
    unittest.main()
