"""Does the grade -> rewrite -> fallback loop beat a single top-1 lookup?

Each question is a paraphrase of an information need (written in everyday language, not copied from the policy).
 * single-shot : take BM25's top-1 clause for the question, no grading
 * agentic     : crop_trigger.rag.retrieve (grade against must-have phrases, rewrite, retry, else not_found)
In-scope questions should return the right clause; out-of-scope questions (not in the policy) should return not_found.

Held-out questions: if eval/heldout_questions.csv exists (copy eval/heldout_questions_TEMPLATE.csv and have a TEAMMATE write the
questions, so the test is independent) they are evaluated in a separate section and written to eval/heldout_retrieval_results.md.
eval/retrieval_results.md is never changed by the held-out questions.

Run:  python eval/retrieval_eval.py
"""
import csv
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crop_trigger import rag  # noqa: E402

idx = rag.PolicyIndex.from_text((ROOT / "data/policy_sample.txt").read_text())

# (need, question, expected clause or None when the policy does not contain the answer)
Q = [
    ("missing", "what happens if a reading was never recorded for some dates", "4.1"),
    ("missing", "patch holes in the data using the nearby backup instrument", "4.1"),
    ("missing", "how many absent days can be backfilled", "4.1"),
    ("missing", "can gaps in the primary record be filled from elsewhere", "4.1"),
    ("units", "how are measurements in imperial or metric handled", "2.1"),
    ("units", "rainfall recorded in centimetres", "2.1"),
    ("units", "what if the sheet says inches", "2.1"),
    ("units", "is a reading with no unit acceptable", "2.1"),
    ("cross", "are the sensors cross checked against each other", "4.1"),
    ("cross", "what if the two gauges tell different stories", "4.1"),
    ("cross", "who decides when the stations disagree", "4.1"),
    ("dry_day", "what counts as a rainless day", "2.2"),
    ("dry_day", "how little rain makes a day count as dry", "2.2"),
    ("overall_cap", "upper limit on money paid out overall", "5.1"),
    ("overall_cap", "what is the most the policy can pay in total", "5.1"),
    ("disclaimer", "is this a guarantee that money will be paid", "5.2"),
    ("disclaimer", "does this mean the claim is approved", "5.2"),
    ("period", "season start and end", "1.1"),
    ("period", "what dates does the cover run for", "1.1"),
    ("stations", "which station is the reference and which one is the backup", "1.3"),
    # out of scope: the policy has no answer, the right behaviour is to say so
    ("premium", "what premium does the farmer pay", None),
    ("deadline", "how many days does the farmer have to file a claim", None),
    ("insurer", "which company underwrites this policy", None),
    ("deductible", "is there a deductible or excess", None),
    ("variety", "which rice varieties are covered", None),
]
EXTRA = {"premium": (("premium",), "premium rate farmer pays"), "deadline": (("days to file", "claim"), "claim filing deadline days"),
         "insurer": (("underwrit",), "insurer underwriter company"), "deductible": (("deductible",), "deductible excess"),
         "variety": (("variety",), "rice variety covered")}


def need_for(name, question):
    if name in rag.NEEDS:
        return replace(rag.NEEDS[name], query=question)
    must, canon = EXTRA[name]
    return rag.Need(name, question, must, canon)


# Held-out questions carry no "need" label, so the agentic loop is run with the grader of the information need that the expected
# clause belongs to (4.1 serves two needs, so either may succeed). NONE (out of scope) is correct only if no question-answering need
# finds a clause; the multi-clause 'phases' need is left out because it grades on words every rule clause contains.
CLAUSE_NEEDS = {"1.1": ["period"], "1.3": ["stations"], "2.1": ["units"], "2.2": ["dry_day"], "3.1": ["phases"], "3.2": ["phases"],
                "3.3": ["phases"], "4.1": ["missing", "cross"], "5.1": ["overall_cap"], "5.2": ["disclaimer"]}
ANSWER_NEEDS = ["period", "stations", "units", "dry_day", "missing", "cross", "overall_cap", "disclaimer"]


def load_heldout(path):
    """Read the held-out CSV (id, question, expected_clause or NONE, written_by); rows whose written_by starts with EXAMPLE are ignored.
    Returns (rows, number_of_example_rows_ignored)."""
    with open(path, newline="", encoding="utf8") as f:
        rows = list(csv.DictReader(f))
    real = [r for r in rows if not r["written_by"].strip().upper().startswith("EXAMPLE")]
    return real, len(rows) - len(real)


def heldout_section(rows, ignored=0):
    """Evaluate held-out questions: single-shot BM25 top-1 vs the agentic loop. Returns markdown lines."""
    ins = [r for r in rows if r["expected_clause"].strip().upper() != "NONE"]
    outs = [r for r in rows if r["expected_clause"].strip().upper() == "NONE"]
    ss_ok = ag_ok = ss_out = ag_out = 0
    misses = []
    for r in rows:
        q, want = r["question"], r["expected_clause"].strip()
        top = idx.search(q, 1)
        ss = top[0][0].clause_id if top else None
        if want.upper() != "NONE":
            got = [rag.retrieve(idx, replace(rag.NEEDS[n], query=q)) for n in CLAUSE_NEEDS.get(want, [])]
            hit = any(g.status == "ok" and want in g.clause_ids for g in got)
            ss_ok += ss == want
            ag_ok += hit
            if not hit or ss != want:
                misses.append(f"- {r['id']} (expected {want}, written by {r['written_by']}): single-shot top-1 {ss}; agentic {'ok' if hit else 'missed'}")
        else:
            found = [n for n in ANSWER_NEEDS if rag.retrieve(idx, replace(rag.NEEDS[n], query=q)).status == "ok"]
            ss_out += ss is None
            ag_out += not found
            if found or ss is not None:
                misses.append(f"- {r['id']} (expected NONE, written by {r['written_by']}): single-shot top-1 {ss}; agentic found a clause via need(s) {found}")
    pct = lambda a, b: "n/a (no such questions)" if not b else f"{100 * a / b:.0f}% ({a}/{b})"
    L = ["## Held-out questions (written by a teammate)", "",
         f"{len(ins)} in-scope and {len(outs)} out-of-scope questions" + (f"; {ignored} EXAMPLE row(s) ignored" if ignored else "") + ".", "",
         "| | Single-shot top-1 | Agentic loop |", "|---|---|---|",
         f"| In-scope: correct clause | {pct(ss_ok, len(ins))} | {pct(ag_ok, len(ins))} |",
         f"| Out-of-scope: correctly says 'not found' | {pct(ss_out, len(outs))} | {pct(ag_out, len(outs))} |", "",
         "Method: no need label is given, so the agentic loop uses the grader of the need that the expected clause belongs to "
         "(see CLAUSE_NEEDS in eval/retrieval_eval.py); that favours it slightly compared with a real unlabelled question. "
         "NONE is correct only if no question-answering need finds a clause.", ""]
    if misses:
        L += ["Questions where either method was wrong:", ""] + misses + [""]
    return L


def main():
    ss_ok = ag_ok = rewrites = firsttry = 0
    ins = [q for q in Q if q[2]]
    outs = [q for q in Q if not q[2]]
    ss_out = ag_out = 0
    for name, question, want in Q:
        top = idx.search(question, 1)
        ss = top[0][0].clause_id if top else None
        r = rag.retrieve(idx, need_for(name, question))
        if want:
            ss_ok += ss == want
            ag_ok += r.status == "ok" and want in r.clause_ids
            firsttry += bool(r.attempts[0]["passed"]) and want in r.attempts[0]["passed"]
            rewrites += r.rewrites > 0 and r.status == "ok"
        else:
            ss_out += ss is None                  # single-shot "abstains" only if nothing matched at all
            ag_out += r.status == "not_found"
    pct = lambda a, b: f"{100 * a / b:.0f}% ({a}/{b})"
    L = ["# Retrieval evaluation", "",
         f"{len(ins)} in-scope paraphrased questions and {len(outs)} out-of-scope questions.", "",
         "| | Single-shot top-1 | Agentic loop (grade, rewrite, retry, abstain) |", "|---|---|---|",
         f"| In-scope: correct clause | {pct(ss_ok, len(ins))} | {pct(ag_ok, len(ins))} |",
         f"| Out-of-scope: correctly says 'not found' | {pct(ss_out, len(outs))} | {pct(ag_out, len(outs))} |", "",
         f"- In-scope questions answered correctly on the first attempt without any rewrite: {pct(firsttry, len(ins))}",
         f"- In-scope questions that needed at least one rewrite and then succeeded: {rewrites}"]
    out = "\n".join(L) + "\n"
    (ROOT / "eval/retrieval_results.md").write_text(out)
    print(out)
    held = ROOT / "eval/heldout_questions.csv"
    if held.exists():
        rows, ignored = load_heldout(held)
        text = "\n".join(["# Held-out retrieval evaluation", ""] + heldout_section(rows, ignored)) + "\n"
        (ROOT / "eval/heldout_retrieval_results.md").write_text(text)
        print(text)
    else:
        print("note: eval/heldout_questions.csv not found - skipping the held-out section (copy eval/heldout_questions_TEMPLATE.csv and have a teammate fill it in)")


if __name__ == "__main__":
    main()
