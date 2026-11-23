"""Accounts-payable checks for an extracted Indian GST invoice. Pure functions: easy to test, same answer every time.

The n8n workflow sends the LLM's extraction here; these rules, not the model, decide whether an invoice can be posted
straight to the ledger, needs a person, or is a duplicate.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "27": "Maharashtra", "29": "Karnataka", "30": "Goa", "32": "Kerala", "33": "Tamil Nadu", "36": "Telangana",
    "37": "Andhra Pradesh",
}  # fmt: skip
GST_RATES = {0.0, 5.0, 12.0, 18.0, 28.0}
APPROVAL_LIMIT = 500_000.0  # invoices above ₹5 lakh need a person, whatever the checks say
MONEY_TOL = 1.0  # rupees: invoices round each line and each tax
MAX_AGE_DAYS = 180


def gstin_check_char(first14: str) -> str:
    """The official GSTIN check character (mod-36, alternating weights 1 and 2)."""
    total = 0
    for i, ch in enumerate(first14):
        v = GSTIN_CHARS.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return GSTIN_CHARS[(36 - total % 36) % 36]


def gstin_valid(gstin: str | None) -> bool:
    g = (gstin or "").strip().upper()
    return bool(GSTIN_RE.match(g)) and g[:2] in STATES and gstin_check_char(g[:14]) == g[14]


@dataclass
class Issue:
    code: str
    severity: str  # "review" sends the invoice to a person, "reject" stops it
    message: str


@dataclass
class Decision:
    route: str  # approve | review | reject
    issues: list[Issue] = field(default_factory=list)
    checks_passed: list[str] = field(default_factory=list)
    totals: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(v: Any) -> float | None:
    """A number from model or invoice text: 1180, "1,23,456.50", "Rs. 1,180.00", "(500)"... None if absent."""
    if v is None or v == "" or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("\u2212", "-")
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _date(v: Any) -> date | None:
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def validate(inv: dict[str, Any], buyer_gstin: str, today: date, seen: set[tuple[str, str]] | None = None) -> Decision:
    """Check one extracted invoice. `seen` holds (vendor GSTIN, invoice number) pairs already in the ledger."""
    issues: list[Issue] = []
    passed: list[str] = []

    def issue(code: str, msg: str, severity: str = "review") -> None:
        issues.append(Issue(code, severity, msg))

    # Required fields
    for key, label in (("vendor_name", "vendor name"), ("vendor_gstin", "vendor GSTIN"),
                       ("invoice_number", "invoice number"), ("invoice_date", "invoice date"), ("total", "total")):  # fmt: skip
        if inv.get(key) in (None, "", []):
            issue("missing_field", f"The {label} could not be read.")
    if not issues:
        passed.append("required fields present")

    # GSTINs
    vendor = (inv.get("vendor_gstin") or "").strip().upper()
    if vendor:
        if gstin_valid(vendor):
            passed.append("vendor GSTIN valid")
        else:
            issue("invalid_gstin", f"Vendor GSTIN {vendor} fails the format or checksum test.")
    billed_to = (inv.get("buyer_gstin") or "").strip().upper()
    if billed_to and billed_to != buyer_gstin:
        issue("wrong_buyer", f"Billed to GSTIN {billed_to}, which is not ours ({buyer_gstin}).")

    # Arithmetic
    lines = inv.get("line_items") or []
    line_sum = 0.0
    bad_lines = []
    for i, li in enumerate(lines, start=1):
        qty, rate, amt = _num(li.get("quantity")), _num(li.get("unit_price")), _num(li.get("amount"))
        if amt is not None:
            line_sum += amt
        if qty is not None and rate is not None and amt is not None and abs(qty * rate - amt) > MONEY_TOL:
            bad_lines.append(f"line {i}: {qty:g} x {rate:,.2f} = {qty * rate:,.2f}, invoice says {amt:,.2f}")
    if bad_lines:
        issue("line_math", "Line amounts don't add up: " + "; ".join(bad_lines[:3]) + ".")
    elif lines:
        passed.append("line amounts = quantity x price")

    taxable = _num(inv.get("taxable_value"))
    if taxable is None and lines:
        taxable = round(line_sum, 2)
    if lines and taxable is not None and abs(line_sum - taxable) > MONEY_TOL:
        issue("subtotal_math", f"Lines add up to {line_sum:,.2f} but the taxable value is {taxable:,.2f}.")
    elif lines and taxable is not None:
        passed.append("lines add up to the taxable value")

    cgst, sgst, igst = (_num(inv.get(k)) or 0.0 for k in ("cgst", "sgst", "igst"))
    total = _num(inv.get("total"))
    if taxable is not None and total is not None:
        expected = taxable + cgst + sgst + igst
        if abs(expected - total) > MONEY_TOL:
            issue("total_math", f"Taxable value plus tax is {expected:,.2f} but the invoice total is {total:,.2f}.")
        else:
            passed.append("total = taxable value + tax")

    # Tax type: CGST + SGST inside a state, IGST across states. Place of supply is our (the buyer's) state.
    if gstin_valid(vendor):
        same_state = vendor[:2] == buyer_gstin[:2]
        if same_state and igst > 0:
            issue("wrong_tax_type", f"Vendor is in {STATES[vendor[:2]]}, the same state as us, so tax should be "
                                    "CGST + SGST, not IGST.")  # fmt: skip
        elif not same_state and (cgst > 0 or sgst > 0):
            issue("wrong_tax_type", f"Vendor is in {STATES[vendor[:2]]} and we are in {STATES[buyer_gstin[:2]]}, "
                                    "so tax should be IGST, not CGST + SGST.")  # fmt: skip
        elif cgst or sgst or igst:
            passed.append("tax type matches the states")
        if same_state and abs(cgst - sgst) > MONEY_TOL:
            issue("tax_split", f"CGST ({cgst:,.2f}) and SGST ({sgst:,.2f}) should be equal.")

    # Tax amount matches the line rates
    if lines and all(_num(li.get("gst_rate")) is not None and _num(li.get("amount")) is not None for li in lines):
        expected_tax = sum(_num(li["amount"]) * _num(li["gst_rate"]) / 100 for li in lines)
        if any(_num(li["gst_rate"]) not in GST_RATES for li in lines):
            issue("odd_rate", "A line uses a GST rate that is not 0, 5, 12, 18 or 28%.")
        if abs(expected_tax - (cgst + sgst + igst)) > max(MONEY_TOL, 0.005 * expected_tax):
            issue("tax_math", f"The line rates give {expected_tax:,.2f} of tax but the invoice charges "
                              f"{cgst + sgst + igst:,.2f}.")  # fmt: skip
        else:
            passed.append("tax amount matches the GST rates")

    # Dates
    d = _date(inv.get("invoice_date"))
    if inv.get("invoice_date") and d is None:
        issue("bad_date", f"Could not understand the invoice date {inv.get('invoice_date')!r}.")
    elif d is not None:
        if d > today:
            issue("future_date", f"The invoice is dated {d.isoformat()}, which is in the future.")
        elif (today - d).days > MAX_AGE_DAYS:
            issue("stale_date", f"The invoice is dated {d.isoformat()}, more than {MAX_AGE_DAYS} days ago.")
        else:
            passed.append("invoice date is plausible")

    # Policy: approval limit
    if total is not None and total > APPROVAL_LIMIT:
        issue("over_limit", f"Total {total:,.2f} is above the {APPROVAL_LIMIT:,.0f} approval limit.")

    # Duplicates are rejected outright: paying twice is the costliest mistake in AP.
    key = (vendor, str(inv.get("invoice_number") or "").strip().upper())
    if seen is not None and all(key) and key in seen:
        issue("duplicate", f"Invoice {key[1]} from {vendor} is already in the ledger.", "reject")

    route = "reject" if any(i.severity == "reject" for i in issues) else ("review" if issues else "approve")
    return Decision(route, issues, passed, {"taxable_value": taxable or 0.0, "tax": cgst + sgst + igst,
                                             "total": total or 0.0})  # fmt: skip
