"""Review 3: the held-out retrieval scaffold. Fixture questions here only exercise the plumbing; they are NOT the held-out set."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT

sys.path.insert(0, str(ROOT / "eval"))
import retrieval_eval as RE  # noqa: E402

TEMPLATE = ROOT / "eval" / "heldout_questions_TEMPLATE.csv"


class Template(unittest.TestCase):
    def test_template_has_the_required_columns_and_three_labelled_examples(self):
        rows, ignored = RE.load_heldout(TEMPLATE)
        self.assertEqual(rows, [])                      # all three rows are EXAMPLE rows and are ignored
        self.assertEqual(ignored, 3)
        header = TEMPLATE.read_text().splitlines()[0]
        self.assertEqual(header, "id,question,expected_clause,written_by")
        self.assertTrue(all("EXAMPLE" in line for line in TEMPLATE.read_text().splitlines()[1:]))

    def test_real_heldout_file_is_not_committed_by_the_scaffold(self):
        # the teammate creates eval/heldout_questions.csv; the scaffold must not ship one
        if (ROOT / "eval" / "heldout_questions.csv").exists():
            self.skipTest("a teammate has already added eval/heldout_questions.csv")


class Section(unittest.TestCase):
    ROWS = [{"id": "t1", "question": "what counts as a rainless day", "expected_clause": "2.2", "written_by": "test fixture"},
            {"id": "t2", "question": "which company underwrites this policy", "expected_clause": "NONE", "written_by": "test fixture"}]

    def test_section_reports_both_methods_and_counts(self):
        text = "\n".join(RE.heldout_section(self.ROWS))
        self.assertIn("1 in-scope and 1 out-of-scope", text)
        self.assertIn("| In-scope: correct clause |", text)
        self.assertIn("| Out-of-scope: correctly says 'not found' |", text)
        self.assertIn("100% (1/1)", text)                # the agentic loop finds 2.2 and finds nothing for the insurer question

    def test_missing_file_prints_a_note_and_carries_on(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "eval").mkdir()
            old, RE.ROOT = RE.ROOT, Path(d)
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    RE.main()
            finally:
                RE.ROOT = old
            self.assertIn("heldout_questions.csv not found", buf.getvalue())
            self.assertTrue((Path(d) / "eval" / "retrieval_results.md").exists())
            self.assertFalse((Path(d) / "eval" / "heldout_retrieval_results.md").exists())

    def test_present_file_gets_its_own_section_and_file(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "eval").mkdir()
            csv_text = "id,question,expected_clause,written_by\n" + "\n".join(
                f"{r['id']},{r['question']},{r['expected_clause']},{r['written_by']}" for r in self.ROWS) + "\nEX,example row,2.2,EXAMPLE - delete\n"
            (Path(d) / "eval" / "heldout_questions.csv").write_text(csv_text)
            old, RE.ROOT = RE.ROOT, Path(d)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    RE.main()
            finally:
                RE.ROOT = old
            out = (Path(d) / "eval" / "heldout_retrieval_results.md").read_text()
            self.assertIn("1 EXAMPLE row(s) ignored", out)
            self.assertNotIn("Held-out", (Path(d) / "eval" / "retrieval_results.md").read_text())


if __name__ == "__main__":
    unittest.main()
