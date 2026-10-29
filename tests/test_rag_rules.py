import json
import unittest
from dataclasses import replace
from decimal import Decimal as D

from tests.helpers import POLICY
from crop_trigger import rag, rules as R


class FakeLLM:
    available = True
    name = "fake"

    def __init__(self, reply):
        self.reply = reply

    def complete(self, system, prompt):
        return self.reply


class RagTests(unittest.TestCase):
    def setUp(self):
        self.idx = rag.PolicyIndex.from_text(POLICY.read_text())
        self.chunks = {c.clause_id: c for c in self.idx.chunks}

    def test_clauses_are_split(self):
        self.assertEqual([c.clause_id for c in self.idx.chunks], ["1.1", "1.2", "1.3", "2.1", "2.2", "3.1", "3.2", "3.3", "4.1", "5.1", "5.2"])

    def test_every_standard_need_resolves_to_the_right_clause(self):
        expect = {"dry_day": ["2.2"], "stations": ["1.3"], "period": ["1.1"], "overall_cap": ["5.1"], "disclaimer": ["5.2"],
                  "units": ["2.1"], "missing": ["4.1"], "cross": ["4.1"], "phases": ["3.1", "3.2", "3.3"]}
        for name, ids in expect.items():
            with self.subTest(need=name):
                r = rag.retrieve(self.idx, rag.NEEDS[name])
                self.assertEqual(r.status, "ok")
                self.assertEqual(sorted(r.clause_ids), ids)

    def test_weak_first_query_triggers_a_rewrite_that_succeeds(self):
        r = rag.retrieve(self.idx, rag.NEEDS["missing"])
        self.assertEqual(r.status, "ok")
        self.assertGreaterEqual(r.rewrites, 1)
        self.assertEqual(r.attempts[0]["passed"], [])        # first attempt was graded as weak
        self.assertEqual(r.attempts[-1]["passed"], ["4.1"])

    def test_out_of_scope_question_is_not_found_not_guessed(self):
        need = rag.Need("premium", "what premium does the farmer pay", ("premium rate",), "premium rate farmer pays")
        r = rag.retrieve(self.idx, need)
        self.assertEqual(r.status, "not_found")
        self.assertEqual(r.chunks, [])
        self.assertEqual(len(r.attempts), 3)                 # budget fully used, then fall back to abstaining

    def test_attempts_are_bounded(self):
        need = rag.Need("x", "nothing matches this zzz", ("qqq",), "also zzz")
        self.assertLessEqual(len(rag.retrieve(self.idx, need, max_attempts=2).attempts), 2)


class RuleTests(unittest.TestCase):
    def setUp(self):
        idx = rag.PolicyIndex.from_text(POLICY.read_text())
        self.ch = {c.clause_id: c for c in idx.chunks}
        self.dry = R.extract_dry_threshold(self.ch["2.2"].text)

    def test_extracted_values(self):
        p1 = R.extract_phase_rule(self.ch["3.1"], 1)
        self.assertEqual((p1.strike, p1.exit_value, p1.rate, p1.cap), (D(120), D(60), D(300), D(18000)))
        p2 = R.extract_phase_rule(self.ch["3.2"], 2, self.dry)
        self.assertEqual((p2.strike, p2.sum_insured, p2.dry_day_threshold), (D(15), D(30000), D("2.5")))
        self.assertEqual([s.pct for s in p2.slabs], [D(25), D(50)])
        p3 = R.extract_phase_rule(self.ch["3.3"], 3)
        self.assertEqual((p3.strike, p3.sum_insured), (D(250), D(20000)))
        self.assertFalse(p3.slabs[0].lower_inclusive)

    def test_constants(self):
        self.assertEqual(R.extract_stations(self.ch["1.3"].text), ("RWS-A", "RWS-B"))
        self.assertEqual(R.extract_unit_factors(self.ch["2.1"].text), {"mm": D(1), "cm": D(10), "in": D("25.4")})
        self.assertEqual(R.extract_fill_limit(self.ch["4.1"].text), 3)
        self.assertEqual(R.extract_overall_cap(self.ch["5.1"].text), D(68000))

    def test_unparseable_clause_raises(self):
        broken = rag.Chunk("3.1", "Phase 1 - X (Cumulative Rainfall Deficit)", "Phase 1 - X (Cumulative Rainfall Deficit). nothing useful here")
        with self.assertRaises(R.ExtractionError):
            R.extract_phase_rule(broken, 1)

    def test_llm_cross_check_agree_disagree_and_garbage(self):
        rule = R.extract_phase_rule(self.ch["3.1"], 1)
        good = {"index_type": "cumulative_deficit", "window_start": "2026-07-01", "window_end": "2026-07-31",
                "strike": 120, "rate": 300, "cap": 18000, "sum_insured": None, "slab_pcts": []}
        self.assertEqual(R.llm_rule_check(FakeLLM(json.dumps(good)), self.ch["3.1"], rule), [])
        self.assertEqual(R.llm_rule_check(FakeLLM("```json\n" + json.dumps(good) + "\n```"), self.ch["3.1"], rule), [])
        bad = dict(good, strike=130)
        diffs = R.llm_rule_check(FakeLLM(json.dumps(bad)), self.ch["3.1"], rule)
        self.assertTrue(any("strike" in d for d in diffs))
        # garbage is not a disagreement: it raises, so the caller can tell "no opinion" from "different opinion"
        with self.assertRaises(R.LLMOutputError):
            R.llm_rule_check(FakeLLM("sorry, I cannot"), self.ch["3.1"], rule)
        with self.assertRaises(R.LLMOutputError):                     # valid JSON but wrong shape is also unusable
            R.llm_rule_check(FakeLLM('{"strike": "abc"}'), self.ch["3.1"], rule)


if __name__ == "__main__":
    unittest.main()
