"""Naive, non-agentic baseline used as the comparison arm of the experiment.

One fixed pass, no adaptation: parse the policy once, read the primary CSV, assume every number is mm,
fill missing days with 0, ignore the secondary station, never verify and never abstain.
(A reasonable first attempt at 'a script that checks the trigger'.)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from . import rag, rules as R
from .engine import D, apply_overall_cap, compute_phase


def run_baseline(policy_path, primary_csv) -> dict:
    text = Path(policy_path).read_text()
    chunks = {c.clause_id: c for c in rag.split_clauses(text)}
    dry = R.extract_dry_threshold(chunks["2.2"].text)
    rules = [R.extract_phase_rule(chunks[cid], i, dry) for i, cid in enumerate(["3.1", "3.2", "3.3"], 1)]
    cap = R.extract_overall_cap(chunks["5.1"].text)
    df = pd.read_csv(primary_csv, dtype=str, keep_default_na=False)
    series = {}
    for d, v in zip(pd.to_datetime(df["date"], errors="coerce"), df["rainfall"]):
        if pd.isna(d):
            continue
        try:
            series[d.date()] = Decimal(v)
        except InvalidOperation:
            series[d.date()] = D(0)          # blank -> 0
    out, total = {}, D(0)
    for r in rules:
        s = {d: series.get(d, D(0)) for d in r.window()}   # absent -> 0
        res = compute_phase(r, s)
        out[r.phase_id] = {"status": "MET" if res.triggered else "NOT_MET", "index": res.index, "payout": res.payout}
        total += res.payout
    decision = "TRIGGER_MET" if any(v["status"] == "MET" for v in out.values()) else "TRIGGER_NOT_MET"
    return {"decision": decision, "phase_final": out, "total_payout": apply_overall_cap(total, cap)}
