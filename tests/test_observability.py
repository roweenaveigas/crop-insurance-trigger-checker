"""Review 3: trace metrics, CLI summaries and the Streamlit Trace tab (headless, via AppTest)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT, POLICY  # noqa: F401  (adds the project root to sys.path)

from crop_trigger import agent, cli, observability
from crop_trigger.tracing import Tracer


def run_case(cid):
    return cli._run_case(cid)


class TracerTimestamp(unittest.TestCase):
    def test_events_carry_optional_wall_clock_and_old_events_still_load(self):
        t = Tracer()
        e = t.event("node", "x", "hello")
        self.assertIn("ts", e)
        old = [{"step": 1, "kind": "decision", "node": "decide", "summary": "TRIGGER_MET; phases {}"}]   # no t_ms, no ts
        m = observability.run_metrics(old)
        self.assertEqual((m["steps"], m["seconds"], m["decision"]), (1, 0, "TRIGGER_MET"))
        self.assertEqual(observability.node_table(old)[0]["ms"], 0.0)

    def test_jsonl_round_trip(self):
        ev = run_case("F01")["tracer"].events
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            p.write_text(observability.events_to_jsonl(ev))
            self.assertEqual(observability.load_events(p), json.loads(json.dumps(ev, default=str)))


class Metrics(unittest.TestCase):
    def test_metrics_match_the_tracer_and_the_eval_definitions(self):
        s = run_case("F01")
        t = s["tracer"]
        m = observability.run_metrics(t.events)
        self.assertEqual(m["steps"], len(t.events))
        self.assertEqual(m["tool_calls"], t.count("tool") + t.count("retrieval"))     # same definition as eval/run_eval.py
        self.assertEqual(m["verify_loops"], 1)
        self.assertEqual(m["retrieval_rewrites"], sum(v["rewrites"] for v in s["retrievals"].values()))
        self.assertEqual(m["decision"], "TRIGGER_MET")
        self.assertTrue(m["plan"].endswith("compute -> verify"))

    def test_x01_reasons_and_node_table(self):
        ev = run_case("X01")["tracer"].events
        m = observability.run_metrics(ev)
        self.assertEqual(m["decision"], "CANNOT_DETERMINE")
        self.assertIn("station_disagreement", m["review_reasons"])
        rows = {r["node"]: r for r in observability.node_table(ev)}
        self.assertEqual(sum(r["events"] for r in rows.values()), len(ev))
        self.assertEqual(rows["verify"]["loops"], 0)

    def test_attempts_show_query_grade_and_rewrite(self):
        ev = [e for e in run_case("M01")["tracer"].events if e["kind"] == "retrieval" and len(e["data"]["attempts"]) > 1]
        self.assertTrue(ev)
        rows = observability.attempts_of(ev[0])
        self.assertEqual([r["kind"] for r in rows][:2], ["first query", "rewrite"])
        self.assertTrue(rows[0]["grade"].startswith("weak"))
        self.assertTrue(rows[1]["grade"].startswith("passed"))

    def test_flags(self):
        self.assertEqual(observability.flag_for({"kind": "loop"}), "LOOP")
        self.assertEqual(observability.flag_for({"kind": "guardrail"}), "GUARDRAIL")
        self.assertEqual(observability.flag_for({"kind": "tool"}), "")


class CliViews(unittest.TestCase):
    def test_compare_has_one_row_per_case(self):
        out = cli.compare_cases(["C01", "M01", "F01", "X01"])
        rows = [l for l in out.splitlines() if l.startswith("| ") and not l.startswith("| case")]
        self.assertEqual(len(rows), 4)
        self.assertIn("missing -> cross -> compute -> verify", out)
        self.assertIn("CANNOT_DETERMINE", out)

    def test_trace_summary_for_case_and_for_saved_file(self):
        self.assertIn("verify loops 1", cli.trace_summary("F01"))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            p.write_text(observability.events_to_jsonl(run_case("M01")["tracer"].events))
            out = cli.trace_summary(str(p))
        self.assertIn("rewrites 2", out)
        self.assertIn("| remediate |", out)


class StreamlitTraceTab(unittest.TestCase):
    """Headless only: AppTest runs the script, it does not render a browser page."""

    def run_app(self, cid):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
        label = next(o for o in at.sidebar.selectbox[0].options if o.startswith(cid + " "))
        at.sidebar.selectbox[0].select(label).run()
        at.sidebar.button[0].click().run()
        return at

    def test_all_four_demo_cases_render_the_trace_tab(self):
        for cid, decision, loops in (("C01", "TRIGGER_NOT_MET", 0), ("M01", "TRIGGER_NOT_MET", 0), ("F01", "TRIGGER_MET", 1),
                                     ("X01", "CANNOT_DETERMINE", 0)):
            with self.subTest(case=cid):
                at = self.run_app(cid)
                self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
                labels = {m.label: m.value for m in at.metric}
                self.assertEqual(labels["Final decision"], decision)
                self.assertEqual(labels["Verify loops"], str(loops))
                self.assertIn("Retrieval rewrites", labels)
                self.assertIn("Wall-clock (s)", labels)
                self.assertEqual(at.multiselect(key="trace_kinds").value[:2], ["plan", "retrieval"])
                self.assertTrue(any("attempt(s)" in x.label for x in at.expander))
                self.assertTrue(at.get("download_button"))

    def test_kind_filter_hides_other_kinds(self):
        at = self.run_app("F01")
        at.multiselect(key="trace_kinds").set_value(["loop"]).run()
        self.assertEqual(len(at.exception), 0)
        df = [d for d in at.dataframe if "flag" in d.value.columns][0].value
        self.assertEqual(set(df["kind"]), {"loop"})
        self.assertEqual(list(df["flag"]), ["LOOP"])


if __name__ == "__main__":
    unittest.main()
