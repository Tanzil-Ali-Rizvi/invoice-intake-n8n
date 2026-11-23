"""Web demo: push an invoice through the intake steps and see each node's output, the decision and the queues.

Streamlit cannot run n8n, so this runs the same steps in Python (same prompt, same rules, same storage). The real
n8n workflow is what CI and the benchmark run.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))

from intake.pipeline import GatewayLLM, run_intake  # noqa: E402
from intake.store import Store  # noqa: E402

st.set_page_config(page_title="Invoice intake with n8n", page_icon="🧾", layout="wide")
try:
    if "GROQ_API_KEY" in st.secrets and not os.getenv("GROQ_API_KEY"):
        os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]
except Exception:  # noqa: BLE001  (no secrets file)
    pass

TRUTH = json.loads((ROOT / "dataset" / "truth.json").read_text())
BUYER = TRUTH["meta"]["buyer"]
DEMO_TODAY = date.fromisoformat(TRUTH["meta"]["today"])  # the sample invoices are dated around this day
IST = timezone(timedelta(hours=5, minutes=30))
ICON = {"approve": "✅", "review": "🟠", "reject": "⛔"}
WORD = {"approve": "Posted to the ledger", "review": "Sent to the review queue", "reject": "Rejected"}


@st.cache_resource
def loop():
    lp = asyncio.new_event_loop()
    threading.Thread(target=lp.run_forever, daemon=True).start()
    return lp


@st.cache_resource
def _llm(key_fp: str):
    return GatewayLLM() if key_fp else None


def llm():
    key = os.getenv("GROQ_API_KEY", "")
    return _llm(str(hash(key)) if key else "")


@st.cache_data
def recorded_answers() -> dict:
    """Extractions recorded by the benchmark through real n8n: used when this deployment has no API key."""
    out = {}
    for name in ("e2e_test.json", "e2e_dev.json"):
        p = ROOT / "results" / name
        if p.exists():
            out |= {r["id"]: r.get("invoice") for r in json.loads(p.read_text())["rows"] if r.get("invoice")}
    return out


@st.cache_data
def preview(data: bytes) -> bytes | None:
    try:
        import io

        import pypdfium2 as pdfium

        page = pdfium.PdfDocument(data)[0]
        img = page.render(scale=1.3).to_pil()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return None


if "store" not in st.session_state:
    st.session_state.store = Store()  # each visitor gets a private ledger and review queue
    st.session_state.runs = []
store: Store = st.session_state.store

st.title("🧾 Invoice intake: n8n + LLM + accounts-payable rules")
st.write(
    "An n8n workflow receives a vendor invoice PDF, reads its text, has an LLM extract the fields, and sends them to a "
    "rules service that checks the GSTIN, the arithmetic, the tax type, the dates and duplicates. Clean invoices post "
    "straight to the ledger; anything doubtful goes to a person. "
    "[Workflow, code and benchmark](https://github.com/Tanzil-Ali-Rizvi/invoice-intake-n8n)"
)
wf = ROOT / "docs" / "n8n-workflow.png"
if wf.exists():
    st.image(str(wf), caption="The n8n workflow (this page runs the same steps in Python; CI runs the real n8n).")

left, right = st.columns([1, 1.3], gap="large")
with left:
    source = st.radio("Invoice", ["A sample invoice", "Upload a PDF"], horizontal=True)
    sample_id = None
    if source == "A sample invoice":
        rows = TRUTH["invoices"]
        labels = {r["id"]: f"{r['id']} · {r['truth']['vendor_name']}" for r in rows}
        sample_id = st.selectbox("Sample (fictional vendors; some invoices have planted problems)", list(labels),
                                 format_func=labels.get)  # fmt: skip
        row = next(r for r in rows if r["id"] == sample_id)
        data = (ROOT / "dataset" / row["file"]).read_bytes()
        fname = Path(row["file"]).name
        today = DEMO_TODAY
        st.caption(f"Checks run as of {DEMO_TODAY:%d %b %Y}, the date the sample set is built around.")
    else:
        up = st.file_uploader("A text-based PDF invoice (scans have no text layer and will go to review)", type=["pdf"])
        data, fname, today = (up.getvalue(), up.name, datetime.now(IST).date()) if up else (b"", "", DEMO_TODAY)
        st.caption(
            f"Bills are expected to be addressed to {BUYER['name']} (GSTIN {BUYER['gstin']}), the fictional buyer."
        )
    have_llm = llm() is not None
    recorded = recorded_answers().get(sample_id) if sample_id else None
    if not have_llm:
        st.info("No LLM key on this deployment: samples replay the extraction recorded when they ran through n8n.")
    go = st.button(
        "Run intake", type="primary", width="stretch", disabled=not data or (not have_llm and recorded is None)
    )
    if data:
        img = preview(data)
        if img:
            st.image(img, width="stretch")

with right:
    if go:
        with st.spinner("Running the workflow steps…"):
            fut = asyncio.run_coroutine_threadsafe(
                run_intake(data, fname, llm() if have_llm else None, store, BUYER["gstin"], today,
                           recorded=None if have_llm else json.dumps(recorded)),
                loop(),
            )  # fmt: skip
            run = fut.result(timeout=240)
        st.session_state.runs.insert(0, run)
    if st.session_state.runs:
        run = st.session_state.runs[0]
        st.subheader(f"{ICON[run.route]} {WORD[run.route]}")
        st.write(run.summary)
        a, b = st.columns(2)
        with a:
            st.markdown("**Checks passed**")
            for c in run.checks_passed:
                st.markdown(f"- {c}")
        with b:
            st.markdown("**Issues**")
            for i in run.issues or [{"message": "None"}]:
                st.markdown(f"- {i['message']}")
        st.markdown("**Workflow steps**")
        for s in run.steps:
            with st.expander(f"{s.node}  ·  {s.ms:.0f} ms"):
                out = dict(s.output) if isinstance(s.output, dict) else s.output
                if isinstance(out, dict) and "text" in out:
                    st.text(out.pop("text")[:3000])
                st.json(out)
        if run.cost_usd:
            st.caption(f"LLM cost for this invoice: ${run.cost_usd:.5f}")
    else:
        st.write("Pick an invoice and press **Run intake**.")

st.divider()
t1, t2, t3, t4 = st.tabs(["Review queue", "Ledger", "Audit log", "Benchmark"])
with t1:
    queue = store.list("review")
    if not queue:
        st.write("Nothing waiting for review.")
    for inv in queue:
        with st.container(border=True):
            total = f"Rs {inv['total']:,.2f}" if inv["total"] is not None else "no total"
            st.markdown(
                f"**#{inv['id']} · {inv['vendor_name'] or 'Unknown vendor'} · {inv['invoice_number'] or '(no number)'} · {total}**"
            )
            for i in inv["decision"].get("issues", []):
                st.markdown(f"- {i['message']}")
            c1, c2, _ = st.columns([1, 1, 4])
            if c1.button("Approve", key=f"a{inv['id']}"):
                store.decide(inv["id"], True, "demo reviewer")
                st.rerun()
            if c2.button("Reject", key=f"r{inv['id']}"):
                store.decide(inv["id"], False, "demo reviewer")
                st.rerun()
with t2:
    rows = [{"#": r["id"], "Vendor": r["vendor_name"], "Invoice": r["invoice_number"], "Date": r["invoice_date"],
             "Total": r["total"], "Approved by": r["decided_by"] or "rules (straight through)"} for r in store.list("approved")]  # fmt: skip
    st.dataframe(rows, width="stretch", hide_index=True) if rows else st.write("The ledger is empty.")
with t3:
    log = [
        {"At": a["at"], "Invoice": a["invoice_id"], "Event": a["event"], "Detail": json.dumps(a["detail"])}
        for a in store.audit_log()
    ]
    st.dataframe(log, width="stretch", hide_index=True) if log else st.write("No events yet.")
with t4:
    bench = ROOT / "results" / "e2e_test.md"
    st.markdown(
        bench.read_text().split("\n| Invoice |")[0] if bench.exists() else "The benchmark has not been run yet."
    )
