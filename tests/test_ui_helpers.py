"""Review 3 UI redesign: helpers that turn trace events into badges and story steps, plus headless AppTest checks
of the Streamlit page (no browser; AppTest runs the script and inspects the widgets)."""
import json
import unittest

from tests.helpers import ROOT, POLICY  # noqa: F401  (adds the project root to sys.path)

from crop_trigger import agent, cli, ui_helpers as ui
from tests.test_observability import pick_and_run

CASES = json.loads((ROOT / "data/cases.json").read_text())["cases"]
BADGE_LABELS = set(ui.BADGES)


def events(cid):
    return cli._run_case(cid)["tracer"].events


class Badges(unittest.TestCase):
    def test_every_story_step_has_one_of_the_six_badges(self):
        for cid in ("C01", "M01", "F01", "X01"):
            for s in ui.build_story(events(cid)):
                self.assertIn(s["badge"], BADGE_LABELS)

    def test_badge_for_maps_kinds(self):
        def mk(kind, node="n", summary="s"):
            return {"step": 1, "kind": kind, "node": node, "summary": summary}
        self.assertEqual(ui.badge_for(mk("plan")), "PLANNING")
        self.assertEqual(ui.badge_for(mk("tool", "calculator")), "TOOL USE")
        self.assertEqual(ui.badge_for(mk("retrieval", "rag")), "RAG")
        self.assertEqual(ui.badge_for(mk("loop", "verify")), "FEEDBACK LOOP")
        self.assertEqual(ui.badge_for(mk("guardrail", "x")), "GUARDRAIL")
        self.assertEqual(ui.badge_for(mk("decision", "decide")), "DECISION")
        self.assertEqual(ui.badge_for(mk("node", "remediate", "gap filling skipped: x")), "PLANNING")
        self.assertIsNone(ui.badge_for(mk("node", "intake")))

    def test_badge_html_always_contains_its_text(self):
        for label in BADGE_LABELS:
            self.assertIn(label, ui.badge_html(label))

    def test_row_flags(self):
        rows = ui.trace_rows(events("F01"))
        self.assertEqual({r["flag"] for r in rows if r["kind"] == "loop"}, {"LOOP"})
        self.assertIn("RAG REWRITE", {r["flag"] for r in rows})
        self.assertIn("GUARDRAIL", {r["flag"] for r in rows})


class Story(unittest.TestCase):
    def test_f01_has_the_91_to_90_loop(self):
        fb = ui.feedback_loops(events("F01"))
        self.assertEqual(len(fb), 1)
        self.assertEqual((fb[0]["attempt1"], fb[0]["verifier"], fb[0]["attempt2"]), ("91.0 mm", "90.0 mm", "90.0 mm"))
        self.assertTrue(fb[0]["fixed"])
        self.assertTrue(any(s["badge"] == "FEEDBACK LOOP" and s["highlight"] for s in ui.build_story(events("F01"))))

    def test_no_loop_in_other_demo_cases(self):
        for cid in ("C01", "M01", "X01"):
            self.assertEqual(ui.feedback_loops(events(cid)), [])
            self.assertFalse(any(s["badge"] == "FEEDBACK LOOP" for s in ui.build_story(events(cid))))

    def test_m01_story_shows_the_rewrite_with_every_attempt(self):
        rw = [s for s in ui.build_story(events("M01")) if s["kind"] == "rag_rewrite"]
        self.assertTrue(rw)
        rows = rw[0]["rows"]
        self.assertEqual([r["kind"] for r in rows], ["first query", "rewrite"])
        self.assertEqual((rows[0]["grade"], rows[1]["grade"], rows[1]["clause found"]), ("weak", "passed", "4.1"))

    def test_story_steps_point_at_real_trace_steps(self):
        ev = events("M01")
        valid = {e["step"] for e in ev}
        for s in ui.build_story(ev):
            self.assertTrue(s["steps"] and set(s["steps"]) <= valid)

    def test_story_uses_only_event_text(self):
        """A decision step carries the decision event's own text: nothing is hard-coded."""
        for cid in ("C01", "X01"):
            ev = events(cid)
            dec = next(e for e in ev if e["kind"] == "decision")
            step = next(s for s in ui.build_story(ev) if s["badge"] == "DECISION")
            self.assertEqual(step["detail"], dec["summary"])

    def test_x01_story_has_a_highlighted_guardrail_for_the_referral(self):
        g = [s for s in ui.build_story(events("X01")) if s["badge"] == "GUARDRAIL" and "HUMAN REVIEW" in s["title"]]
        self.assertTrue(g and g[0]["highlight"])

    def test_empty_trace(self):
        self.assertEqual(ui.build_story([]), [])
        self.assertEqual(ui.feedback_loops([]), [])


class Flow(unittest.TestCase):
    def test_dot_marks_ran_nodes_and_retry_edge(self):
        f = ui.flow_dot(events("F01"), agent.NODES, agent.EDGES)
        self.assertIn("RETRY (fired)", f)
        self.assertEqual(f.count("\\nran"), 12)
        c = ui.flow_dot(events("C01"), agent.NODES, agent.EDGES)
        self.assertIn("retry (not fired)", c)
        self.assertNotIn("RETRY (fired)", c)

    def test_halted_run_marks_skipped_nodes_not_run(self):
        ev = [{"step": 1, "kind": "node", "node": "intake", "summary": "x"},
              {"step": 2, "kind": "decision", "node": "decide", "summary": "CANNOT_DETERMINE"}]
        self.assertIn("compute\\nnot run", ui.flow_dot(ev, agent.NODES, agent.EDGES))

    def test_nodes_ran_order_includes_retry(self):
        seq = ui.nodes_ran(events("F01"))
        self.assertEqual(seq.count("compute"), 2)
        self.assertEqual(seq[:3], ["intake", "retrieve_rules", "load_validate"])


class Cards(unittest.TestCase):
    def test_case_groups_pin_demo_cases_and_cover_all_cases(self):
        g = ui.case_groups(CASES)
        self.assertEqual(list(g)[0], "Demo cases")
        self.assertEqual([lab.split(" ")[0] for lab, _ in g["Demo cases"]], ["C01", "M01", "F01", "X01"])
        self.assertEqual(sum(len(v) for k, v in g.items() if k != "Demo cases"), len(CASES))

    def test_verdict_card_has_text_label_and_flag(self):
        h = ui.verdict_html("CANNOT_DETERMINE", "summary", None, True, [{"detail": "stations disagree"}])
        self.assertIn("CANNOT_DETERMINE", h)
        self.assertIn("FLAGGED FOR HUMAN REVIEW", h)
        self.assertIn("No payout figure", h)
        self.assertNotIn("FLAGGED", ui.verdict_html("TRIGGER_MET", "s", "9000.00", False))

    def test_html_is_escaped(self):
        self.assertNotIn("<script>", ui.verdict_html("TRIGGER_MET", "<script>x</script>", "1", False))

    def test_phase_card_for_undetermined_phase(self):
        c = ui.phase_card({"phase": "P1", "name": "N", "clause": "3.1", "status": "UNDETERMINED", "strike": "120",
                           "why": "station_disagreement"}, {"3.1": "text"})
        self.assertEqual((c["index"], c["status"], c["payout"]), ("not computed", "UNDETERMINED", "not stated"))

    def test_md_section_and_first_table(self):
        md = "# T\n\n## A\n\n| x |\n|---|\n| 1 |\n\ntext\n\n## B\n\n| y |\n"
        self.assertEqual(ui.first_table(ui.md_section(md, "A")), "| x |\n|---|\n| 1 |")
        self.assertEqual(ui.md_section(md, "missing"), "")
        head = ui.first_table(ui.md_section((ROOT / "eval/results.md").read_text(encoding="utf8"), "Headline comparison"))
        self.assertIn("Naive baseline", head)


class StreamlitPage(unittest.TestCase):
    """Headless: AppTest executes app.py and inspects widgets. Not a browser."""

    @staticmethod
    def page_text(at):
        parts = [m.value for m in at.markdown] + [i.value for i in at.info] + [c.value for c in at.caption]
        parts += [m.value for m in at.metric] + [m.label for m in at.metric]
        for d in at.dataframe:
            parts.append(d.value.to_string())
        return "\n".join(map(str, parts))

    def run_case(self, cid):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
        return pick_and_run(at, cid)

    def test_demo_cases_and_one_per_category_render_without_exceptions(self):
        first = {}
        for c in CASES:
            first.setdefault(c["category"], c["id"])
        for cid in sorted({"C01", "M01", "F01", "X01"} | set(first.values())):
            with self.subTest(case=cid):
                at = self.run_case(cid)
                self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
                self.assertEqual(len(at.error), 0, [e.value for e in at.error])
                self.assertEqual(len(at.tabs), 6)
                self.assertTrue(any("TRIGGER" in m.value or "CANNOT_DETERMINE" in m.value for m in at.markdown))

    def test_f01_page_shows_the_loop_91_to_90(self):
        at = self.run_case("F01")
        labels = {m.label: m.value for m in at.metric}
        self.assertEqual(labels["P1: attempt 1 (calculator)"], "91.0 mm")
        self.assertEqual(labels["Verifier says"], "90.0 mm")
        self.assertEqual(labels["P1: attempt 2 (recompute)"], "90.0 mm")
        self.assertIn("FEEDBACK LOOP", self.page_text(at))
        self.assertNotIn("No feedback loop was needed", self.page_text(at))

    def test_m01_page_shows_a_retrieval_rewrite(self):
        at = self.run_case("M01")
        txt = self.page_text(at)
        self.assertIn("needed a rewrite", txt)
        self.assertIn("RAG REWRITE", txt)
        self.assertIn("No feedback loop was needed in this case.", txt)

    def test_x01_page_is_flagged_for_human_review(self):
        at = self.run_case("X01")
        self.assertTrue(any("FLAGGED FOR HUMAN REVIEW" in m.value for m in at.markdown))

    def test_switching_widgets_does_not_rerun_the_agent(self):
        at = self.run_case("F01")
        run_id = at.session_state["state"]["tracer"].run_id
        at.multiselect(key="trace_kinds").set_value(["loop"]).run()
        self.assertEqual(at.session_state["state"]["tracer"].run_id, run_id)

    def test_compare_tab_matches_cli_compare(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
        at.sidebar.button(key="run_all_btn").click().run()
        self.assertEqual(len(at.exception), 0)
        cli_md = cli.compare_cases(["C01", "M01", "F01", "X01"])
        for r in at.session_state["compare_rows"]:
            line = f"| {r['case']} | {r['plan']} | {r['steps']} | {r['tool_calls']} | {r['rewrites']} | {r['loops']} | {r['decision']} |"
            self.assertIn(line, cli_md)

    def test_evaluation_tab_shows_headline_and_ablation_from_files(self):
        txt = self.page_text(self.run_case("C01"))
        self.assertIn("Naive baseline", txt)
        self.assertIn("agent_no_plan", txt)


if __name__ == "__main__":
    unittest.main()
