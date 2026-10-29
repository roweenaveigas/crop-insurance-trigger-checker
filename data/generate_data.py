"""Generate synthetic daily rainfall CSVs and a labelled test suite (data/cases.json).

Ground truth is fixed BY CONSTRUCTION from the policy numbers (strike 120 mm, 15 dry days, 250 mm in 3 days...),
not by running the agent or the engine. Each case's expected phase indices are planted deliberately
(for example "P1 total is exactly 119.9 mm"), and a small brute-force oracle below double-checks the plant.

Run:  python data/generate_data.py
"""
from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "cases"
START, END = date(2026, 7, 1), date(2026, 10, 15)
P1 = (date(2026, 7, 1), date(2026, 7, 31))
P2 = (date(2026, 8, 1), date(2026, 9, 15))
P3 = (date(2026, 9, 16), date(2026, 10, 15))
PRIMARY, SECONDARY = "RWS-A", "RWS-B"


def days(a, b):
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


def t(mm: str) -> int:
    """'12.5' -> 125 (tenths of a mm)."""
    return int((D(mm) * 10).to_integral_value())


def fmt(tenths: int) -> str:
    return f"{tenths // 10}.{tenths % 10}"


# ---------------------------------------------------------------- series construction (tenths of mm)
def spread(total: int, n: int, rng: random.Random) -> list[int]:
    w = [rng.random() ** 2 + 0.05 for _ in range(n)]
    s = sum(w)
    vals = [int(total * x / s) for x in w]
    rem = total - sum(vals)
    for i in rng.sample(range(n), n)[: rem % n] if rem else []:
        vals[i] += 1
    vals[0] += rem - (rem % n if rem else 0)
    assert sum(vals) == total
    return vals


def build(seed, p1_total="150.0", p2_runs=None, p3_storm=None):
    """Return {date: tenths}. p1_total: exact P1 cumulative rainfall. p2_runs: [(start_idx, length)] dry runs.
    p3_storm: exact highest 3-day total (mm string)."""
    rng = random.Random(seed)
    s = {}
    # P1: one big day (Jul 10) + the remainder spread over the other 30 days
    total = t(p1_total)
    big = min(300, total // 2)
    rest = spread(total - big, 30, rng)
    vals = rest[:9] + [big] + rest[9:]
    for d, v in zip(days(*P1), vals):
        s[d] = v
    # P2: wet baseline (3.0..12.0 mm) with planted dry runs (0.0..2.4 mm)
    d2 = days(*P2)
    wet = [rng.randint(30, 120) for _ in d2]
    if p2_runs is None:
        p2_runs = [(2, 4), (10, 6)]          # short natural dry spells
    for start, length in p2_runs:
        for i in range(start, start + length):
            wet[i] = rng.randint(0, 24)
    for d, v in zip(d2, wet):
        s[d] = v
    # P3: light baseline (0..5 mm) + a three-day storm at idx 12..14
    d3 = days(*P3)
    base = [rng.randint(0, 50) for _ in d3]
    T = t(p3_storm or "120.0")
    a = round(T * 0.36)
    b = round(T * 0.32)
    c = T - a - b
    base[12], base[13], base[14] = a, b, c
    for d, v in zip(d3, base):
        s[d] = v
    return s


# ---------------------------------------------------------------- oracle (brute force, deliberately naive)
def oracle(series: dict[date, D]):
    """series in mm Decimals. Returns per-phase expected dict using policy numbers typed in by hand."""
    out = {}
    p1 = sum(series[d] for d in days(*P1))
    pay1 = D(0)
    if p1 < 120:
        pay1 = min(D(18000), (120 - p1) * 300)
    out["P1"] = {"status": "MET" if p1 < 120 else "NOT_MET", "index": p1, "payout": pay1}
    run = best = 0
    for d in days(*P2):
        if series[d] < D("2.5"):
            run += 1
            best = max(best, run)
        else:
            run = 0
    pay2 = D(30000) * D("0.5") if best >= 20 else (D(30000) * D("0.25") if best >= 15 else D(0))
    out["P2"] = {"status": "MET" if best >= 15 else "NOT_MET", "index": D(best), "payout": pay2}
    ds = days(*P3)
    mx = max(series[ds[i]] + series[ds[i + 1]] + series[ds[i + 2]] for i in range(len(ds) - 2))
    pay3 = D(20000) if mx > 350 else (D(20000) * D("0.4") if mx > 250 else D(0))
    out["P3"] = {"status": "MET" if mx > 250 else "NOT_MET", "index": mx, "payout": pay3}
    return out


def to_mm(series_t: dict) -> dict:
    return {d: D(v) / 10 for d, v in series_t.items()}


# ---------------------------------------------------------------- writing files
def write_csv(path: Path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "rainfall", "unit", "station"])
        w.writerows(rows)


def rows_mm(series_t, station, drop=(), blank=(), unit_for=None, factor_for=None):
    rows = []
    for d in days(START, END):
        if d in drop:
            continue
        v = series_t[d]
        unit = "mm"
        text = fmt(v)
        if unit_for and d in unit_for:
            unit = unit_for[d]
        if factor_for and d in factor_for:
            text = factor_for[d](v)
        if d in blank:
            text = ""
        rows.append([d.isoformat(), text, unit, station])
    return rows


CASES = []


def ex_phase(status, index=None, payout=None):
    return {"status": status, "index": None if index is None else str(index), "payout": None if payout is None else str(payout)}


def add(cid, category, description, primary_rows, secondary_rows, expected_phases, fault=None, extra_cites=(), reasons=()):
    write_csv(OUT / f"{cid}_primary.csv", primary_rows)
    write_csv(OUT / f"{cid}_secondary.csv", secondary_rows)
    sts = [v["status"] for v in expected_phases.values()]
    if "UNDETERMINED" in sts:
        decision, total = "CANNOT_DETERMINE", None
    else:
        decision = "TRIGGER_MET" if "MET" in sts else "TRIGGER_NOT_MET"
        total = min(D(68000), sum(D(v["payout"]) for v in expected_phases.values()))
        total = str(total.quantize(D("0.01")))
    cites = ["3.1", "3.2", "3.3", "2.2", "4.1"] + list(extra_cites)
    CASES.append({"id": cid, "category": category, "description": description,
                  "primary": f"data/cases/{cid}_primary.csv", "secondary": f"data/cases/{cid}_secondary.csv",
                  "fault": fault,
                  "expected": {"decision": decision, "total_payout": total, "phases": expected_phases,
                               "reason_codes": list(reasons), "cited_clauses": cites}})


def planted(series_t, **override):
    """Expected phases from the oracle on the planted series; `override` replaces a phase with a given dict."""
    o = oracle(to_mm(series_t))
    ph = {k: ex_phase(v["status"], v["index"], v["payout"].quantize(D("0.01"))) for k, v in o.items()}
    ph.update(override)
    return ph


def clean(cid, category, description, seed, p1="150.0", p2_runs=None, p3="120.0", sec=None, expect_by_construction=None):
    s = build(seed, p1, p2_runs, p3)
    ph = planted(s)
    if expect_by_construction:  # assert the planted numbers match what we intended
        for k, v in expect_by_construction.items():
            assert (str(ph[k]["index"]) in (v, str(D(v))) or D(ph[k]["index"]) == D(v)), (cid, k, ph[k]["index"], v)
    s_sec = sec if sec is not None else s
    add(cid, category, description, rows_mm(s, PRIMARY), rows_mm(s_sec, SECONDARY), ph)
    return s


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.csv"):
        f.unlink()

    # ---- clean cases: trigger logic, boundaries ------------------------------------------------
    clean("C01", "clean", "Normal season: nothing triggers", 1, expect_by_construction={"P1": "150.0", "P3": "120.0"})
    clean("C02", "clean", "P1 deficit: 90.0 mm -> shortfall 30 mm -> INR 9,000", 2, p1="90.0", expect_by_construction={"P1": "90.0"})
    clean("C03", "clean", "P1 exactly at strike 120.0 mm -> NOT met (strictly below)", 3, p1="120.0", expect_by_construction={"P1": "120.0"})
    clean("C04", "clean", "P1 119.9 mm -> met, payout INR 30", 4, p1="119.9", expect_by_construction={"P1": "119.9"})
    clean("C05", "clean", "P1 50.0 mm (below exit) -> payout capped at INR 18,000", 5, p1="50.0", expect_by_construction={"P1": "50.0"})
    clean("C06", "clean", "P2 dry run of exactly 15 days -> met 25% = INR 7,500", 6, p2_runs=[(20, 15)], expect_by_construction={"P2": "15"})
    clean("C07", "clean", "P2 dry run of 14 days -> NOT met", 7, p2_runs=[(20, 14)], expect_by_construction={"P2": "14"})
    clean("C08", "clean", "P2 dry run of 20 days -> met 50% = INR 15,000", 8, p2_runs=[(20, 20)], expect_by_construction={"P2": "20"})
    clean("C09", "clean", "P2 two dry runs (16 and 21 days): the longest governs -> 50%", 9, p2_runs=[(0, 16), (20, 21)], expect_by_construction={"P2": "21"})
    clean("C10", "clean", "P3 3-day total exactly 250.0 mm -> NOT met (strictly above)", 10, p3="250.0", expect_by_construction={"P3": "250.0"})
    clean("C11", "clean", "P3 3-day total 250.1 mm -> met 40% = INR 8,000", 11, p3="250.1", expect_by_construction={"P3": "250.1"})
    clean("C12", "clean", "P3 3-day total 350.0 mm -> still the 40% band", 12, p3="350.0", expect_by_construction={"P3": "350.0"})
    clean("C13", "clean", "P3 3-day total 360.0 mm -> 100% = INR 20,000", 13, p3="360.0", expect_by_construction={"P3": "360.0"})
    clean("C14", "clean", "P1 and P2 both met -> payouts add up", 14, p1="100.0", p2_runs=[(20, 17)], expect_by_construction={"P1": "100.0", "P2": "17"})
    clean("C15", "clean", "All three phases met", 15, p1="60.0", p2_runs=[(20, 22)], p3="300.0", expect_by_construction={"P1": "60.0", "P2": "22", "P3": "300.0"})
    # a day with exactly 2.5 mm is NOT dry, so it must break a dry run: 14 dry + 2.5 + 14 dry -> longest 14
    s = build(16, "150.0", [(20, 14), (35, 11)])
    s[date(2026, 8, 1) + timedelta(days=34)] = t("2.5")
    ph = planted(s)
    assert ph["P2"]["index"] == "14", ph["P2"]
    add("C16", "clean", "P2: a day of exactly 2.5 mm is not dry and breaks the run (14 dry, 2.5, 11 dry) -> NOT met",
        rows_mm(s, PRIMARY), rows_mm(s, SECONDARY), ph)

    # ---- missing data -----------------------------------------------------------------------
    s = build(21, "125.0")
    gone = {date(2026, 7, 10), date(2026, 7, 11)}      # Jul 10 is the 30 mm day: naive zero-fill would wrongly trigger
    add("M01", "missing", "2 days absent in P1 (incl. the 30 mm day); Secondary Station has them -> fill, 125.0 mm, NOT met",
        rows_mm(s, PRIMARY, drop=gone), rows_mm(s, SECONDARY), planted(s), reasons=[])
    s = build(22, "110.0")
    add("M02", "missing", "Exactly 3 blank days in P1 (the allowed limit) -> fill, 110.0 mm, met",
        rows_mm(s, PRIMARY, blank={date(2026, 7, 8), date(2026, 7, 9), date(2026, 7, 10)}), rows_mm(s, SECONDARY), planted(s))
    s = build(23, "110.0")
    ph = planted(s, P1=ex_phase("UNDETERMINED"))
    add("M03", "missing", "4 days missing in P1 (over the limit of 3) -> P1 undetermined", rows_mm(s, PRIMARY, drop={date(2026, 7, d) for d in (8, 9, 10, 11)}),
        rows_mm(s, SECONDARY), ph, reasons=["missing_exceeds_limit"])
    s = build(24, "110.0")
    ph = planted(s, P1=ex_phase("UNDETERMINED"))
    add("M04", "missing", "2 days missing in P1 and the Secondary Station is also missing one of them -> undetermined",
        rows_mm(s, PRIMARY, drop={date(2026, 7, 10), date(2026, 7, 11)}), rows_mm(s, SECONDARY, drop={date(2026, 7, 10)}), ph,
        reasons=["secondary_also_missing"])
    s = build(25, "150.0", [(20, 20)])
    mid = date(2026, 8, 1) + timedelta(days=30)
    add("M05", "missing", "1 blank day inside a 20-day dry spell; filled from Secondary -> still 20 days, 50%",
        rows_mm(s, PRIMARY, blank={mid}), rows_mm(s, SECONDARY), planted(s))
    s = build(26, "150.0")
    ph = planted(s, P2=ex_phase("UNDETERMINED"), P3=ex_phase("UNDETERMINED"))
    cut = date(2026, 9, 5)
    add("M06", "missing", "Primary file stops on 5 Sep (truncated): P2 and P3 cannot be assessed, P1 still can",
        [r for r in rows_mm(s, PRIMARY) if r[0] <= cut.isoformat()], [r for r in rows_mm(s, SECONDARY) if r[0] <= cut.isoformat()], ph,
        reasons=["missing_exceeds_limit"])

    # ---- units ----------------------------------------------------------------------------
    s = build(31, "90.0", [(20, 20)], "300.0")
    cm = lambda v: f"{D(v) / 100:.2f}"
    add("U01", "units", "Whole primary file in centimetres -> convert (x10) and assess correctly",
        rows_mm(s, PRIMARY, unit_for={d: "cm" for d in days(START, END)}, factor_for={d: cm for d in days(START, END)}),
        rows_mm(s, SECONDARY), planted(s), extra_cites=["2.1"])
    s = build(32, "90.0", [(20, 20)], "300.0")
    inch = lambda v: f"{(D(v) / 10 / D('25.4')).quantize(D('0.001'))}"
    rows = rows_mm(s, PRIMARY, unit_for={d: "in" for d in days(START, END)}, factor_for={d: inch for d in days(START, END)})
    s_in = {}                                          # the truth is what the written inch values mean, computed by the oracle
    for r in rows:
        s_in[date.fromisoformat(r[0])] = D(r[1]) * D("25.4")
    o = oracle(s_in)
    ph = {k: ex_phase(v["status"], v["index"], v["payout"].quantize(D("0.01"))) for k, v in o.items()}
    add("U02", "units", "Whole primary file in inches -> convert (x25.4); expected values from the oracle on the written values",
        rows, rows_mm(s, SECONDARY), ph, extra_cites=["2.1"])
    # the secondary mm file is the un-rounded truth, so the two stations may differ by <0.1% - outcomes must still agree
    s = build(33, "90.0", [(20, 20)], "300.0")
    ph = planted(s, P1=ex_phase("UNDETERMINED"), P2=ex_phase("UNDETERMINED"), P3=ex_phase("UNDETERMINED"))
    add("U03", "units", "Unit column blank for the whole primary file -> no valid evidence, all phases undetermined",
        rows_mm(s, PRIMARY, unit_for={d: "" for d in days(START, END)}), rows_mm(s, SECONDARY), ph,
        extra_cites=["2.1"], reasons=["missing_exceeds_limit"])
    s = build(34, "90.0", [(20, 20)], "300.0")
    ph = planted(s, P1=ex_phase("UNDETERMINED"), P2=ex_phase("UNDETERMINED"), P3=ex_phase("UNDETERMINED"))
    add("U04", "units", "Unsupported unit 'mm/hr' for the whole primary file -> undetermined",
        rows_mm(s, PRIMARY, unit_for={d: "mm/hr" for d in days(START, END)}), rows_mm(s, SECONDARY), ph,
        extra_cites=["2.1"], reasons=["missing_exceeds_limit"])
    s = build(35, "90.0", [(20, 20)], "300.0")
    three = {date(2026, 7, 15), date(2026, 8, 20), date(2026, 9, 20)}
    add("U05", "units", "Three single days reported in cm inside an otherwise-mm file -> converted, same result as clean",
        rows_mm(s, PRIMARY, unit_for={d: "cm" for d in three}, factor_for={d: cm for d in three}), rows_mm(s, SECONDARY), planted(s),
        extra_cites=["2.1"])

    # ---- data integrity ----------------------------------------------------------------------
    s = build(41, "110.0")
    rows = rows_mm(s, PRIMARY)
    dup_days = [date(2026, 7, d) for d in (3, 4, 5, 6, 7)]
    extra = [[d.isoformat(), fmt(s[d] + 25), "mm", PRIMARY] for d in dup_days]     # a second, different reading for 5 days
    ph = planted(s, P1=ex_phase("UNDETERMINED"))
    add("D01", "integrity", "5 days with two conflicting readings in P1 -> invalid days, over the limit -> undetermined", rows + extra,
        rows_mm(s, SECONDARY), ph, reasons=["missing_exceeds_limit"])
    s = build(42, "150.0")
    ph = planted(s, P1=ex_phase("UNDETERMINED"), P2=ex_phase("UNDETERMINED"), P3=ex_phase("UNDETERMINED"))
    shift = lambda rows: [[(date.fromisoformat(r[0]) - timedelta(days=365)).isoformat()] + r[1:] for r in rows]
    add("D02", "integrity", "Both files carry 2025 dates (wrong season) -> nothing inside the 2026 windows -> undetermined",
        shift(rows_mm(s, PRIMARY)), shift(rows_mm(s, SECONDARY)), ph, reasons=["missing_exceeds_limit"])
    s = build(43, "150.0")
    ph = planted(s, P1=ex_phase("UNDETERMINED"), P2=ex_phase("UNDETERMINED"), P3=ex_phase("UNDETERMINED"))
    add("D03", "integrity", "Primary file is labelled station RWS-X, not the policy's RWS-A -> undetermined",
        rows_mm(s, "RWS-X"), rows_mm(s, SECONDARY), ph, reasons=["station_mismatch"])
    s = build(44, "90.0", [(20, 20)], "300.0")
    rows = rows_mm(s, PRIMARY)
    rows = rows + rows[10:20]                         # 10 identical duplicate rows
    add("D04", "integrity", "10 identical duplicate rows -> collapsed silently, same result as clean", rows, rows_mm(s, SECONDARY), planted(s))

    # ---- station conflict -----------------------------------------------------------------------
    s = build(51, "100.0")
    s2 = build(51, "130.0")
    ph = planted(s, P1=ex_phase("UNDETERMINED"))
    add("X01", "conflict", "P1: Primary 100.0 mm (met) vs Secondary 130.0 mm (not met) -> refer", rows_mm(s, PRIMARY), rows_mm(s2, SECONDARY), ph,
        reasons=["station_disagreement"])
    s = build(52, "130.0")
    s2 = build(52, "100.0")
    ph = planted(s, P1=ex_phase("UNDETERMINED"))
    add("X02", "conflict", "P1: Primary 130.0 mm (not met) vs Secondary 100.0 mm (met) -> refer (Primary is never overridden)",
        rows_mm(s, PRIMARY), rows_mm(s2, SECONDARY), ph, reasons=["station_disagreement"])
    s = build(53, "100.0")
    s2 = build(53, "104.0")
    add("X03", "conflict", "P1: Primary 100.0 vs Secondary 104.0 mm - small difference, same outcome (met) -> corroborated", rows_mm(s, PRIMARY),
        rows_mm(s2, SECONDARY), planted(s))
    s = build(54, "150.0", None, "260.0")
    s2 = build(54, "150.0", None, "240.0")
    ph = planted(s, P3=ex_phase("UNDETERMINED"))
    add("X04", "conflict", "P3: Primary storm 260 mm (met) vs Secondary 240 mm (not met) -> refer", rows_mm(s, PRIMARY), rows_mm(s2, SECONDARY), ph,
        reasons=["station_disagreement"])

    # ---- injected calculator faults (verifier tests) -----------------------------------------
    s = build(61, "90.0")
    add("F01", "fault", "Calculator has a transient off-by-one bug in P1 on the first attempt -> verifier catches it, retry fixes it",
        rows_mm(s, PRIMARY), rows_mm(s, SECONDARY), planted(s), fault={"mode": "transient", "phase": "P1"})
    s = build(62, "90.0")
    ph = planted(s, P1=ex_phase("UNDETERMINED"))
    add("F02", "fault", "Calculator has a persistent bug in P1 -> verifier catches it on both attempts -> P1 escalated, never reported",
        rows_mm(s, PRIMARY), rows_mm(s, SECONDARY), ph, fault={"mode": "persistent", "phase": "P1"}, reasons=["calc_mismatch"])
    s = build(63, "150.0")
    add("F03", "fault", "Transient bug on a not-triggered case -> caught and fixed by retry",
        rows_mm(s, PRIMARY), rows_mm(s, SECONDARY), planted(s), fault={"mode": "transient", "phase": "P1"})

    (HERE / "cases.json").write_text(json.dumps({"policy": "data/policy_sample.txt", "cases": CASES}, indent=2))
    cats = {}
    for c in CASES:
        cats[c["category"]] = cats.get(c["category"], 0) + 1
    print(f"wrote {len(CASES)} cases: {cats}")


if __name__ == "__main__":
    main()
