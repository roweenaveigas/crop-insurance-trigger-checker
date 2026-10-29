"""Hand-verified arithmetic. Expected numbers below were worked out by hand from the policy text, not from the code."""
import unittest
from decimal import Decimal as D

from tests.helpers import policy_rules, series_for
from crop_trigger import engine, verify as V


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.p1, self.p2, self.p3 = policy_rules()

    def p1_total(self, total):
        # 31 days: put the whole total on day 1, zeros elsewhere
        return series_for(self.p1, [total] + [0] * 30)

    def test_p1_shortfall_payout(self):
        r = engine.compute_phase(self.p1, self.p1_total("90.0"))       # (120-90) x 300 = 9000
        self.assertEqual((r.index, r.triggered, r.payout), (D("90.0"), True, D("9000.00")))

    def test_p1_boundary_exactly_at_strike_is_not_triggered(self):
        r = engine.compute_phase(self.p1, self.p1_total("120.0"))
        self.assertFalse(r.triggered)
        self.assertEqual(r.payout, 0)

    def test_p1_just_below_strike(self):
        r = engine.compute_phase(self.p1, self.p1_total("119.9"))      # 0.1 x 300 = 30
        self.assertEqual((r.triggered, r.payout), (True, D("30.00")))

    def test_p1_cap(self):
        r = engine.compute_phase(self.p1, self.p1_total("50.0"))       # 70 x 300 = 21000 -> capped 18000
        self.assertEqual(r.payout, D("18000.00"))

    def test_decimal_sum_has_no_float_error(self):
        r = engine.compute_phase(self.p1, series_for(self.p1, ["0.1"] * 31))
        self.assertEqual(r.index, D("3.1"))

    def dry(self, n, wet_between=None):
        vals = ["1.0"] * n + ["5.0"] + ["1.0"] * 0
        return series_for(self.p2, vals)

    def test_dry_spell_boundaries(self):
        cases = [(14, False, 0), (15, True, D("7500.00")), (19, True, D("7500.00")), (20, True, D("15000.00")), (30, True, D("15000.00"))]
        for n, trig, pay in cases:
            with self.subTest(days=n):
                r = engine.compute_phase(self.p2, self.dry(n))
                self.assertEqual((r.index, r.triggered, r.payout), (D(n), trig, D(pay)))

    def test_dry_day_threshold_is_strictly_less_than(self):
        vals = ["1.0"] * 14 + ["2.5"] + ["1.0"] * 14                 # the 2.5 mm day is wet -> longest run 14
        r = engine.compute_phase(self.p2, series_for(self.p2, vals))
        self.assertEqual(r.index, D(14))
        self.assertFalse(r.triggered)

    def storm(self, a, b, c):
        return series_for(self.p3, ["1.0"] * 5 + [a, b, c])

    def test_excess_rain_bands(self):
        cases = [("250.0", False, 0), ("250.1", True, D("8000.00")), ("350.0", True, D("8000.00")),
                 ("350.1", True, D("20000.00"))]
        for total, trig, pay in cases:
            with self.subTest(total=total):
                t = D(total)
                r = engine.compute_phase(self.p3, self.storm(t / 3, t / 3, t - 2 * (t / 3)))
                self.assertEqual((r.index, r.triggered, r.payout), (t, trig, D(pay)))

    def test_missing_day_raises(self):
        s = self.p1_total("100")
        del s[self.p1.start]
        with self.assertRaises(engine.MissingDataError) as cm:
            engine.compute_phase(self.p1, s)
        self.assertEqual(cm.exception.missing, [self.p1.start])

    def test_overall_cap(self):
        self.assertEqual(engine.apply_overall_cap(D("70000"), D("68000")), D("68000.00"))
        self.assertEqual(engine.apply_overall_cap(D("100"), D("68000")), D("100.00"))


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.p1, self.p2, self.p3 = policy_rules()

    def test_verifier_agrees_with_engine_on_all_phases(self):
        for rule, series in ((self.p1, series_for(self.p1, ["3.0"] * 31)),
                             (self.p2, series_for(self.p2, ["1.0"] * 22)),
                             (self.p3, series_for(self.p3, ["1.0"] * 5 + ["120", "100", "90"]))):
            res = engine.compute_phase(rule, series)
            self.assertEqual(V.check_result(rule, series, res), [], rule.phase_id)

    def test_verifier_catches_wrong_index(self):
        s = series_for(self.p1, ["3.0"] * 31)
        bad = engine.FaultyCalculator("persistent")(self.p1, s)
        self.assertTrue(any("index mismatch" in p for p in V.check_result(self.p1, s, bad)))

    def test_grounding_detects_a_rule_number_not_in_the_clause(self):
        from dataclasses import replace
        text = "Strike: 120 mm. Exit: 60 mm. INR 300 for each mm, up to a maximum of INR 18,000."
        self.assertEqual(V.grounding_problems(self.p1, text), [])
        tampered = replace(self.p1, strike=D("130"))
        self.assertTrue(V.grounding_problems(tampered, text))


if __name__ == "__main__":
    unittest.main()
