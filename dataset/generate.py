"""Generate the benchmark: fictional Indian GST invoices as PDFs, with ground truth.

Every vendor, GSTIN and invoice is made up (the GSTINs are valid in format and checksum only). Half the invoices are
clean; the rest carry one planted problem each. The ground truth records what is printed on the page, which is what
extraction should return, plus the route the rules should choose.

    python dataset/generate.py        # writes dataset/pdfs/*.pdf and dataset/truth.json (deterministic)
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "service"))
from intake.rules import STATES, gstin_check_char  # noqa: E402

TODAY = date(2026, 11, 20)  # the "processing date" the benchmark runs at
BUYER = {
    "name": "Acme Retail Private Limited",
    "gstin": "07AABCA1234A1ZL",
    "address": "Plot 14, Okhla Industrial Area Phase II, New Delhi 110020",
}


def make_gstin(state: str, pan: str, entity: str = "1") -> str:
    first = f"{state}{pan}{entity}Z"
    return first + gstin_check_char(first)


VENDORS = [
    ("Sharma Office Supplies", "07", "AKJPS4821M", "office", "B-22, Lajpat Nagar II, New Delhi 110024"),
    ("Nimbus Cloud Services Pvt Ltd", "29", "AAFCN7710Q", "cloud", "4th Floor, Indiranagar, Bengaluru 560038"),
    ("Vega Logistics LLP", "27", "AAJFV2209K", "logistics", "Plot 7, MIDC Andheri East, Mumbai 400093"),
    ("Kaveri Print House", "33", "ABHPK6630D", "print", "12 Mount Road, Chennai 600002"),
    ("Brightline Facility Services", "06", "AAGCB5512H", "facility", "Sector 18, Gurugram, Haryana 122015"),
    ("Orbit IT Hardware Pvt Ltd", "36", "AABCO9934P", "hardware", "Banjara Hills Road 3, Hyderabad 500034"),
    ("Saffron Caterers", "07", "BCKPS1180L", "food", "Shop 5, Karol Bagh, New Delhi 110005"),
    ("Deccan Packaging Industries", "24", "AAEFD4471R", "packaging", "GIDC Vatva, Ahmedabad 382445"),
    ("Lotus Electricals", "09", "AXLPL7725C", "electrical", "Sector 63, Noida, Uttar Pradesh 201301"),
    ("Coastal Security Agency", "32", "AAHFC3398N", "security", "MG Road, Kochi, Kerala 682016"),
    ("Pinnacle Legal Associates", "07", "AAKFP6643G", "legal", "Connaught Place, New Delhi 110001"),
    ("Greenleaf Housekeeping", "19", "ACFPG2257J", "facility", "Salt Lake Sector V, Kolkata 700091"),
]
CATALOG = {
    "office": [("A4 copier paper, 500 sheets", "4802", 18, 285, 1200), ("Ball pens, box of 50", "9608", 18, 240, 900),
               ("Stapler, heavy duty", "8472", 18, 450, 900), ("Box files", "4820", 12, 65, 200)],
    "cloud": [("Cloud compute, monthly", "998315", 18, 42000, 90000), ("Object storage, 5 TB", "998315", 18, 9500, 20000),
              ("Managed database, monthly", "998315", 18, 18000, 40000)],
    "logistics": [("Freight, Mumbai to Delhi (per tonne)", "996511", 12, 6200, 9000),
                  ("Last-mile delivery (per drop)", "996812", 18, 85, 160), ("Warehousing (per pallet-month)", "996729", 18, 650, 1100)],
    "print": [("Brochures, A4 tri-fold", "4911", 12, 9, 22), ("Visiting cards, box of 100", "4911", 12, 180, 420),
              ("Standee, roll-up", "4911", 18, 1400, 2600)],
    "facility": [("Housekeeping staff (per person-month)", "998533", 18, 16500, 21000),
                 ("Pest control service", "998531", 18, 3500, 7000), ("Floor deep-cleaning", "998533", 18, 9000, 15000)],
    "hardware": [("Laptop, 16 GB RAM", "8471", 18, 58000, 82000), ("27-inch monitor", "8528", 18, 14500, 22000),
                 ("Network switch, 24-port", "8517", 18, 18000, 32000), ("USB-C dock", "8471", 18, 6500, 11000)],
    "food": [("Working lunch (per plate)", "996333", 5, 280, 420), ("Tea and snacks (per person)", "996333", 5, 90, 150)],
    "packaging": [("Corrugated boxes, 5-ply", "4819", 12, 32, 58), ("Stretch film roll", "3920", 18, 520, 780),
                  ("Packing tape, 48 mm", "3919", 18, 38, 60)],
    "electrical": [("LED panel, 36 W", "9405", 12, 1150, 1800), ("Copper wire, 2.5 sq mm (90 m)", "8544", 18, 2900, 4100),
                   ("MCB, 32 A", "8536", 18, 210, 380)],
    "security": [("Security guard (per guard-month)", "998525", 18, 19500, 24500), ("CCTV maintenance visit", "998713", 18, 2500, 4500)],
    "legal": [("Contract review", "998212", 18, 25000, 60000), ("Trademark filing", "998213", 18, 9000, 15000)],
}  # fmt: skip
PROBLEMS = ["line_math", "total_math", "invalid_gstin", "wrong_tax_type", "tax_math", "missing_field", "future_date",
            "stale_date", "over_limit", "duplicate"]  # fmt: skip


def inr(x: float) -> str:
    """Indian digit grouping: 1,23,456.78"""
    neg = x < 0
    s = f"{abs(x):.2f}"
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return ("-" if neg else "") + whole + "." + frac


ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def words(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return ONES[n // 100] + " hundred" + (" and " + words(n % 100) if n % 100 else "")
    for div, name in ((10_000_000, "crore"), (100_000, "lakh"), (1000, "thousand")):
        if n >= div:
            return words(n // div) + f" {name}" + (" " + words(n % div) if n % div else "")
    return str(n)


@dataclass
class Inv:
    id: str
    layout: int
    vendor: dict
    number: str | None
    inv_date: date
    lines: list[dict]
    taxable: float
    cgst: float
    sgst: float
    igst: float
    total: float
    po: str | None
    problem: str | None


def build(rng: random.Random, i: int, problem: str | None, vendor_idx: int | None = None) -> Inv:
    name, st, pan, kind, addr = VENDORS[vendor_idx if vendor_idx is not None else rng.randrange(len(VENDORS))]
    vendor = {"name": name, "state": st, "gstin": make_gstin(st, pan), "address": addr}
    items = rng.sample(CATALOG[kind], k=min(len(CATALOG[kind]), rng.randint(1, 4)))
    lines = []
    for desc, hsn, rate, lo, hi in items:
        qty = rng.choice([1, 2, 3, 4, 5, 6, 10, 12, 20, 25, 50]) if lo < 2000 else rng.choice([1, 1, 2, 3])
        price = round(rng.uniform(lo, hi), 0)
        lines.append({"description": desc, "hsn": hsn, "quantity": qty, "unit_price": price,
                      "amount": round(qty * price, 2), "gst_rate": rate})  # fmt: skip
    if problem == "over_limit":
        lines[0]["quantity"] = max(lines[0]["quantity"], 1) * rng.choice([40, 60, 80])
        lines[0]["amount"] = round(lines[0]["quantity"] * lines[0]["unit_price"], 2)
        while sum(li["amount"] for li in lines) * 1.18 < 520_000:
            lines[0]["quantity"] *= 2
            lines[0]["amount"] = round(lines[0]["quantity"] * lines[0]["unit_price"], 2)
    if problem == "line_math":
        k = rng.randrange(len(lines))
        lines[k]["amount"] = round(lines[k]["amount"] + rng.choice([100, 250, 1000, -500]), 2)
    taxable = round(sum(li["amount"] for li in lines), 2)
    tax = round(sum(li["amount"] * li["gst_rate"] / 100 for li in lines), 2)
    if problem == "tax_math":
        tax = round(tax * rng.choice([1.5, 0.66, 1.4]), 2)  # e.g. 18% charged where the lines say 12%
    same_state = st == BUYER["gstin"][:2]
    interstate_wrong = problem == "wrong_tax_type"
    if same_state != interstate_wrong:  # wrong_tax_type flips the treatment
        cgst = sgst = round(tax / 2, 2)
        igst = 0.0
    else:
        cgst = sgst = 0.0
        igst = tax
    total = round(taxable + cgst + sgst + igst, 2)
    if problem == "total_math":
        total = round(total + rng.choice([500, 1200, -300, 2000]), 2)
    d = TODAY - timedelta(days=rng.randint(3, 75))
    if problem == "future_date":
        d = TODAY + timedelta(days=rng.randint(12, 40))
    if problem == "stale_date":
        d = TODAY - timedelta(days=rng.randint(220, 400))
    prefix = "".join(w[0] for w in name.split()[:2]).upper()
    number = f"{prefix}/{rng.choice(['2026-27', '26-27', 'FY27'])}/{rng.randint(101, 9899)}"
    if problem == "missing_field":
        number = None
    if problem == "invalid_gstin":
        g = vendor["gstin"]
        vendor = {**vendor, "gstin": g[:-1] + next(c for c in "ABCDEFGHJK" if c != g[-1])}
    po = f"PO-{rng.randint(24000, 26999)}" if rng.random() < 0.6 else None
    return Inv(
        f"inv-{i:03d}", rng.randrange(4), vendor, number, d, lines, taxable, cgst, sgst, igst, total, po, problem
    )


# ------------------------------------------------------------------------------------------------------ rendering
def _fmt_date(d: date, layout: int) -> str:
    return [d.strftime("%d-%m-%Y"), d.strftime("%d %b %Y"), d.strftime("%d/%m/%Y"), d.strftime("%d.%m.%Y")][layout]


LABELS = [
    {"title": "TAX INVOICE", "no": "Invoice No.", "date": "Invoice Date", "total": "Grand Total", "gstin": "GSTIN"},
    {"title": "Tax Invoice", "no": "Bill No", "date": "Dated", "total": "Amount Payable", "gstin": "GSTIN/UIN"},
    {"title": "INVOICE", "no": "Invoice #", "date": "Date", "total": "Total (INR)", "gstin": "Supplier GSTIN"},
    {"title": "TAX INVOICE (ORIGINAL FOR RECIPIENT)", "no": "Inv. No.", "date": "Inv. Date", "total": "Invoice Value",
     "gstin": "GST No."},
]  # fmt: skip


def render(inv: Inv, path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)  # byte-for-byte reproducible
    c.setTitle(f"Invoice {inv.number or ''}")
    W, H = A4
    L = LABELS[inv.layout]
    x0, y = 18 * mm, H - 20 * mm
    accent = [colors.HexColor("#1f3a5f"), colors.HexColor("#7a2e2e"), colors.HexColor("#245c3a"), colors.black][
        inv.layout
    ]

    # Header: vendor block left or centred depending on layout
    c.setFillColor(accent)
    if inv.layout == 1:
        c.rect(0, H - 34 * mm, W, 34 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16)
    if inv.layout == 3:
        c.drawCentredString(W / 2, y, inv.vendor["name"].upper())
    else:
        c.drawString(x0, y, inv.vendor["name"])
    c.setFont("Helvetica", 9)
    line2 = f"{inv.vendor['address']}  |  {L['gstin']}: {inv.vendor['gstin']}"
    if inv.layout == 3:
        c.drawCentredString(W / 2, y - 13, inv.vendor["address"])
        c.drawCentredString(
            W / 2,
            y - 25,
            f"{L['gstin']}: {inv.vendor['gstin']}   State: {STATES[inv.vendor['state']]} ({inv.vendor['state']})",
        )
    else:
        c.drawString(x0, y - 13, line2)
        c.drawString(x0, y - 25, f"State: {STATES[inv.vendor['state']]}, Code {inv.vendor['state']}")
    c.setFillColor(colors.black)
    y -= 50
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x0, y, L["title"])
    c.setFont("Helvetica", 9.5)
    meta = [(L["no"], inv.number or ""), (L["date"], _fmt_date(inv.inv_date, inv.layout)),
            ("Due Date", _fmt_date(inv.inv_date + timedelta(days=30), inv.layout))]  # fmt: skip
    if inv.po:
        meta.append(("Buyer PO", inv.po))
    meta.append(("Place of Supply", f"{STATES['07']} (07)"))
    mx = W - 80 * mm
    for k, (lab, val) in enumerate(meta):
        if inv.number is None and lab == L["no"]:
            continue
        c.drawString(mx, y - k * 13, f"{lab}:")
        c.drawString(mx + 30 * mm, y - k * 13, val)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(x0, y - 18, "Bill To:")
    c.setFont("Helvetica", 9.5)
    c.drawString(x0, y - 31, BUYER["name"])
    c.drawString(x0, y - 44, BUYER["address"])
    c.drawString(x0, y - 57, f"GSTIN: {BUYER['gstin']}")
    y -= 95

    # Line items
    cols = [("#", 8), ("Description", 70), ("HSN/SAC", 20), ("Qty", 14), ("Rate", 24), ("GST %", 14), ("Amount", 28)]
    if inv.layout == 2:
        cols = [("Description", 78), ("HSN", 18), ("Qty", 14), ("Unit Price", 26), ("GST", 12), ("Taxable Amt", 30)]
    xs = [x0]
    for _, w in cols:
        xs.append(xs[-1] + w * mm)
    c.setFillColor(colors.HexColor("#eef1f5") if inv.layout != 3 else colors.white)
    c.rect(x0, y - 4, xs[-1] - x0, 16, fill=1, stroke=inv.layout == 3)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    for (lab, _), x in zip(cols, xs, strict=False):
        c.drawString(x + 2, y + 2, lab)
    c.setFont("Helvetica", 9)
    for n, li in enumerate(inv.lines, start=1):
        y -= 16
        vals = [str(n), li["description"], li["hsn"], f"{li['quantity']:g}", inr(li["unit_price"]), f"{li['gst_rate']}%",
                inr(li["amount"])]  # fmt: skip
        if inv.layout == 2:
            vals = vals[1:]
        for v, x, (lab, w) in zip(vals, xs, cols, strict=False):
            if lab in ("Rate", "Amount", "Unit Price", "Taxable Amt"):
                c.drawRightString(x + w * mm - 8, y + 2, v)
            else:
                c.drawString(x + 2, y + 2, v)
    y -= 10
    c.line(x0, y, xs[-1], y)

    # Totals
    rows = [("Taxable Value" if inv.layout != 1 else "Sub Total", inv.taxable)]
    if inv.cgst or inv.sgst:
        half = [li["gst_rate"] / 2 for li in inv.lines]
        rate = f" @ {half[0]:g}%" if len(set(half)) == 1 else ""
        rows += [(f"CGST{rate}", inv.cgst), (f"SGST{rate}", inv.sgst)]
    if inv.igst:
        rates = {li["gst_rate"] for li in inv.lines}
        rows.append((f"IGST @ {next(iter(rates))}%" if len(rates) == 1 else "IGST", inv.igst))
    rows.append((L["total"], inv.total))
    tx = xs[-1] - 70 * mm
    for k, (lab, val) in enumerate(rows):
        bold = k == len(rows) - 1
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10 if bold else 9.5)
        c.drawString(tx, y - 16 - k * 14, lab)
        c.drawRightString(xs[-1] - 3, y - 16 - k * 14, ("Rs. " if bold else "") + inr(val))
    y -= 30 + len(rows) * 14
    c.setFont("Helvetica-Oblique", 8.5)
    rupees = int(inv.total)
    paise = int(round((inv.total - rupees) * 100))
    amount_words = f"Rupees {words(rupees)}" + (f" and {words(paise)} paise" if paise else "") + " only"
    c.drawString(x0, y, "Amount in words: " + amount_words.capitalize())

    # Footer clutter
    c.setFont("Helvetica", 8)
    fy = 40 * mm
    c.drawString(x0, fy, "Bank: State Bank of India, Current A/c (details on request)   IFSC: SBIN000XXXX")
    c.drawString(
        x0,
        fy - 11,
        "Terms: Payment within 30 days. Interest @ 18% p.a. on overdue amounts. Subject to local jurisdiction.",
    )
    c.drawString(x0, fy - 22, "This is a computer generated invoice.")
    c.drawRightString(W - x0, fy - 22, f"For {inv.vendor['name']}  -  Authorised Signatory")
    c.save()


def truth(inv: Inv) -> dict:
    return {
        "vendor_name": inv.vendor["name"],
        "vendor_gstin": inv.vendor["gstin"],
        "buyer_gstin": BUYER["gstin"],
        "invoice_number": inv.number,
        "invoice_date": inv.inv_date.isoformat(),
        "po_number": inv.po,
        "taxable_value": inv.taxable,
        "cgst": inv.cgst,
        "sgst": inv.sgst,
        "igst": inv.igst,
        "total": inv.total,
        "line_items": [
            {k: li[k] for k in ("description", "quantity", "unit_price", "amount", "gst_rate")} for li in inv.lines
        ],
    }


EXPECT = {
    None: ("approve", []), "line_math": ("review", ["line_math", "subtotal_math?"]), "total_math": ("review", ["total_math"]),
    "invalid_gstin": ("review", ["invalid_gstin"]), "wrong_tax_type": ("review", ["wrong_tax_type"]),
    "tax_math": ("review", ["tax_math", "total_math?"]), "missing_field": ("review", ["missing_field"]),
    "future_date": ("review", ["future_date"]), "stale_date": ("review", ["stale_date"]),
    "over_limit": ("review", ["over_limit"]), "duplicate": ("reject", ["duplicate"]),
}  # fmt: skip


def main() -> None:
    rng = random.Random(20261120)
    out = ROOT / "pdfs"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.pdf"):
        old.unlink()
    plan: list[str | None] = [None] * 32
    for p in PROBLEMS:
        plan += [p] * (4 if p == "duplicate" else 3)  # 3 of each kind, 4 duplicates -> 31 problem invoices
    rng.shuffle(plan)
    # Duplicates must come after the invoice they repeat: move them to the back half.
    dups = [k for k, p in enumerate(plan) if p == "duplicate"]
    for k in dups:
        plan[k] = None
    plan = plan[: len(plan) - len(dups)] + ["__dup__"] * len(dups)
    invs: list[Inv] = []
    clean_pool: list[Inv] = []
    for i, p in enumerate(plan, start=1):
        if p == "__dup__":
            src = clean_pool.pop(rng.randrange(len(clean_pool)))
            inv = Inv(f"inv-{i:03d}", (src.layout + 1 + rng.randrange(3)) % 4, src.vendor, src.number, src.inv_date,
                      src.lines, src.taxable, src.cgst, src.sgst, src.igst, src.total, src.po, "duplicate")  # fmt: skip
            inv.duplicate_of = src.id  # type: ignore[attr-defined]
        else:
            inv = build(rng, i, p)
            if p is None and inv.total <= 500_000:
                clean_pool.append(inv)
        invs.append(inv)
    rows = []
    for k, inv in enumerate(invs):
        render(inv, out / f"{inv.id}.pdf")
        route, codes = EXPECT[inv.problem]
        rows.append({
            "id": inv.id, "file": f"pdfs/{inv.id}.pdf", "layout": inv.layout,
            "split": "dev" if k % 4 == 0 else "test",  # every 4th invoice is for tuning; the rest are held out
            "problem": inv.problem, "expected_route": route,
            "expected_issues": [c for c in codes if not c.endswith("?")],
            "allowed_issues": [c.rstrip("?") for c in codes],
            "duplicate_of": getattr(inv, "duplicate_of", None), "truth": truth(inv),
        })  # fmt: skip
    # A clean invoice can legitimately be over the limit by chance; record that honestly.
    for r in rows:
        if r["problem"] is None and r["truth"]["total"] > 500_000:
            r["expected_route"], r["expected_issues"], r["allowed_issues"] = "review", ["over_limit"], ["over_limit"]
    # Duplicates must land in the same split as the invoice they repeat (the ledger is per run).
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        if r["duplicate_of"]:
            r["split"] = by_id[r["duplicate_of"]]["split"]
    meta = {"today": TODAY.isoformat(), "buyer": BUYER, "count": len(rows)}
    (ROOT / "truth.json").write_text(json.dumps({"meta": meta, "invoices": rows}, indent=1))
    from collections import Counter

    print(len(rows), "invoices;", Counter(r["split"] for r in rows), Counter(r["expected_route"] for r in rows))


if __name__ == "__main__":
    main()
