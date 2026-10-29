"""Deterministic index / trigger / payout engine.

No LLM is ever involved in arithmetic. All numbers are `Decimal` so that boundary
cases (for example exactly 120.0 mm against a strike of 120 mm) are exact.

A `series` is a plain dict: {datetime.date: Decimal rainfall in mm}.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

D = Decimal
INDEX_TYPES = ("cumulative_deficit", "dry_spell", "excess_3day")


def q2(x: Decimal) -> Decimal:
    """Round money to 2 decimals (INR paise), half-up."""
    return x.quantize(D("0.01"), rounding=ROUND_HALF_UP)


class MissingDataError(Exception):
    """Raised by compute_phase when the observation window has days with no reading (the agent should fill or abstain first)."""
    def __init__(self, missing: list[date]):
        self.missing = missing
        super().__init__(f"{len(missing)} day(s) missing in observation window")


@dataclass(frozen=True)
class Slab:
    """A payout band: `pct` percent of the phase sum insured when the index is in the band."""
    lower: Decimal
    lower_inclusive: bool
    upper: Optional[Decimal]
    upper_inclusive: bool
    pct: Decimal

    def contains(self, v: Decimal) -> bool:
        """True if index value v lies inside this band, honouring inclusive/exclusive ends (upper=None means open-ended)."""
        if self.lower_inclusive:
            if v < self.lower:
                return False
        elif v <= self.lower:
            return False
        if self.upper is None:
            return True
        return v <= self.upper if self.upper_inclusive else v < self.upper


@dataclass(frozen=True)
class PhaseRule:
    """One phase's rule as parsed from its policy clause: window, index type, strike and payout parameters."""
    phase_id: str                 # "P1", "P2", ...
    name: str
    clause_id: str                # e.g. "3.1" - where this rule came from
    start: date
    end: date
    index_type: str               # one of INDEX_TYPES
    strike: Decimal
    exit_value: Optional[Decimal] = None
    rate: Optional[Decimal] = None          # INR per mm (cumulative_deficit)
    cap: Optional[Decimal] = None           # INR max for this phase (cumulative_deficit)
    sum_insured: Optional[Decimal] = None   # INR (slab phases)
    slabs: tuple = ()
    dry_day_threshold: Optional[Decimal] = None  # mm, dry_spell only

    def window(self) -> list[date]:
        n = (self.end - self.start).days + 1
        return [self.start + timedelta(days=i) for i in range(n)]


@dataclass(frozen=True)
class PhaseResult:
    phase_id: str
    index: Decimal
    index_unit: str
    triggered: bool
    payout: Decimal
    steps: tuple = ()


def _slab_payout(rule: PhaseRule, index: Decimal) -> Decimal:
    for s in rule.slabs:
        if s.contains(index):
            return q2(rule.sum_insured * s.pct / D(100))
    raise ValueError(f"{rule.phase_id}: triggered but index {index} falls in no payout slab")


def compute_phase(rule: PhaseRule, series: dict) -> PhaseResult:
    """Compute index, trigger and payout for one phase. Raises MissingDataError if the window is incomplete."""
    days = rule.window()
    missing = [d for d in days if d not in series]
    if missing:
        raise MissingDataError(missing)
    vals = [series[d] for d in days]
    steps = [f"window {rule.start} to {rule.end} = {len(days)} days"]

    if rule.index_type == "cumulative_deficit":
        index = sum(vals, D(0))
        triggered = index < rule.strike
        steps.append(f"cumulative rainfall = {index} mm; strike = {rule.strike} mm; triggered if index < strike -> {triggered}")
        payout = D(0)
        if triggered:
            shortfall = rule.strike - index
            raw = shortfall * rule.rate
            payout = q2(min(raw, rule.cap))
            steps.append(f"shortfall = {rule.strike} - {index} = {shortfall} mm; x INR {rule.rate}/mm = INR {q2(raw)}; cap INR {rule.cap} -> payout INR {payout}")
        return PhaseResult(rule.phase_id, index, "mm", triggered, payout, tuple(steps))

    if rule.index_type == "dry_spell":
        thr = rule.dry_day_threshold
        longest = run = 0
        for v in vals:
            if v < thr:
                run += 1
                longest = max(longest, run)
            else:
                run = 0
        index = D(longest)
        triggered = index >= rule.strike
        steps.append(f"dry day = rainfall < {thr} mm; longest dry run = {longest} days; strike = {rule.strike} days; triggered if run >= strike -> {triggered}")
        payout = _slab_payout(rule, index) if triggered else D(0)
        if triggered:
            steps.append(f"slab lookup for {longest} days -> payout INR {payout} of sum insured INR {rule.sum_insured}")
        return PhaseResult(rule.phase_id, index, "days", triggered, payout, tuple(steps))

    if rule.index_type == "excess_3day":
        best = None
        for i in range(len(vals) - 2):
            s3 = vals[i] + vals[i + 1] + vals[i + 2]
            if best is None or s3 > best[0]:
                best = (s3, days[i])
        index = best[0]
        triggered = index > rule.strike
        steps.append(f"highest 3-day total = {index} mm (starting {best[1]}); strike = {rule.strike} mm; triggered if index > strike -> {triggered}")
        payout = _slab_payout(rule, index) if triggered else D(0)
        if triggered:
            steps.append(f"slab lookup for {index} mm -> payout INR {payout} of sum insured INR {rule.sum_insured}")
        return PhaseResult(rule.phase_id, index, "mm", triggered, payout, tuple(steps))

    raise ValueError(f"unknown index type {rule.index_type}")


def apply_overall_cap(total: Decimal, overall_cap: Optional[Decimal]) -> Decimal:
    """Limit the summed payout to the policy-wide cap (clause 5.1); no cap means just round to paise."""
    if overall_cap is None:
        return q2(total)
    return q2(min(total, overall_cap))


# --- Fault injection (used only by the evaluation harness and tests) ---------
class FaultyCalculator:
    """Wraps compute_phase and adds +1 to the index of one phase, simulating an off-by-one bug.

    mode "transient": only the first attempt is wrong (a retry fixes it).
    mode "persistent": every attempt is wrong (the verifier must escalate).
    """

    def __init__(self, mode: str = "transient", target_phase: str = "P1"):
        assert mode in ("transient", "persistent")
        self.mode, self.target_phase, self.attempt = mode, target_phase, 0

    def new_attempt(self):
        self.attempt += 1

    def __call__(self, rule: PhaseRule, series: dict) -> PhaseResult:
        res = compute_phase(rule, series)
        if rule.phase_id == self.target_phase and (self.mode == "persistent" or self.attempt <= 1):
            return replace(res, index=res.index + 1)
        return res
