import json
from decimal import Decimal
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT, POLICY
from crop_trigger import agent, records
from crop_trigger.engine import FaultyCalculator
from crop_trigger.tracing import Tracer

CASES = json.loads((ROOT / "data" / "cases.json").read_text())["cases"]
BY_ID = {c["id"]: c for c in CASES}


def run_case(cid, **kw):
    c = BY_ID[cid]
    if c.get("fault") and "calculator" not in kw:
        kw["calculator"] = FaultyCalculator(c["fault"]["mode"], c["fault"]["phase"])
    return agent.run(POLICY, ROOT / c["primary"], ROOT / c["secondary"], **kw)


class LabelledCases(unittest.TestCase):
    def test_every_labelled_case_matches_ground_truth(self):
        for c in CASES:
            with self.subTest(case=c["id"]):
                s = run_case(c["id"])
                e = c["expected"]
                self.assertEqual(s["decision"], e["decision"])
                if e["total_payout"] is not None:
                    self.assertEqual(Decimal(str(s["total_payout"])), Decimal(e["total_payout"]))
                for pid, ep in e["phases"].items():
                    got = s["phase_final"][pid]
                    self.assertEqual(got["status"], ep["status"], pid)
                    if ep["status"] != "UNDETERMINED":
                        self.assertEqual(Decimal(str(got["index"])), Decimal(ep["index"]), pid)
                got_codes = {r["code"] for r in s["review_reasons"]}
                for code in e["reason_codes"]:
                    self.assertIn(code, got_codes)


class Behaviour(unittest.TestCase):
    def kinds(self, s):
        return [e["kind"] for e in s["tracer"].events]

    def test_planning_is_data_driven(self):
        clean = run_case("C01")
        plan_clean = [e for e in clean["tracer"].events if e["kind"] == "plan"][0]["summary"]
        self.assertNotIn("missing", plan_clean)
        self.assertNotIn("units", plan_clean)
        miss = run_case("M01")
        self.assertIn("missing", [e for e in miss["tracer"].events if e["kind"] == "plan"][0]["summary"])
        cm = run_case("U01")
        self.assertIn("units", [e for e in cm["tracer"].events if e["kind"] == "plan"][0]["summary"])

    def test_transient_fault_is_caught_and_fixed_by_retry(self):
        s = run_case("F01")
        self.assertEqual(s["compute_attempts"], 2)
        self.assertIn("loop", self.kinds(s))
        self.assertEqual(s["decision"], "TRIGGER_MET")
        self.assertEqual(s["phase_final"]["P1"]["index"], Decimal("90.0"))

    def test_persistent_fault_is_escalated_and_wrong_number_never_reported(self):
        s = run_case("F02")
        self.assertEqual(s["compute_attempts"], 2)                      # loop is bounded
        self.assertEqual(s["decision"], "CANNOT_DETERMINE")
        self.assertEqual(s["phase_final"]["P1"]["status"], "UNDETERMINED")
        self.assertNotIn("91.0", s["report_md"])

    def test_verifier_disabled_lets_the_fault_through(self):
        s = run_case("F02", verify_enabled=False)
        self.assertEqual(s["decision"], "TRIGGER_MET")                  # the ablation is worse - that is the point

    def test_missing_data_fill_is_logged_with_source(self):
        s = run_case("M01")
        self.assertEqual(len(s["fills"]), 2)
        self.assertTrue(all(f["source"] == "RWS-B" for f in s["fills"]))
        self.assertIn("filled from RWS-B", s["report_md"])

    def test_primary_is_never_overridden_on_disagreement(self):
        s = run_case("X02")                                             # primary says NOT met, secondary says met
        self.assertEqual(s["phase_final"]["P1"]["status"], "UNDETERMINED")
        self.assertEqual(s["decision"], "CANNOT_DETERMINE")
        self.assertIsNone(s["total_payout"])

    def test_no_payout_figure_when_cannot_determine(self):
        s = run_case("M03")
        self.assertEqual(s["decision"], "CANNOT_DETERMINE")
        if s["determinate_payout"] > 0:
            self.assertIn("no total is stated", s["report_md"])
        self.assertEqual(s["status"], "AWAITING_HUMAN_REVIEW")
        self.assertIsNone(s["report_data"]["total_payout_inr"])

    def test_missing_input_file_abstains_instead_of_crashing(self):
        s = agent.run(POLICY, ROOT / "data/cases/does_not_exist.csv", None)
        self.assertEqual(s["decision"], "CANNOT_DETERMINE")
        self.assertEqual(s["review_reasons"][0]["code"], "input_missing")

    def test_malformed_csv_abstains(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.csv"
            bad.write_text("day,mm\n2026-07-01,3\n")
            s = agent.run(POLICY, bad, None)
        self.assertEqual(s["decision"], "CANNOT_DETERMINE")
        self.assertEqual(s["review_reasons"][0]["code"], "input_invalid")

    def test_policy_without_rules_abstains(self):
        with tempfile.TemporaryDirectory() as d:
            pol = Path(d) / "p.txt"
            pol.write_text("Clause 1.1 Policy Period. The policy covers 2026, from 1 July 2026 to 15 October 2026.\n")
            s = agent.run(pol, ROOT / BY_ID["C01"]["primary"], None)
        self.assertEqual(s["decision"], "CANNOT_DETERMINE")
        self.assertEqual(s["review_reasons"][0]["code"], "policy_rules_not_found")

    def test_tampered_policy_number_is_still_computed_from_the_clause(self):
        # change the P1 strike in the policy text: the agent must follow the document, not memory
        with tempfile.TemporaryDirectory() as d:
            pol = Path(d) / "p.txt"
            pol.write_text(POLICY.read_text().replace("Strike: 120 mm. Exit: 60 mm.", "Strike: 160 mm. Exit: 60 mm."))
            s = agent.run(pol, ROOT / BY_ID["C01"]["primary"], ROOT / BY_ID["C01"]["secondary"])   # P1 = 150 mm
        self.assertEqual(s["phase_final"]["P1"]["status"], "MET")

    def test_step_limit_guardrail(self):
        old = agent.MAX_STEPS
        agent.MAX_STEPS = 3
        try:
            s = run_case("C01")
        finally:
            agent.MAX_STEPS = old
        self.assertEqual(s["decision"], "CANNOT_DETERMINE")
        self.assertIn("step_limit", [r["code"] for r in s["review_reasons"]])

    def test_trace_is_saved_and_ordered(self):
        with tempfile.TemporaryDirectory() as d:
            s = run_case("C02", tracer=Tracer(out_dir=d))
            files = list(Path(d).glob("*.jsonl"))
            self.assertEqual(len(files), 1)
            events = [json.loads(l) for l in files[0].read_text().splitlines()]
        self.assertEqual([e["step"] for e in events], list(range(1, len(events) + 1)))
        self.assertTrue({"plan", "tool", "retrieval", "decision"} <= {e["kind"] for e in events})

    def test_llm_summary_with_invented_number_is_rejected(self):
        class Liar:
            available = True
            name = "liar"

            def complete(self, system, prompt):
                if "JSON" in system:
                    raise RuntimeError("not used for extraction in this test")
                return "Payout is INR 99999 and the trigger is met."
        s = run_case("C02", llm=Liar())
        self.assertNotIn("99999", s["report_md"])
        self.assertTrue(any("LLM summary rejected" in e["summary"] for e in s["tracer"].events))

    def test_llm_extraction_disagreement_routes_to_human(self):
        class Dissenter:
            available = True
            name = "dissenter"

            def complete(self, system, prompt):
                return json.dumps({"index_type": "cumulative_deficit", "window_start": "2026-07-01", "window_end": "2026-07-31",
                                   "strike": 100, "rate": 300, "cap": 18000, "sum_insured": None, "slab_pcts": []})
        s = run_case("C01", llm=Dissenter())
        self.assertEqual(s["decision"], "CANNOT_DETERMINE")
        self.assertIn("rule_llm_disagreement", [r["code"] for r in s["review_reasons"]])

    def test_llm_network_failure_does_not_break_the_run(self):
        class Down:
            available = True
            name = "down"

            def complete(self, system, prompt):
                raise ConnectionError("offline")
        s = run_case("C02", llm=Down())
        self.assertEqual(s["decision"], "TRIGGER_MET")


class LLMFailureVersusDisagreement(unittest.TestCase):
    """An LLM that is down or rambles gives no opinion (parser kept); only valid JSON that differs halts the run."""

    @staticmethod
    def rule_json(strike):
        return json.dumps({"index_type": "dry_spell", "window_start": "2026-08-01", "window_end": "2026-09-15",
                           "strike": strike, "rate": None, "cap": None, "sum_insured": 30000, "slab_pcts": [25, 50]})

    def fake(self, extraction):
        class Fake:
            available = True
            name = "fake"

            def __init__(self):
                self.calls = 0

            def complete(self, system, prompt):
                if "JSON" not in system:                      # the summary request: not under test here
                    raise RuntimeError("summary not used in this test")
                self.calls += 1
                return extraction(self.calls)
        return Fake()

    def test_invalid_json_keeps_parser_result_and_does_not_escalate(self):
        s = run_case("C02", llm=self.fake(lambda n: "sorry, I cannot read that clause"))
        self.assertEqual(s["decision"], "TRIGGER_MET")                                  # same answer as without an LLM
        self.assertNotIn("rule_llm_disagreement", [r["code"] for r in s["review_reasons"]])
        notes = [e["summary"] for e in s["tracer"].events if e["kind"] == "guardrail" and "unusable" in e["summary"]]
        self.assertEqual(len(notes), 3)                                                 # one logged event per phase rule

    def test_valid_json_of_the_wrong_shape_is_also_not_a_disagreement(self):
        s = run_case("C02", llm=self.fake(lambda n: '{"strike": "abc"}'))
        self.assertEqual(s["decision"], "TRIGGER_MET")

    def test_valid_disagreeing_json_still_halts_even_after_an_unusable_reply(self):
        # reply 1 (P1) is garbage -> logged, parser kept; reply 2 (P2) is valid JSON with a different strike -> halt
        s = run_case("C02", llm=self.fake(lambda n: "garbage" if n == 1 else self.rule_json(99)))
        self.assertEqual(s["decision"], "CANNOT_DETERMINE")
        self.assertIn("rule_llm_disagreement", [r["code"] for r in s["review_reasons"]])
        self.assertTrue(any("unusable for P1" in e["summary"] for e in s["tracer"].events))


class PlanDrivesRoute(unittest.TestCase):
    def nodes(self, s):
        return [e["node"] for e in s["tracer"].events]

    def summaries(self, s):
        return " | ".join(e["summary"] for e in s["tracer"].events)

    def test_router_follows_plan(self):
        self.assertEqual(agent._after_verify({"retry": True, "plan_steps": ["cross", "compute", "verify"]}), "compute")
        self.assertEqual(agent._after_verify({"retry": False, "plan_steps": ["cross", "compute", "verify"]}), "cross_check")
        self.assertEqual(agent._after_verify({"retry": False, "plan_steps": ["compute", "verify"]}), "decide")

    def test_clean_case_skips_unit_conversion_and_gap_filling_and_trace_shows_it(self):
        s = run_case("C01")                                          # clean: all mm, no gaps
        self.assertEqual(s["plan_steps"], ["cross", "compute", "verify"])
        text = self.summaries(s)
        self.assertIn("unit conversion skipped", text)
        self.assertIn("gap filling skipped", text)
        self.assertEqual(s["fills"], [])
        plan = [e for e in s["tracer"].events if e["kind"] == "plan"][0]
        self.assertTrue(any("skipped: ['units', 'missing']" in t for t in plan["data"]["thoughts"]))

    def test_no_cross_step_means_verify_routes_straight_to_decide(self):
        for label, kw, secondary in (("no secondary file", {}, None), ("cross-check disabled", {"crosscheck_enabled": False}, "file")):
            with self.subTest(label):
                c = BY_ID["C02"]
                sec = ROOT / c["secondary"] if secondary else None
                s = agent.run(POLICY, ROOT / c["primary"], sec, **kw)
                self.assertNotIn("cross", s["plan_steps"])
                self.assertNotIn("cross_check", self.nodes(s))      # the node never ran
                self.assertIn("cross_check not in plan -> routing straight to decide", self.summaries(s))
                self.assertTrue(any("uncorroborated" in n for n in s["notes"]))
                self.assertEqual(s["decision"], run_case("C02")["decision"])   # route changes the trace, not the answer

    def test_cross_step_present_runs_cross_check(self):
        s = run_case("C02")
        self.assertIn("cross", s["plan_steps"])
        self.assertIn("cross_check", self.nodes(s))
        self.assertNotIn("routing straight to decide", self.summaries(s))

    def test_gap_filling_happens_only_when_plan_lists_missing(self):
        # M01 needs gap filling. Hide 'missing' from remediate: it must withhold the phase, not fill from the secondary.
        orig = agent.NODES["remediate"]
        agent.NODES["remediate"] = lambda st: orig({**st, "plan_steps": [x for x in st["plan_steps"] if x != "missing"]})
        try:
            s = run_case("M01")
        finally:
            agent.NODES["remediate"] = orig
        self.assertEqual(s["fills"], [])
        self.assertEqual(s["decision"], "CANNOT_DETERMINE")
        self.assertIn("gap filling skipped", self.summaries(s))

    def test_unit_conversion_happens_only_when_plan_lists_units(self):
        # U01 has cm readings. Hide 'units': they must be treated as unsupported (invalid), never silently used as mm.
        orig = agent.NODES["remediate"]
        agent.NODES["remediate"] = lambda st: orig({**st, "plan_steps": [x for x in st["plan_steps"] if x != "units"]})
        try:
            s = run_case("U01")
        finally:
            agent.NODES["remediate"] = orig
        self.assertEqual(s["decision"], "CANNOT_DETERMINE")
        self.assertIn("unit conversion skipped", self.summaries(s))


class HumanReview(unittest.TestCase):
    def test_review_workflow(self):
        s = run_case("X01")
        rec = records.to_record(s)
        self.assertEqual(rec["status"], "AWAITING_HUMAN_REVIEW")
        with self.assertRaises(ValueError):
            records.apply_human_review(rec, "", "ACCEPT_REFERRAL", "x")
        with self.assertRaises(ValueError):
            records.apply_human_review(rec, "Asha", "APPROVE_PAYOUT", "x")
        rec = records.apply_human_review(rec, "Asha", "ESCALATE_TO_COMMITTEE", "Stations disagree on P1")
        self.assertEqual(rec["status"], "REVIEWED_ESCALATE_TO_COMMITTEE")
        self.assertEqual(rec["human_review"][0]["reviewer"], "Asha")
        with self.assertRaises(ValueError):                              # cannot be reviewed twice
            records.apply_human_review(rec, "Asha", "CLOSE_NO_ACTION", "again")

    def test_complete_runs_cannot_be_reviewed(self):
        rec = records.to_record(run_case("C01"))
        with self.assertRaises(ValueError):
            records.apply_human_review(rec, "Asha", "ACCEPT_REFERRAL", "x")


if __name__ == "__main__":
    unittest.main()
