"""Randomised stress test: many random cases with random combinations of defects.

Why this exists: the 38 hand-written cases in data/cases.json were written by the same person who built the
agent, around the failure modes the agent was designed for, so a perfect score there proves little about
robustness. Here the parameters and defects are drawn at random (seeded, so reproducible), often right next
to thresholds, and the expected answer is derived from the POLICY SPEC by an independent re-implementation
in this file (a plain brute-force oracle), never from the agent.

Run:  python eval/stress_eval.py [N] [seed]
"""
from __future__ import annotations

import importlib.util
import random
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("gen", ROOT / "data" / "generate_data.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

from crop_trigger import agent  # noqa: E402
from crop_trigger.baseline import run_baseline  # noqa: E402
from crop_trigger.engine import FaultyCalculator  # noqa: E402

WINDOWS = {"P1": gen.P1, "P2": gen.P2, "P3": gen.P3}


def pick_params(rng, safe):
    if safe:
        p1 = rng.choice(["70.0", "90.0", "100.0", "140.0", "180.0"])
        L = rng.choice([5, 8, 17, 25])
        T = rng.choice(["120.0", "200.0", "300.0", "400.0"])
    else:
        p1 = rng.choice(["119.9", "120.0", "120.1", "119.0", "121.0"]) if rng.random() < 0.3 else f"{rng.uniform(40, 200):.1f}"
        L = rng.choice([14, 15, 19, 20, 21]) if rng.random() < 0.3 else rng.randint(3, 30)
        T = rng.choice(["249.9", "250.0", "250.1", "349.9", "350.0", "350.1"]) if rng.random() < 0.3 else f"{rng.uniform(100, 420):.1f}"
    return p1, L, T


def make_case(rng, i, tmp: Path):
    unit = rng.choices(["mm", "cm", "in", "blank", "bad", "mixed"], [50, 10, 8, 4, 3, 10])[0]
    p1, L, T = pick_params(rng, safe=(unit == "in"))
    start2 = rng.randint(0, 46 - L - 1)
    seed = rng.randint(1, 10**6)
    truth_t = gen.build(seed, p1, [(start2, L)], T)
    pert = rng.choice(["P1", "P2", "P3"]) if (unit != "in" and rng.random() < 0.15) else None
    sec_t = truth_t
    if pert == "P1":
        sec_t = gen.build(seed, f"{max(40.0, float(p1) + rng.choice([-25, -10, -3, 3, 10, 25])):.1f}", [(start2, L)], T)
    elif pert == "P2":
        L2 = max(0, L + rng.choice([-7, -3, -1, 1, 3, 7]))
        sec_t = gen.build(seed, p1, [(start2, L2)] if L2 else [], T)
    elif pert == "P3":
        sec_t = gen.build(seed, p1, [(start2, L)], f"{max(60.0, float(T) + rng.choice([-40, -10, -1, 1, 10, 40])):.1f}")

    drop, blank, conflict_days, sec_drop = set(), set(), set(), set()
    flags = []
    if unit != "in":
        for ph, (a, b) in WINDOWS.items():
            if ph == pert or rng.random() > 0.25:
                continue
            k = rng.choice([1, 2, 3, 3, 4, 5, 6])
            chosen = set(rng.sample(gen.days(a, b), k))
            mode = rng.random()
            (drop if mode < 0.5 else blank).update(chosen)
            flags.append("missing")
            if rng.random() < 0.3:
                sec_drop.add(rng.choice(sorted(chosen)))
                flags.append("secondary_gap_on_missing_day")
        if rng.random() < 0.08:
            ph = rng.choice([p for p in WINDOWS if p != pert] or ["P1"])
            chosen = set(rng.sample([d for d in gen.days(*WINDOWS[ph]) if d not in drop | blank], rng.randint(1, 5)))
            conflict_days |= chosen
            flags.append("conflicting_duplicates")
    if rng.random() < 0.15:
        ph = rng.choice(list(WINDOWS))
        sec_drop |= set(rng.sample(gen.days(*WINDOWS[ph]), rng.randint(1, 3)))
        flags.append("secondary_gaps")
    station = "RWS-X" if rng.random() < 0.03 else gen.PRIMARY
    if station != gen.PRIMARY:
        flags.append("wrong_station")
    fault = rng.choice([None, None, None, None, None, None, None, None, "transient", "persistent"])
    if fault:
        flags.append("fault_" + fault)
    if pert:
        flags.append("station_conflict_" + pert)
    if unit != "mm":
        flags.append("unit_" + unit)

    alld = gen.days(gen.START, gen.END)
    unit_for = factor_for = None
    cm = lambda v: f"{D(v) / 100:.2f}"
    inch = lambda v: f"{(D(v) / 10 / D('25.4')).quantize(D('0.001'))}"
    if unit == "cm":
        unit_for, factor_for = {d: "cm" for d in alld}, {d: cm for d in alld}
    elif unit == "in":
        unit_for, factor_for = {d: "in" for d in alld}, {d: inch for d in alld}
    elif unit == "blank":
        unit_for = {d: "" for d in alld}
    elif unit == "bad":
        unit_for = {d: "mm/hr" for d in alld}
    elif unit == "mixed":
        three = set(rng.sample(alld, 3))
        unit_for, factor_for = {d: "cm" for d in three}, {d: cm for d in three}
    prim_rows = gen.rows_mm(truth_t, station, drop=drop, blank=blank, unit_for=unit_for, factor_for=factor_for)
    for d in sorted(conflict_days):
        prim_rows.append([d.isoformat(), gen.fmt(truth_t[d] + 25), "mm", station])
    if rng.random() < 0.1:
        prim_rows += rng.sample(prim_rows, 5)
        flags.append("identical_duplicates")
    sec_rows = gen.rows_mm(sec_t, gen.SECONDARY, drop=sec_drop)
    pp, sp = tmp / f"s{i}_p.csv", tmp / f"s{i}_s.csv"
    gen.write_csv(pp, prim_rows)
    gen.write_csv(sp, sec_rows)

    # ------------------------------------------------ expected answer from the spec (independent of the agent)
    if unit == "in":                                   # truth is what the written inch values mean
        truth_mm = {}
        for r in prim_rows:
            truth_mm[gen.date.fromisoformat(r[0])] = D(r[1]) * D("25.4")
    else:
        truth_mm = gen.to_mm(truth_t)
    o_truth, o_sec = gen.oracle(truth_mm), gen.oracle(gen.to_mm(sec_t))
    sec_present = {d for d in alld if d not in sec_drop}
    exp = {}
    for ph, (a, b) in WINDOWS.items():
        win = gen.days(a, b)
        if station != gen.PRIMARY or unit in ("blank", "bad"):
            exp[ph] = {"status": "UNDETERMINED"}
            continue
        missing = [d for d in win if d in drop or d in blank or d in conflict_days]
        if len(missing) > 3 or any(d not in sec_present for d in missing):
            exp[ph] = {"status": "UNDETERMINED"}
            continue
        e = dict(o_truth[ph])
        sec_complete = all(d in sec_present for d in win)
        if sec_complete and o_sec[ph]["status"] != e["status"]:
            exp[ph] = {"status": "UNDETERMINED"}
            continue
        if fault == "persistent" and ph == "P1":
            exp[ph] = {"status": "UNDETERMINED"}
            continue
        exp[ph] = e
    if any(v["status"] == "UNDETERMINED" for v in exp.values()):
        decision, total = "CANNOT_DETERMINE", None
    else:
        decision = "TRIGGER_MET" if any(v["status"] == "MET" for v in exp.values()) else "TRIGGER_NOT_MET"
        total = min(D(68000), sum(v["payout"] for v in exp.values()))
    return {"id": f"S{i:03d}", "primary": pp, "secondary": sp, "fault": fault, "flags": flags or ["clean"],
            "decision": decision, "total": total, "phases": exp}


def main(n=500, seed=2026, write=True, quiet=False):
    rng = random.Random(seed)
    tmp = Path(tempfile.mkdtemp(prefix="stress_"))
    pol = ROOT / "data/policy_sample.txt"
    cases = [make_case(rng, i, tmp) for i in range(n)]
    ag_ok = base_ok = 0
    mism = []
    by_flag = defaultdict(lambda: [0, 0, 0])      # n, agent ok, baseline ok
    idx_tot = idx_ok = pay_tot = pay_ok = unsafe = abstain_expected = 0
    for c in cases:
        kw = {"calculator": FaultyCalculator(c["fault"], "P1")} if c["fault"] else {}
        s = agent.run(pol, c["primary"], c["secondary"], **kw)
        problems = []
        if s["decision"] != c["decision"]:
            problems.append(f"decision {s['decision']} != {c['decision']}")
        for ph, e in c["phases"].items():
            got = s["phase_final"][ph]
            if got["status"] != e["status"]:
                problems.append(f"{ph} status {got['status']} != {e['status']}")
            elif e["status"] != "UNDETERMINED":
                idx_tot += 1
                if D(str(got["index"])) == D(str(e["index"])):
                    idx_ok += 1
                else:
                    problems.append(f"{ph} index {got['index']} != {e['index']}")
        if c["total"] is not None:
            pay_tot += 1
            if s["total_payout"] is not None and D(str(s["total_payout"])) == c["total"].quantize(D("0.01")):
                pay_ok += 1
            else:
                problems.append(f"payout {s['total_payout']} != {c['total']}")
        else:
            abstain_expected += 1
            unsafe += s["decision"] != "CANNOT_DETERMINE"
        b = run_baseline(pol, c["primary"])["decision"] == c["decision"]
        ag_ok += not problems
        base_ok += b
        for f in set(c["flags"]):
            by_flag[f][0] += 1
            by_flag[f][1] += not problems
            by_flag[f][2] += b
        if problems:
            mism.append((c, problems))
    pct = lambda a, b: "n/a" if not b else f"{100 * a / b:.1f}%"
    L = [f"# Randomised stress test ({n} cases, seed {seed})", "",
         "Expected answers come from an independent brute-force implementation of the policy text (see `eval/stress_eval.py`), not from the agent.", "",
         f"- Agent fully correct (decision, every phase status, every index, total payout): **{pct(ag_ok, n)}** ({ag_ok}/{n})",
         f"- Naive baseline decision accuracy: {pct(base_ok, n)} ({base_ok}/{n})",
         f"- Agent index exactness on determinate phases: {pct(idx_ok, idx_tot)}; total payout exact: {pct(pay_ok, pay_tot)}",
         f"- Cases where the truth is CANNOT_DETERMINE: {abstain_expected}; agent gave an unsafe answer on {unsafe} of them", "",
         "| Defect present | Cases | Agent fully correct | Baseline decision correct |", "|---|---|---|---|"]
    for f, (cnt, a, b) in sorted(by_flag.items()):
        L.append(f"| {f} | {cnt} | {pct(a, cnt)} | {pct(b, cnt)} |")
    L += ["", f"## Mismatches ({len(mism)})", ""]
    for c, pr in mism[:25]:
        L.append(f"- {c['id']} flags={c['flags']}: " + "; ".join(pr))
    out = "\n".join(L) + "\n"
    if write:
        (ROOT / "eval/stress_results.md").write_text(out)
    if not quiet:
        print(out)
    return len(mism)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 500, int(sys.argv[2]) if len(sys.argv) > 2 else 2026)
