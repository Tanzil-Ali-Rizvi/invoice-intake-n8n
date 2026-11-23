"""The LLM extraction step: one prompt (shared with the n8n workflow) and the normaliser for its answer."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .rules import _date, _num

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "extract_system.md"
SYSTEM_PROMPT = PROMPT_PATH.read_text() if PROMPT_PATH.exists() else ""
FIELDS = ("vendor_name", "vendor_gstin", "buyer_gstin", "invoice_number", "invoice_date", "po_number",
          "taxable_value", "cgst", "sgst", "igst", "total", "line_items")  # fmt: skip
MAX_TEXT = 12_000


def messages(text: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Invoice text:\n<invoice>\n" + text[:MAX_TEXT] + "\n</invoice>"}]  # fmt: skip


def parse_json(text: str | dict | None) -> dict[str, Any] | None:
    if isinstance(text, dict):
        return text
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    try:
        out = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.S)
        if not m:
            return None
        try:
            out = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return out if isinstance(out, dict) else None


def _str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None if s.lower() not in ("null", "none", "n/a", "-") else None


def normalise(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Coerce the model's answer into clean types. Never invents values: unknown stays None."""
    raw = raw or {}
    out: dict[str, Any] = {}
    for k in ("vendor_name", "invoice_number", "po_number"):
        out[k] = _str(raw.get(k))
    for k in ("vendor_gstin", "buyer_gstin"):
        g = _str(raw.get(k))
        out[k] = re.sub(r"\s", "", g).upper() if g else None
    d = _date(raw.get("invoice_date"))
    out["invoice_date"] = d.isoformat() if d else _str(raw.get("invoice_date"))
    for k in ("taxable_value", "total"):
        out[k] = _num(raw.get(k))
    for k in ("cgst", "sgst", "igst"):
        out[k] = _num(raw.get(k)) or 0.0
    items = []
    for li in raw.get("line_items") or []:
        if not isinstance(li, dict):
            continue
        rate = _num(li.get("gst_rate"))
        if rate is not None and 0 < rate < 1:  # 0.18 -> 18
            rate = round(rate * 100, 2)
        items.append({"description": _str(li.get("description")) or "", "quantity": _num(li.get("quantity")),
                      "unit_price": _num(li.get("unit_price")), "amount": _num(li.get("amount")), "gst_rate": rate})  # fmt: skip
    out["line_items"] = items
    return out
