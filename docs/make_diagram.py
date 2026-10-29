"""Draws docs/architecture.png (agent graph + components). Run from the project root: python docs/make_diagram.py

The halt and skip arrows are read from EDGES in crop_trigger/agent.py, so the picture follows the code."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crop_trigger.agent import EDGES

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

fig, ax = plt.subplots(figsize=(15, 8.2))
ax.set_xlim(0, 15)
ax.set_ylim(0, 8.2)
ax.axis("off")

C = {"node": "#E8F0FE", "tool": "#E6F4EA", "guard": "#FEF7E0", "store": "#F3E8FD", "edge": "#3C4043"}


def box(x, y, w, h, text, color, bold=False, fs=9):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", fc=color, ec=C["edge"], lw=1))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, fontweight="bold" if bold else "normal", wrap=True)


def arrow(x1, y1, x2, y2, text=None, style="-|>", rad=0.0, color=None, dy=0.0):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color or C["edge"], lw=1.2, connectionstyle=f"arc3,rad={rad}"))
    if text:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + dy, text, fontsize=7.5, ha="center", va="center", color=color or C["edge"],
                bbox=dict(fc="white", ec="none", pad=0.5))


ax.text(7.5, 7.9, "Parametric Crop-Insurance Trigger Checker: agent graph", ha="center", fontsize=14, fontweight="bold")
ax.text(7.5, 7.55, "orange = guardrail / escalation path     blue = agent node     green = tool or deterministic component     purple = data", ha="center", fontsize=8.5)

# main row 1
row1 = [("1 intake\nvalidate inputs", 0.3), ("2 retrieve_rules\nagentic RAG: phases,\nstations, cap, dry day", 2.55),
        ("3 load_validate\nread + profile CSVs", 4.95), ("4 make_plan\ndata-driven plan\n(units? gaps? cross?)", 7.2),
        ("5 retrieve_support\nonly the clauses the\nplan needs", 9.6), ("6 remediate\nconvert units, fill <=3 gaps\nfrom secondary or abstain", 12.0)]
w, h, y1 = 2.2, 1.0, 5.6
for t, x in row1:
    box(x, y1, w, h, t, C["node"], fs=8.5)
for i in range(len(row1) - 1):
    arrow(row1[i][1] + w, y1 + h / 2, row1[i + 1][1], y1 + h / 2)
arrow(0.3 + w / 2, 6.95, 0.3 + w / 2, y1 + h, None)
ax.text(0.3 + w / 2 + 0.1, 6.95, "policy text + 2 station CSVs", fontsize=8, va="bottom")

# row 2 (right to left)
row2 = [("7 compute\ndeterministic engine", 12.0), ("8 verify\nindependent recompute,\ninvariants, rule grounding", 9.3),
        ("9 cross_check\nprimary vs secondary\ntrigger outcomes", 6.6), ("10 decide\nMET / NOT MET /\nCANNOT DETERMINE", 3.9), ("11 human_gate\nflagged and referred\n(AWAITING_HUMAN_REVIEW;\nthe run does not wait)", 1.3)]
y2 = 3.5
for t, x in row2:
    box(x, y2, w, h, t, C["node"], fs=7.5 if "human_gate" in t else 8.5)
arrow(13.1, y1, 13.1, y2 + h)
for i in range(len(row2) - 1):
    arrow(row2[i][1], y2 + h / 2, row2[i + 1][1] + w, y2 + h / 2)
# retry loop 8 -> 7
arrow(10.4, y2 + h, 12.3, y2 + h, None, rad=-0.55, color="#B06000")
ax.text(11.9, 5.2, "mismatch: retry\n(max 2 attempts)", fontsize=7.5, ha="center", va="center", color="#B06000")
box(0.3, 1.5, 2.2, 1.0, "12 write_report\ncited clauses, steps,\nassumptions, next steps", C["node"], fs=8.5)
arrow(2.4, y2, 1.4, 2.5)
ax.text(0.4, 0.95, "END: report + JSON record", fontsize=8.5)
arrow(1.4, 1.5, 1.4, 1.1)

# guardrail halt path, derived from EDGES: nodes whose router can go straight to decide
xc = {t.split("\n")[0].split(" ", 1)[1]: x + w / 2 for t, x in row1 + row2}
halt_from = [n for n, (_, tg) in EDGES.items() if len(tg) == 2 and tg[0] == "decide"]
bus_y = 5.0
ORANGE = "#B06000"
xs = [xc[n] for n in halt_from]
ax.plot([min(xs), max(xs)], [bus_y, bus_y], color=ORANGE, lw=1.2)
for n in halt_from:
    ax.plot([xc[n], xc[n]], [y1, bus_y], color=ORANGE, lw=1.2)
arrow(xc["decide"], bus_y, xc["decide"], y2 + h, None, color=ORANGE)
ax.plot([xc["decide"], xc["decide"]], [bus_y, bus_y], color=ORANGE)
ax.text(5.5, bus_y - 0.12, "halt -> decide: " + ", ".join(halt_from), fontsize=7, color=ORANGE, va="top")
box(5.2, 1.5, 4.6, 1.0, "halt -> decide: any node that cannot continue safely\n(input missing, clause not found, rule not grounded,\nstep cap exceeded) abstains and explains", C["guard"], fs=8)
# skip edge verify -> decide (plan has no 'cross' step), drawn below row 2
if "decide" in EDGES["verify"][1]:
    arrow(xc["verify"], y2, xc["decide"] + 0.4, y2, None, rad=-0.22, color=ORANGE)
    ax.text(7.9, 3.2, "no 'cross' in plan: verify -> decide", fontsize=7.5, ha="center", va="center", color=ORANGE, bbox=dict(fc="white", ec="none", pad=0.5))

# components
box(10.2, 1.5, 2.1, 1.0, "Policy KB\nclause chunks + BM25\n(retrieve, grade,\nrewrite, abstain)", C["store"], fs=8)
box(12.5, 1.5, 2.2, 1.0, "Tracer\nevery step -> JSONL\n(traces/)", C["tool"], fs=8)
box(10.2, 0.15, 2.1, 1.0, "Optional LLM\nrule cross-check +\nsummary (guarded)", C["tool"], fs=8)
box(12.5, 0.15, 2.2, 1.0, "Human review\naudit trail (runs/)", C["guard"], fs=8)
box(5.2, 0.15, 4.6, 1.0, "Deterministic engine (Decimal, no LLM) + independent verifier\nuse different algorithms, so one bug cannot hide in both", C["tool"], fs=8)
plt.savefig("docs/architecture.png", dpi=170, bbox_inches="tight", facecolor="white")
print("saved")
