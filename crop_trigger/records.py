"""Persist a finished run as a JSON record and support the human-review step (the case is flagged, reviewed, and the review is recorded; the run does not wait).

The agent never finalises a CANNOT_DETERMINE case. It saves a record with status AWAITING_HUMAN_REVIEW;
a person then records a disposition with `apply_human_review`. The reviewer can accept, ask for more data
or escalate - but cannot edit the computed numbers, and every action is appended to an audit trail.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REVIEW_ACTIONS = ("ACCEPT_REFERRAL", "REQUEST_MORE_DATA", "ESCALATE_TO_COMMITTEE", "CLOSE_NO_ACTION")


def to_record(state) -> dict:
    d = state["report_data"]
    return {"run_id": d["trace_id"], "decision": d["decision"], "status": state["status"],
            "total_payout_inr": d["total_payout_inr"], "phases": d["phases"], "review_reasons": d["review_reasons"],
            "report_md": state["report_md"], "human_review": []}


def save_record(record: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{record['run_id']}.json"
    p.write_text(json.dumps(record, indent=2))
    return p


def load_record(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def apply_human_review(record: dict, reviewer: str, action: str, note: str) -> dict:
    if record["status"] != "AWAITING_HUMAN_REVIEW":
        raise ValueError("this run is not awaiting human review")
    if action not in REVIEW_ACTIONS:
        raise ValueError(f"action must be one of {REVIEW_ACTIONS}")
    if not reviewer.strip() or not note.strip():
        raise ValueError("reviewer name and a note are required")
    record["human_review"].append({"reviewer": reviewer.strip(), "action": action, "note": note.strip(),
                                   "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    record["status"] = "REVIEWED_" + action
    return record
