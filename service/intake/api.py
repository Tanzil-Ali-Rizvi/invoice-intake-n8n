"""HTTP API the n8n workflow calls. n8n orchestrates; this service owns the rules and the records.

POST /validate                 normalise the LLM's extraction and decide: approve | review | reject
POST /record                   store the invoice under that decision (ledger, review queue or rejected)
GET  /review                   the human review queue          POST /review/{id}/decision
GET  /ledger  GET /audit       approved invoices; every step that happened
GET  /                         a minimal review page for people
"""

from __future__ import annotations

import html
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from .decide import decide
from .store import Store

BUYER_GSTIN = os.getenv("INTAKE_BUYER_GSTIN", "07AABCA1234A1ZL")
IST = timezone(timedelta(hours=5, minutes=30))
STATUS = {"approve": "approved", "review": "review", "reject": "rejected"}

app = FastAPI(title="Invoice intake service", version="0.1.0")
store = Store(os.getenv("INTAKE_DB", ":memory:"))


def today() -> date:
    fixed = os.getenv("INTAKE_TODAY")
    return date.fromisoformat(fixed) if fixed else datetime.now(IST).date()


class ValidateIn(BaseModel):
    extraction: Any = None  # the model's JSON (object or string)
    file_name: str = ""
    file_sha256: str = ""
    text_chars: int | None = None  # how much text the PDF gave; 0 means a scan with no text layer


class RecordIn(BaseModel):
    route: str
    invoice: dict
    decision: dict = {}
    file_name: str = ""
    file_sha256: str = ""


class EventIn(BaseModel):
    event: str
    detail: dict = {}


class DecisionIn(BaseModel):
    approve: bool
    by: str = "reviewer"
    note: str = ""


@app.get("/health")
def health() -> dict:
    return {"ok": True, "today": today().isoformat(), "buyer_gstin": BUYER_GSTIN}


@app.post("/validate")
def validate_endpoint(body: ValidateIn) -> dict:
    d = decide(body.extraction, body.text_chars, body.file_sha256, store, BUYER_GSTIN, today())
    store.audit("validated", None, file=body.file_name, route=d["route"], issues=[i["code"] for i in d["issues"]])
    return d


@app.post("/record")
def record(body: RecordIn) -> dict:
    if body.route not in STATUS:
        raise HTTPException(422, "route must be approve, review or reject")
    status = STATUS[body.route]
    inv_id = store.add(status, body.invoice, body.decision, body.file_name, body.file_sha256)
    store.audit(f"recorded_{status}", inv_id, file=body.file_name)
    return {"id": inv_id, "status": status}


@app.get("/review")
def review_queue() -> list[dict]:
    return store.list("review")


@app.post("/review/{invoice_id}/decision")
def review_decision(invoice_id: int, body: DecisionIn) -> dict:
    out = store.decide(invoice_id, body.approve, body.by, body.note)
    if out is None:
        raise HTTPException(404, "no invoice waiting for review with that id")
    return out


@app.get("/ledger")
def ledger() -> list[dict]:
    return store.list("approved")


@app.get("/invoices")
def invoices() -> list[dict]:
    return store.list()


@app.get("/audit")
def audit() -> list[dict]:
    return store.audit_log()


@app.post("/events")
def event(body: EventIn) -> dict:
    """Workflow-level events from n8n (for example its error workflow), kept in the same audit log."""
    store.audit(body.event[:60], None, **body.detail)
    return {"ok": True}


@app.post("/reset")
def reset() -> dict:
    if os.getenv("INTAKE_ALLOW_RESET") != "1":
        raise HTTPException(403, "reset is disabled")
    store.reset()
    return {"ok": True}


# ------------------------------------------------------------------------------------------- a small page for people
@app.get("/", response_class=HTMLResponse)
def page() -> str:
    rows = []
    for inv in store.list(limit=100):
        issues = "<br>".join(html.escape(i["message"]) for i in inv["decision"].get("issues", []))
        action = ""
        if inv["status"] == "review":
            action = (f"<form method=post action='/ui/{inv['id']}'><input name=note placeholder='note'>"
                      "<button name=approve value=1>Approve</button><button name=approve value=0>Reject</button></form>")  # fmt: skip
        total = f"{inv['total']:,.2f}" if inv["total"] is not None else ""
        rows.append(f"<tr><td>{inv['id']}</td><td>{inv['status']}</td><td>{html.escape(inv['vendor_name'] or '')}</td>"
                    f"<td>{html.escape(inv['invoice_number'] or '')}</td><td style='text-align:right'>{total}</td>"
                    f"<td>{issues}</td><td>{action}</td></tr>")  # fmt: skip
    return ("<!doctype html><meta charset=utf-8><title>Invoice intake</title><style>body{font:14px system-ui;margin:24px}"
            "table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:6px;vertical-align:top}</style>"
            "<h2>Invoice intake</h2><table><tr><th>#</th><th>Status</th><th>Vendor</th><th>Invoice</th><th>Total</th>"
            "<th>Issues</th><th>Decision</th></tr>" + "".join(rows) + "</table>")  # fmt: skip


@app.post("/ui/{invoice_id}")
def page_decision(invoice_id: int, approve: str = Form(...), note: str = Form("")) -> RedirectResponse:
    store.decide(invoice_id, approve == "1", "reviewer (web)", note)
    return RedirectResponse("/", status_code=303)


# ------------------------------------------------------------------- deterministic stand-in for the LLM (tests only)
if os.getenv("INTAKE_MOCK_LLM") == "1":
    TRUTH = json.loads((Path(__file__).resolve().parents[2] / "dataset" / "truth.json").read_text())["invoices"]

    @app.post("/mock-llm/v1/chat/completions")
    def mock_llm(body: dict) -> dict:
        """Returns the ground truth for a benchmark invoice found in the text, so CI can test the n8n plumbing
        end to end without an API key. Never used for the reported results."""
        text = body["messages"][-1]["content"]
        hit = next((r["truth"] for r in TRUTH if r["truth"]["vendor_gstin"] in text
                    and f"{r['truth']['total']:,.2f}".replace(",", "")[-6:] in text.replace(",", "")
                    and (r["truth"]["invoice_number"] or "") in text), None)  # fmt: skip
        return {"choices": [{"message": {"role": "assistant", "content": json.dumps(hit or {})}}],
                "usage": {"total_tokens": 0}}  # fmt: skip
