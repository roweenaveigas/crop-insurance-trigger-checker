"""UI theme (presentation only): CSS contents, Streamlit theme config, and the card/badge classes emitted by ui_helpers."""
import tomllib
import unittest
from unittest import mock

from tests.helpers import ROOT, POLICY  # noqa: F401  (adds the project root to sys.path)

from crop_trigger import theme, ui_helpers as ui


class ThemeCss(unittest.TestCase):
    def test_css_has_palette_fonts_and_card_classes(self):
        for token in ("#FAF6EC", "#EFE8D2", "#2B2A22", "#1F4D2B", "#C9A227", "#DCD3B4", "#173B21",
                      "Fraunces", "DM Sans", "Georgia", "sans-serif", ".card.notmet", ".card.met", ".card.review",
                      "#E4F1E0", "#4B8059", "#FBE9D0", "#D98E3F", "#EFE3F3", "#8E5FA3", "#FFFDF6"):
            self.assertIn(token, theme.CSS, token)

    def test_fonts_are_imported_and_not_applied_with_a_wildcard(self):
        self.assertTrue(theme.CSS.startswith("@import url('https://fonts.googleapis.com/css2?family=DM+Sans"))
        import re
        wildcard_rules = re.findall(r"(?:^|,)\s*\*\s*\{[^}]*\}", theme.CSS, flags=re.M)
        self.assertEqual(wildcard_rules, [])   # a bare `*` font rule would break the Material icon glyphs

    def test_apply_theme_injects_one_style_block(self):
        with mock.patch("streamlit.markdown") as md:
            theme.apply_theme()
        md.assert_called_once()
        self.assertTrue(md.call_args.args[0].startswith("<style>"))
        self.assertTrue(md.call_args.kwargs["unsafe_allow_html"])

    def test_streamlit_config_theme(self):
        cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())["theme"]
        self.assertEqual(cfg, {"base": "light", "primaryColor": "#2F6B3A", "backgroundColor": "#FAF6EC",
                               "secondaryBackgroundColor": "#EFE8D2", "textColor": "#2B2A22", "font": "sans serif"})


class CardClasses(unittest.TestCase):
    def test_verdict_class_follows_meaning_and_keeps_text(self):
        for decision, cls, label in (("TRIGGER_NOT_MET", "notmet", "Trigger not met"), ("TRIGGER_MET", "met", "Trigger met"),
                                     ("CANNOT_DETERMINE", "review", "Cannot determine")):
            h = ui.verdict_html(decision, "s", None, decision == "CANNOT_DETERMINE")
            self.assertIn(f'class="card verdict {cls}"', h)
            self.assertIn(decision, h)
            self.assertIn(label, h)

    def test_phase_card_class_and_emoji_in_separate_element(self):
        base = {"phase": "P1", "name": "Crop Establishment", "clause": "3.1", "strike": "120", "index": "90.0", "unit": "mm", "payout": "9000.00"}
        for status, cls in (("MET", "met"), ("NOT_MET", "notmet"), ("UNDETERMINED", "review")):
            card = ui.phase_card({**base, "status": status}, {})
            self.assertNotIn(card["emoji"], card["title"])          # titles keep their exact text
            html = ui.phase_card_html(card)
            self.assertIn(f'class="card phase {cls}"', html)
            self.assertIn('<span class="phase-emoji">', html)
            self.assertIn(card["status"], html)
        self.assertEqual([ui.PHASE_EMOJI[k] for k in ("P1", "P2", "P3")], ["\U0001F331", "\U0001F33F", "\U0001F33C"])

    def test_no_inline_blue_or_old_palette_left_in_cards_and_badges(self):
        html = (ui.verdict_html("TRIGGER_NOT_MET", "s", "0", False) + ui.badge_html("TOOL USE")
                + ui.phase_card_html(ui.phase_card({"phase": "P2", "name": "x", "clause": "3.2", "status": "NOT_MET", "strike": "15"}, {})))
        for old in ("#BBDEFB", "#C8E6C9", "#FFE0B2", "style="):
            self.assertNotIn(old, html)

    def test_badge_has_class_and_text(self):
        for label, cls in ui.BADGES.items():
            h = ui.badge_html(label)
            self.assertIn(f'class="badge {cls}"', h)
            self.assertIn(label, h)


if __name__ == "__main__":
    unittest.main()
