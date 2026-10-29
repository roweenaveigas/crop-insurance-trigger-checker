"""Visual theme for the Streamlit UI: a crop-themed "field notes" look (cream paper, forest green, wheat gold).

Presentation only. `apply_theme()` injects one CSS block; the card and badge classes it styles (`.card.met`,
`.card.notmet`, `.card.review`, `.badge.*`, `.notice`) are emitted by `ui_helpers`. Colour never carries meaning alone:
every card and badge also prints its label as text.
"""
from __future__ import annotations

PALETTE = {"paper": "#FAF6EC", "paper2": "#EFE8D2", "ink": "#2B2A22", "green": "#1F4D2B", "green_dark": "#173B21",
           "gold": "#C9A227", "border": "#DCD3B4"}

FONTS_IMPORT = ("@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600"
                "&family=Fraunces:wght@600;700&display=swap');")
HEADING_FONT = "'Fraunces', Georgia, 'Times New Roman', serif"
BODY_FONT = "'DM Sans', 'Segoe UI', Arial, sans-serif"

CSS = FONTS_IMPORT + """
:root { --paper:#FAF6EC; --paper2:#EFE8D2; --ink:#2B2A22; --green:#1F4D2B; --green-dark:#173B21; --gold:#C9A227; --line:#DCD3B4; }
html, body, .stApp { background: var(--paper); color: var(--ink); }
body, p, li, label, td, th, button, input, textarea, [data-testid="stMarkdownContainer"],
[data-testid="stCaptionContainer"], [data-testid="stMetricLabel"], [data-baseweb="tab"] { font-family: %(body)s; }
h1, h2, h3, h4, [data-testid="stMarkdownContainer"] h1, [data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3, [data-testid="stMarkdownContainer"] h4 {
  font-family: %(head)s; font-weight: 700; color: var(--green); letter-spacing: -0.01em; }
.block-container { padding-top: 1.6rem; max-width: 100%%; }
[data-testid="stMetricValue"] { font-size: 2rem; font-family: %(head)s; font-weight: 600; color: var(--green); }
[data-testid="stHeader"] { background: var(--paper); }
code, [data-testid="stMarkdownContainer"] code { background: #EFE8D2 !important; color: #5A3E1B !important; border-radius: 6px; padding: 1px 6px; }

/* tabs */
[data-baseweb="tab"] { font-weight: 600; font-size: 1.02rem; }
[data-baseweb="tab-highlight"] { background-color: var(--gold) !important; height: 3px; }
button[data-baseweb="tab"][aria-selected="true"] { color: var(--green); }

/* sidebar */
[data-testid="stSidebar"] { background: linear-gradient(180deg, #1F4D2B 0%%, #173B21 100%%); }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] label,
[data-testid="stSidebar"] p, [data-testid="stSidebar"] li, [data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
[data-testid="stSidebar"] [data-testid="stCaptionContainer"], [data-testid="stSidebar"] [data-testid="stWidgetLabel"] { color: #FAF6EC; }
[data-testid="stSidebar"] [data-baseweb="select"] > div { border-radius: 10px; background: #FAF6EC; color: #2B2A22; border-color: var(--gold); }
[data-testid="stSidebar"] [data-baseweb="select"] * { color: #2B2A22; }
[data-testid="stSidebar"] [data-testid="stAlert"] { background: rgba(250,246,236,0.14); color: #FAF6EC; border-radius: 10px; }
[data-testid="stSidebar"] [data-testid="stAlert"] * { color: #FAF6EC; }
[data-testid="stSidebar"] [data-testid="stExpander"] { border: 1px solid rgba(250,246,236,0.35); border-radius: 10px; }
[data-testid="stSidebar"] [data-testid="stExpander"] * { color: #FAF6EC; }

/* buttons: gold primary, outlined secondary */
button[kind="primary"], [data-testid="stBaseButton-primary"] {
  background: var(--gold); color: #2B2A22; border: 1px solid #A8851C; border-radius: 10px; font-weight: 700; }
button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover { background: #D8B33A; color: #2B2A22; border-color: #A8851C; }
button[kind="primary"]:disabled, [data-testid="stBaseButton-primary"]:disabled { background: #E3D9A8; color: #6b684f; }
button[kind="secondary"], [data-testid="stBaseButton-secondary"] { border-radius: 10px; font-weight: 600; }
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] { background: transparent; color: #FAF6EC; border: 1px solid #FAF6EC; }
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] p { color: #FAF6EC; }

[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] *, [data-testid="stBaseButton-primary"] * { color: #2B2A22 !important; }
[data-testid="stMain"] [data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]) { background: #E4EEDF; color: #1F4D2B; border-radius: 12px; }
[data-testid="stMain"] [data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]) * { color: #1F4D2B; }

/* notice, cards, badges */
.notice { display: inline-block; background: #FBF3CF; color: var(--ink); border-left: 6px solid var(--gold); border-radius: 10px;
  padding: 6px 14px; font-weight: 600; box-shadow: 0 1px 3px rgba(60,50,20,0.12); }
.card { background: #FFFDF6; color: var(--ink); border: 2px solid var(--line); border-radius: 16px; padding: 12px 16px;
  box-shadow: 0 2px 8px rgba(60,50,20,0.10); }
.card.notmet { background: #E4F1E0; border-color: #4B8059; }
.card.met { background: #FBE9D0; border-color: #D98E3F; }
.card.review { background: #EFE3F3; border-color: #8E5FA3; }
.card.verdict { border-width: 4px; padding: 14px 22px; }
.verdict-title { font-family: %(head)s; font-size: 2.2rem; font-weight: 700; line-height: 1.1; color: var(--ink); }
.verdict-label { font-size: 1.2rem; font-weight: 600; }
.verdict-pay { font-size: 1.15rem; margin-top: 6px; }
.verdict-summary { margin-top: 4px; }
.phase-cited { font-size: 0.95rem; }
.verdict-flag { margin-top: 8px; font-weight: 700; font-size: 1.15rem; }
.card.phase { min-height: 190px; }
.phase-title { font-weight: 700; }
.phase-status { font-family: %(head)s; font-size: 1.35rem; font-weight: 700; }
.phase-emoji { font-size: 1.3rem; margin-right: 6px; }
.badge { color: #2B2A22; padding: 2px 10px; border-radius: 10px; font-weight: 700; font-size: 0.85rem; border: 1px solid #0003; white-space: nowrap; }
.badge.planning { background: #E3D3EC; }
.badge.tooluse { background: #D6E4EF; }
.badge.rag { background: #D5E8CC; }
.badge.loop { background: #F6CF8E; }
.badge.guardrail { background: #F3C9C4; }
.badge.decision { background: #F3E39A; }

/* story */
.story-step, .story-detail { font-size: 1.05rem; }
.story-step { padding: 6px 0 2px 0; border-top: 1px solid var(--line); }
.story-detail { font-size: 0.95rem; opacity: 0.9; margin: 2px 0 4px 4px; }
.story-hl { background: #F6CF8E44; border-left: 5px solid #D98E3F; padding-left: 8px; }
""" % {"head": HEADING_FONT, "body": BODY_FONT}


def apply_theme() -> None:
    """Inject the theme CSS into the page (call once, right after `st.set_page_config`)."""
    import streamlit as st
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)
