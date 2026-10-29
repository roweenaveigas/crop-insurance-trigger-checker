"""Turn retrieved clause text into structured rules (and grounded constants).

Deterministic regex extraction is the source of truth. If an LLM is configured it extracts the same rule
independently; any disagreement is raised so the agent can send the case to a human.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ValidationError

from .engine import D, PhaseRule, Slab


class ExtractionError(Exception):
    pass


def _num(s: str) -> Decimal:
    return D(s.replace(",", ""))


def _date(s: str):
    return datetime.strptime(s.strip(), "%d %B %Y").date()


def _must(pattern: str, text: str, what: str, flags=0):
    m = re.search(pattern, text, flags)
    if not m:
        raise ExtractionError(f"could not find {what}")
    return m


def extract_phase_rule(chunk, phase_no: int, dry_threshold: Decimal | None = None) -> PhaseRule:
    """chunk: rag.Chunk for a phase clause (title looks like 'Phase 1 - Crop Establishment (Cumulative Rainfall Deficit)')."""
    t = chunk.text
    title = chunk.title.lower()
    w = _must(r"Observation window:\s*(\d{1,2} \w+ \d{4}) to (\d{1,2} \w+ \d{4})", t, "observation window")
    start, end = _date(w.group(1)), _date(w.group(2))
    name = re.sub(r"^Phase \d+ - ", "", chunk.title)
    pid = f"P{phase_no}"

    if "cumulative rainfall deficit" in title:
        strike = _num(_must(r"Strike:\s*([\d.,]+) mm", t, "strike").group(1))
        ex = _num(_must(r"Exit:\s*([\d.,]+) mm", t, "exit").group(1))
        rate = _num(_must(r"INR ([\d,]+) for each mm", t, "per-mm rate").group(1))
        cap = _num(_must(r"maximum of INR ([\d,]+)", t, "phase cap").group(1))
        return PhaseRule(pid, name, chunk.clause_id, start, end, "cumulative_deficit", strike, exit_value=ex, rate=rate, cap=cap)

    if "dry spell" in title:
        if dry_threshold is None:
            raise ExtractionError("dry-day threshold needed for a dry-spell phase")
        strike = _num(_must(r"Strike:\s*(\d+) consecutive dry days", t, "strike days").group(1))
        si = _num(_must(r"sum insured is INR ([\d,]+)", t, "sum insured").group(1))
        s = _must(r"(\d+)% of the Phase \d sum insured is paid for a longest run of (\d+) to (\d+) days; (\d+)% is paid for (\d+) or more days", t, "dry-spell slabs")
        slabs = (Slab(_num(s.group(2)), True, _num(s.group(3)), True, _num(s.group(1))),
                 Slab(_num(s.group(5)), True, None, False, _num(s.group(4))))
        return PhaseRule(pid, name, chunk.clause_id, start, end, "dry_spell", strike, sum_insured=si, slabs=slabs, dry_day_threshold=dry_threshold)

    if "excess rainfall" in title:
        strike = _num(_must(r"Strike:\s*([\d.,]+) mm", t, "strike").group(1))
        si = _num(_must(r"sum insured is INR ([\d,]+)", t, "sum insured").group(1))
        s = _must(r"(\d+)% of the Phase \d sum insured is paid when the index is above (\d+) mm up to (\d+) mm; (\d+)% is paid when the index is above (\d+) mm", t, "excess-rain slabs")
        slabs = (Slab(_num(s.group(2)), False, _num(s.group(3)), True, _num(s.group(1))),
                 Slab(_num(s.group(5)), False, None, False, _num(s.group(4))))
        return PhaseRule(pid, name, chunk.clause_id, start, end, "excess_3day", strike, sum_insured=si, slabs=slabs)

    raise ExtractionError(f"unrecognised phase type in clause {chunk.clause_id}: {chunk.title}")


def extract_dry_threshold(text: str) -> Decimal:
    """Read the dry-day rainfall threshold in mm from clause 2.2 ('less than X mm')."""
    return _num(_must(r"less than ([\d.]+) mm", text, "dry-day threshold").group(1))


def extract_stations(text: str) -> tuple[str, str]:
    """Return (primary_station_id, secondary_station_id) from clause 1.3."""
    p = _must(r"Primary Station is ([A-Z0-9-]+)", text, "primary station").group(1)
    s = _must(r"Secondary Station is ([A-Z0-9-]+)", text, "secondary station").group(1)
    return p, s


def extract_unit_factors(text: str) -> dict:
    """Return the unit-to-mm factors from clause 2.1: {'mm': 1, 'cm': ..., 'in': ...}."""
    cm = _num(_must(r"1 cm = ([\d.]+) mm", text, "cm factor").group(1))
    inch = _num(_must(r"1 in = ([\d.]+) mm", text, "inch factor").group(1))
    return {"mm": D(1), "cm": cm, "in": inch}


def extract_fill_limit(text: str) -> int:
    """Return how many missing days per phase may be filled from the Secondary Station (clause 4.1)."""
    return int(_must(r"up to (\d+) such days", text, "fill limit").group(1))


def extract_overall_cap(text: str) -> Decimal:
    """Return the total sum insured in INR, used as the overall payout cap (clause 1.2 / 5.1)."""
    return _num(_must(r"sum insured of INR ([\d,]+)", text, "overall cap").group(1))


def extract_period(text: str):
    """Return (start, end) dates of the policy period from clause 1.1."""
    m = _must(r"from (\d{1,2} \w+ \d{4}) to (\d{1,2} \w+ \d{4})", text, "policy period")
    return _date(m.group(1)), _date(m.group(2))


# ---- Optional LLM cross-check -------------------------------------------------------------------
class RuleSchema(BaseModel):
    index_type: str
    window_start: str      # YYYY-MM-DD
    window_end: str
    strike: Decimal
    rate: Decimal | None = None
    cap: Decimal | None = None
    sum_insured: Decimal | None = None
    slab_pcts: list[Decimal] = []


LLM_SYSTEM = "You extract insurance clause parameters. Reply with ONLY a JSON object, no prose."
LLM_PROMPT = """Clause text:
{clause}

Return JSON with keys: index_type (cumulative_deficit | dry_spell | excess_3day), window_start (YYYY-MM-DD),
window_end (YYYY-MM-DD), strike (number), rate (INR per mm or null), cap (INR or null),
sum_insured (INR or null), slab_pcts (list of payout percentages in order, [] if none)."""


class LLMOutputError(Exception):
    """The LLM answered, but not with usable rule JSON. This is NOT a disagreement with the parser."""


def llm_rule_check(llm, chunk, rule: PhaseRule) -> list[str]:
    """Return a list of disagreements between the LLM extraction and the deterministic rule ([] = agree).

    Two different failures are kept apart on purpose:
      - the LLM is unreachable (llm.complete raises) or replies with unusable text -> raises, no opinion was given;
      - the LLM gives valid JSON that differs from the parser -> returned as a non-empty list (a real disagreement).
    """
    raw = llm.complete(LLM_SYSTEM, LLM_PROMPT.format(clause=chunk.text))
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        got = RuleSchema.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as e:
        raise LLMOutputError(f"not valid rule JSON ({type(e).__name__})") from e
    diffs = []
    exp = {"index_type": rule.index_type, "window_start": rule.start.isoformat(), "window_end": rule.end.isoformat(),
           "strike": rule.strike, "rate": rule.rate, "cap": rule.cap, "sum_insured": rule.sum_insured,
           "slab_pcts": [s.pct for s in rule.slabs]}
    for k, v in exp.items():
        g = getattr(got, k)
        if (g is None) != (v is None) or (g is not None and g != v):
            diffs.append(f"{k}: parser={v} llm={g}")
    return diffs
