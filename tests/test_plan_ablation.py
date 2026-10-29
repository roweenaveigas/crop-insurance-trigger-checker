"""Review 3: the plan_enabled=False ablation runs the fixed full pipeline and must not change the default behaviour."""
import unittest

from tests.helpers import ROOT, POLICY  # noqa: F401

from crop_trigger import agent
from crop_trigger.engine import FaultyCalculator
from crop_trigger.tracing import Tracer

import json

CASES = {c["id"]: c for c in json.loads((ROOT / "data" / "cases.json").read_text())["cases"]}


def run(cid, **kw):
    c = CASES[cid]
    if c.get("fault"):
        kw["calculator"] = FaultyCalculator(c["fault"]["mode"], c["fault"]["phase"])
    return agent.run(POLICY, ROOT / c["primary"], ROOT / c["secondary"], tracer=Tracer(), **kw)


class PlanAblation(unittest.TestCase):
    def test_default_plan_is_unchanged(self):
        self.assertEqual(run("C01")["plan_steps"], ["cross", "compute", "verify"])
        self.assertEqual(run("M01")["plan_steps"], ["missing", "cross", "compute", "verify"])
        self.assertEqual(run("C01", plan_enabled=True)["plan_steps"], run("C01")["plan_steps"])

    def test_no_plan_runs_the_same_fixed_steps_for_every_case(self):
        for cid in ("C01", "M01", "U01", "X01"):
            s = run(cid, plan_enabled=False)
            self.assertEqual(s["plan_steps"], ["units", "missing", "cross", "compute", "verify"], cid)
            plan_event = next(e for e in s["tracer"].events if e["kind"] == "plan")
            self.assertIn("planning disabled", plan_event["summary"])

    def test_no_plan_does_extra_lookups_but_decides_the_same(self):
        for cid in ("C01", "M01", "U01", "X01", "F01", "D01"):
            a, b = run(cid), run(cid, plan_enabled=False)
            self.assertEqual((a["decision"], a["total_payout"]), (b["decision"], b["total_payout"]), cid)
            self.assertGreater(b["tracer"].count("retrieval"), a["tracer"].count("retrieval") - 1, cid)
        c1, c2 = run("C01"), run("C01", plan_enabled=False)
        self.assertEqual(set(c2["retrievals"]) - set(c1["retrievals"]), {"units", "missing"})

    def test_no_plan_respects_disabled_crosscheck(self):
        s = run("C01", plan_enabled=False, crosscheck_enabled=False)
        self.assertEqual(s["plan_steps"], ["units", "missing", "compute", "verify"])

    def test_langgraph_accepts_the_flag(self):
        try:
            import langgraph  # noqa: F401
        except ImportError:
            self.skipTest("langgraph not installed")
        c = CASES["M01"]
        s = agent.run_langgraph(POLICY, ROOT / c["primary"], ROOT / c["secondary"], tracer=Tracer(), plan_enabled=False)
        self.assertEqual(s["plan_steps"], ["units", "missing", "cross", "compute", "verify"])
        self.assertEqual(s["decision"], run("M01")["decision"])


if __name__ == "__main__":
    unittest.main()
