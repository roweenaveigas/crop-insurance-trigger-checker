"""Policy retrieval with an agent-controlled loop (agentic RAG).

Pipeline per information need:  retrieve -> grade -> (rewrite query -> retrieve again) -> fallback.
 * retrieve : BM25 over clause-level chunks (no external services, runs offline)
 * grade    : a chunk passes only if it contains every `must_have` phrase for the need
 * rewrite  : synonym expansion of the question, then the need's canonical keywords
 * fallback : after the attempt budget is spent the need is reported `not_found` and the agent abstains
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

STOPWORDS = set("a an and are as at be by do does for from if in is it of on or that the this to we what when which with".split())

SYNONYMS = {
    "gap": "missing", "gaps": "missing", "absent": "missing", "blank": "missing", "lost": "missing",
    "gauge": "station", "sensor": "station", "backup": "secondary", "backfill": "filled", "fill": "filled",
    "inches": "inches", "inch": "inches", "centimetres": "centimetres", "unit": "units",
}


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def tokenize(text: str) -> list[str]:
    """Lower-case, split into words/numbers, drop stopwords and a trailing plural 's'."""
    toks = re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower())
    return [_stem(t) for t in toks if t not in STOPWORDS]


@dataclass(frozen=True)
class Chunk:
    clause_id: str
    title: str
    text: str


def split_clauses(policy_text: str) -> list[Chunk]:
    """Split the policy text into one Chunk per line that starts with 'Clause N.N Title.'."""
    chunks = []
    for m in re.finditer(r"^Clause (\d+\.\d+) ([^.]+)\. (.*)$", policy_text, flags=re.M):
        cid, title, body = m.group(1), m.group(2).strip(), m.group(3).strip()
        chunks.append(Chunk(cid, title, f"{title}. {body}"))
    return chunks


class PolicyIndex:
    """Tiny BM25 index. k1=1.5, b=0.75."""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.docs = [Counter(tokenize(c.title + " " + c.text)) for c in chunks]
        self.lens = [sum(d.values()) for d in self.docs]
        self.avg = sum(self.lens) / max(1, len(self.lens))
        df = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    @classmethod
    def from_text(cls, text: str) -> "PolicyIndex":
        return cls(split_clauses(text))

    def search(self, query: str, k: int = 3) -> list[tuple[Chunk, float]]:
        """Return the top-k (chunk, BM25 score) pairs for the query, best first, ignoring zero scores."""
        q = tokenize(query)
        scored = []
        for i, d in enumerate(self.docs):
            s = 0.0
            for t in q:
                if t in d:
                    f = d[t]
                    s += self.idf[t] * f * 2.5 / (f + 1.5 * (0.25 + 0.75 * self.lens[i] / self.avg))
            scored.append((self.chunks[i], s))
        scored.sort(key=lambda x: -x[1])
        return [(c, s) for c, s in scored[:k] if s > 0]


@dataclass(frozen=True)
class Need:
    name: str
    query: str                      # how a user would naturally ask
    must_have: tuple = ()           # grading rule: all phrases must appear in the chunk (case-insensitive)
    canonical: str = ""             # last-resort keyword rewrite
    top_k: int = 3
    multi: bool = False             # return every passing chunk (e.g. all phases)


@dataclass
class Retrieval:
    need: str
    status: str                     # "ok" | "not_found"
    chunks: list = field(default_factory=list)
    attempts: list = field(default_factory=list)   # [{query, hits:[(clause_id, score)], passed:[clause_id]}]

    @property
    def rewrites(self) -> int:
        return max(0, len(self.attempts) - 1)

    @property
    def clause_ids(self) -> list[str]:
        return [c.clause_id for c in self.chunks]


def expand(query: str, must_have: tuple) -> str:
    """Rewrite a query: map everyday words to policy vocabulary and append the grading phrases."""
    words = [SYNONYMS.get(w, w) for w in re.findall(r"[A-Za-z0-9.]+", query.lower())]
    extra = [w for phrase in must_have for w in phrase.split()]
    return " ".join(words + extra)


def passes(chunk: Chunk, must_have: tuple) -> bool:
    """Grade a chunk: True only if every must-have phrase appears in it (case-insensitive)."""
    low = chunk.text.lower()
    return all(m.lower() in low for m in must_have)


def retrieve(index: PolicyIndex, need: Need, max_attempts: int = 3) -> Retrieval:
    """Search, grade, and if nothing passes rewrite the query and retry (up to max_attempts); otherwise status 'not_found'."""
    queries = [need.query, expand(need.query, need.must_have)]
    if need.canonical:
        queries.append(need.canonical)
    out = Retrieval(need=need.name, status="not_found")
    for q in queries[:max_attempts]:
        hits = index.search(q, need.top_k)
        good = [c for c, _ in hits if passes(c, need.must_have)]
        out.attempts.append({"query": q, "hits": [(c.clause_id, round(s, 2)) for c, s in hits],
                             "passed": [c.clause_id for c in good]})
        if good:
            out.status = "ok"
            out.chunks = good if need.multi else good[:1]
            return out
    return out


# The information needs the agent can raise. First queries are deliberately written in everyday language
# (not copied from the policy wording), so the grade -> rewrite -> retry loop does real work. How often that
# happens is measured by eval/retrieval_eval.py rather than assumed.
NEEDS = {
    "phases": Need("phases", "which growth stages have a rainfall payout rule", ("observation window", "strike"),
                   "observation window index strike trigger payout phase", top_k=6, multi=True),
    "dry_day": Need("dry_day", "how little rain makes a day count as dry", ("dry day", "less than"),
                    "dry day recorded rainfall less than"),
    "stations": Need("stations", "which station is the reference and which one is the backup", ("primary station", "secondary station"),
                     "primary station secondary station reference weather station"),
    "period": Need("period", "what dates does the cover run for", ("policy period",), "policy period season dates covers"),
    "overall_cap": Need("overall_cap", "what is the most the policy can pay in total", ("total payout", "may not exceed"),
                        "total payout across all phases may not exceed overall cap"),
    "disclaimer": Need("disclaimer", "does this mean the claim is approved", ("claim approval",),
                       "nature of this assessment claim approval guarantee"),
    "units": Need("units", "how are measurements in imperial or metric handled", ("converted", "mm"),
                  "units readings converted to mm centimetres inches"),
    "missing": Need("missing", "patch holes in the data using the nearby backup instrument", ("no valid reading", "secondary station"),
                    "missing observations primary station no valid reading secondary station"),
    "cross": Need("cross", "are the sensors cross checked against each other", ("outcomes differ",),
                  "station disagreement outcomes differ referred committee"),
}
