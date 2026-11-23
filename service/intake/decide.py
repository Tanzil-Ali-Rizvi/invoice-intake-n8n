"""One decision function, used by both the API (called from n8n) and the demo pipeline, so they cannot drift."""

from __future__ import annotations

from datetime import date
from typing import Any

from .extract import normalise, parse_json
from .rules import validate
from .store import Store


def decide(extraction: Any, text_chars: int | None, sha256: str, store: Store, buyer_gstin: str, today: date) -> dict:
    raw = parse_json(extraction) if extraction is not None else None
    inv = normalise(raw)
    d = validate(inv, buyer_gstin, today, store.seen()).to_dict()
    issues = list(d["issues"])
    if raw is None:
        issues.insert(
            0, {"code": "unreadable", "severity": "review", "message": "The extraction step returned no usable JSON."}
        )
    if text_chars == 0:
        issues.insert(
            0, {"code": "no_text", "severity": "review", "message": "The PDF has no text layer (probably a scan)."}
        )
    if sha256 and (prev := store.file_seen(sha256)) is not None:
        issues.append(
            {"code": "duplicate", "severity": "reject", "message": f"This exact file was already received (#{prev})."}
        )
    sev = {i["severity"] for i in issues}
    route = "reject" if "reject" in sev else ("review" if sev else "approve")
    return {"route": route, "issues": issues, "checks_passed": d["checks_passed"], "invoice": inv,
            "summary": summary(inv, route, issues, d["checks_passed"])}  # fmt: skip


def summary(inv: dict, route: str, issues: list[dict], passed: list[str]) -> str:
    who = inv.get("vendor_name") or "Unknown vendor"
    total = inv.get("total")
    amount = f"Rs {total:,.2f}" if isinstance(total, (int, float)) else "no total"
    head = f"{who}, invoice {inv.get('invoice_number') or '(no number)'}, {amount}"
    if route == "approve":
        return f"{head}: all {len(passed)} checks passed, posted to the ledger."
    reasons = "; ".join(i["message"] for i in issues[:3])
    return f"{head}: {'sent for review' if route == 'review' else 'rejected'}. {reasons}"
