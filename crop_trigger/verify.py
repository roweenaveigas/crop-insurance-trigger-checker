"""Independent verifier: recomputes every result with *different algorithms* and checks invariants.

If the main calculator and this module disagree, the agent retries and then escalates.
It also checks that every number in an extracted rule literally appears in the cited clause text
(grounding), so a mis-parsed or hallucinated threshold cannot slip through.
"""
from __future__ import annotations

import re
from decimal import Decimal

from .engine import D, PhaseResult, PhaseRule, q2


def recompute(rule: PhaseRule, series: dict) -> tuple[Decimal, bool, Decimal]:
    """Return (index, triggered, payout) using algorithms different from engine.compute_phase."""
    vals = [series[d] for d in rule.window()]
    if rule.index_type == "cumulative_deficit":
        total = D(0)
        for v in reversed(vals):          # summed in the opposite order
            total += v
        trig = not (total >= rule.strike)
        pay = D(0)
        if trig:
            pay = q2(min((rule.strike - total) * rule.rate, rule.cap))
        return total, trig, pay

    if rule.index_type == "dry_spell":
        s = "".join("D" if v < rule.dry_day_threshold else "W" for v in vals)   # run-length via regex
        runs = re.findall(r"D+", s)
        longest = max((len(r) for r in runs), default=0)
        idx = D(longest)
        trig = idx >= rule.strike
        pay = D(0)
        if trig:
            for slab in rule.slabs:
                if slab.contains(idx):
                    pay = q2(rule.sum_insured * slab.pct / 100)
        return idx, trig, pay

    if rule.index_type == "excess_3day":
        ps = [D(0)]
        for v in vals:                     # prefix sums instead of direct window sums
            ps.append(ps[-1] + v)
        idx = max(ps[i + 3] - ps[i] for i in range(len(vals) - 2))
        trig = idx > rule.strike
        pay = D(0)
        if trig:
            for slab in rule.slabs:
                if slab.contains(idx):
                    pay = q2(rule.sum_insured * slab.pct / 100)
        return idx, trig, pay

    raise ValueError(rule.index_type)


def check_result(rule: PhaseRule, series: dict, res: PhaseResult) -> list[str]:
    """Return a list of problems (empty list = verified)."""
    problems = []
    idx, trig, pay = recompute(rule, series)
    if idx != res.index:
        problems.append(f"{rule.phase_id}: index mismatch (calculator {res.index} vs verifier {idx})")
    if trig != res.triggered:
        problems.append(f"{rule.phase_id}: trigger mismatch (calculator {res.triggered} vs verifier {trig})")
    if pay != res.payout:
        problems.append(f"{rule.phase_id}: payout mismatch (calculator {res.payout} vs verifier {pay})")
    # invariants
    if res.payout < 0:
        problems.append(f"{rule.phase_id}: negative payout")
    if res.triggered and res.payout <= 0:
        problems.append(f"{rule.phase_id}: triggered but payout is zero")
    if not res.triggered and res.payout != 0:
        problems.append(f"{rule.phase_id}: not triggered but payout is non-zero")
    ceiling = rule.cap if rule.index_type == "cumulative_deficit" else rule.sum_insured
    if ceiling is not None and res.payout > ceiling:
        problems.append(f"{rule.phase_id}: payout {res.payout} exceeds phase ceiling {ceiling}")
    return problems


def _numbers(text: str) -> set[str]:
    """All numbers in text, normalised (commas removed, trailing .0 removed)."""
    out = set()
    for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        m = m.replace(",", "")
        out.add(m)
        if "." in m:
            out.add(m.rstrip("0").rstrip("."))
    return out


def _norm(x) -> str:
    s = format(Decimal(x).normalize(), "f")
    return s


def grounding_problems(rule: PhaseRule, clause_text: str, dry_clause_text: str = "") -> list[str]:
    """Every threshold, rate, cap and slab number in the rule must appear in the cited clause text."""
    nums = _numbers(clause_text)
    wanted = {"strike": rule.strike, "exit": rule.exit_value, "rate": rule.rate,
              "cap": rule.cap, "sum insured": rule.sum_insured}
    problems = []
    for label, val in wanted.items():
        if val is not None and _norm(val) not in nums:
            problems.append(f"{rule.phase_id}: {label} {val} not found in clause {rule.clause_id}")
    for s in rule.slabs:
        for label, val in (("slab pct", s.pct), ("slab lower", s.lower), ("slab upper", s.upper)):
            if val is not None and _norm(val) not in nums:
                problems.append(f"{rule.phase_id}: {label} {val} not found in clause {rule.clause_id}")
    if rule.dry_day_threshold is not None and _norm(rule.dry_day_threshold) not in _numbers(dry_clause_text):
        problems.append(f"{rule.phase_id}: dry-day threshold {rule.dry_day_threshold} not found in dry-day clause")
    return problems
