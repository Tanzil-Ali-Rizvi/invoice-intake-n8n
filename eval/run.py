"""End-to-end benchmark: post each invoice PDF to the running n8n webhook and score what comes back.

Everything goes through the real workflow (webhook -> PDF text -> LLM via llm-gateway -> rules -> ledger/review),
so the numbers measure the system as deployed, not a Python re-implementation of it.

    python eval/run.py --split test            # needs the stack running (docker compose up)
    python eval/run.py --split dev --mock      # plumbing check with the stand-in LLM (not a result)
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "dataset"
OUT = ROOT / "results"
FIELDS = ["vendor_name", "vendor_gstin", "buyer_gstin", "invoice_number", "invoice_date", "po_number",
          "taxable_value", "cgst", "sgst", "igst", "total"]  # fmt: skip


def _norm_text(v) -> str:
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower())


def field_ok(name: str, got, want) -> bool:
    if want is None:
        return got in (None, "", 0, 0.0) if name not in ("cgst", "sgst", "igst") else (got or 0) == 0
    if isinstance(want, (int, float)):
        try:
            return got is not None and abs(float(got) - float(want)) <= 0.01
        except (TypeError, ValueError):
            return False
    return _norm_text(got) == _norm_text(want)


def lines_ok(got: list, want: list) -> bool:
    if len(got or []) != len(want):
        return False
    g = sorted(round(float(x.get("amount") or 0), 2) for x in got)
    w = sorted(round(float(x["amount"]), 2) for x in want)
    return g == w and sorted(float(x.get("quantity") or 0) for x in got) == sorted(float(x["quantity"]) for x in want)


def score(rows: list[dict]) -> dict:
    n = len(rows)
    clean = [r for r in rows if r["problem"] is None and r["expected_route"] == "approve"]
    problems = [r for r in rows if r["expected_route"] != "approve"]
    out = {
        "invoices": n,
        "route_accuracy": round(sum(r["route"] == r["expected_route"] for r in rows) / n, 3),
        "clean": len(clean),
        "straight_through": sum(r["route"] == "approve" for r in clean),
        "clean_sent_to_review": sum(r["route"] == "review" for r in clean),
        "clean_rejected": sum(r["route"] == "reject" for r in clean),
        "problems": len(problems),
        "problems_stopped": sum(r["route"] != "approve" for r in problems),
        "problems_right_reason": sum(
            r["route"] == r["expected_route"] and set(r["expected_issues"]) <= set(r["issues"]) for r in problems
        ),  # fmt: skip
        "by_problem": {},
        "confusion": dict(Counter(f"{r['expected_route']}->{r['route']}" for r in rows)),
        "fields": {},
        "all_fields_correct": sum(r["all_fields_ok"] for r in rows),
        "seconds_p50": round(statistics.median(r["seconds"] for r in rows), 1),
        "seconds_p95": round(sorted(r["seconds"] for r in rows)[max(0, int(0.95 * n) - 1)], 1),
    }
    for p in sorted({r["problem"] for r in problems if r["problem"]}):
        sub = [r for r in problems if r["problem"] == p]
        out["by_problem"][p] = {"n": len(sub), "stopped": sum(r["route"] != "approve" for r in sub),
                                "right_reason": sum(set(r["expected_issues"]) <= set(r["issues"]) for r in sub)}  # fmt: skip
    scored = [r for r in rows if r.get("score_fields", True)]  # scans have no text to extract
    for f in FIELDS + ["line_items"]:
        out["fields"][f] = round(sum(r["field_ok"][f] for r in scored) / len(scored), 3) if scored else None
    out["all_fields_correct"] = sum(r["all_fields_ok"] for r in scored)
    out["field_scored"] = len(scored)
    for feat in sorted({r.get("feature") for r in rows if r.get("feature")}):
        sub = [r for r in rows if r.get("feature") == feat]
        out["by_feature"][feat] = {"n": len(sub), "route_ok": sum(r["route"] == r["expected_route"] for r in sub),
                                   "fields_ok": sum(r["all_fields_ok"] for r in sub if r.get("score_fields", True)),
                                   "fields_n": sum(1 for r in sub if r.get("score_fields", True))}  # fmt: skip
    return out


def to_md(s: dict, rows: list[dict], meta: dict) -> str:
    lines = [
        f"# End-to-end benchmark ({meta['split']} split)",
        "",
        f"{s['invoices']} invoice PDFs posted to the n8n webhook, one at a time, in order. Model: {meta['model']}.",
        "",
        "| | Result |",
        "|---|---|",
        f"| Routing decision correct | **{s['route_accuracy']:.0%}** |",
        f"| Clean invoices posted straight to the ledger | **{s['straight_through']} / {s['clean']}** |",
        f"| Clean invoices sent to review unnecessarily | {s['clean_sent_to_review']} |",
        f"| Problem invoices stopped (review or reject) | **{s['problems_stopped']} / {s['problems']}** |",
        f"| ... stopped for the right reason | {s['problems_right_reason']} / {s['problems']} |",
        f"| Invoices with every field extracted correctly | {s['all_fields_correct']} / {s['field_scored']} |",
        f"| Time per invoice through n8n (p50 / p95) | {s['seconds_p50']} s / {s['seconds_p95']} s |",
    ]
    if meta.get("cost_usd") is not None:
        lines.append(
            f"| LLM cost | ${meta['cost_usd']:.4f} in total, ${meta['cost_usd'] / s['invoices']:.5f} per invoice |"
        )
    if s["by_feature"]:
        lines += ["", "| Stress feature | Invoices | Routed correctly | Every field correct |", "|---|---|---|---|"]
        for f, v in s["by_feature"].items():
            fields = f"{v['fields_ok']} / {v['fields_n']}" if v["fields_n"] else "n/a (no text)"
            lines.append(f"| {f.replace('_', ' ')} | {v['n']} | {v['route_ok']} | {fields} |")
    lines += ["", "| Planted problem | Invoices | Stopped | Right reason |", "|---|---|---|---|"]
    for p, v in s["by_problem"].items():
        lines.append(f"| {p.replace('_', ' ')} | {v['n']} | {v['stopped']} | {v['right_reason']} |")
    lines += ["", "| Field | Accuracy |", "|---|---|"] + [
        f"| {k} | {v:.0%} |" for k, v in s["fields"].items() if v is not None
    ]
    lines += [
        "",
        "| Invoice | Planted problem | Expected | Got | Issues raised | Wrong fields |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        mark = "✅" if r["route"] == r["expected_route"] else "❌"
        lines.append(f"| `{r['id']}` | {r['problem'] or 'none'} | {r['expected_route']} | {mark} {r['route']} | "
                     f"{', '.join(r['issues']) or '-'} | {', '.join(r['wrong_fields']) or '-'} |")  # fmt: skip
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["dev", "test", "stress", "all"])
    ap.add_argument("--n8n", default="http://localhost:5678/webhook/invoice")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--gateway", default="http://localhost:8080")
    ap.add_argument("--gateway-key", default="local-admin-key")
    ap.add_argument(
        "--mock", action="store_true", help="the stack runs the stand-in LLM; label results as plumbing only"
    )
    ap.add_argument("--pause", type=float, default=2.0)
    a = ap.parse_args()

    truth = json.loads((DATA / "truth.json").read_text())
    todo = [r for r in truth["invoices"] if a.split == "all" or r["split"] == a.split]
    c = httpx.Client(timeout=300)
    c.post(f"{a.api}/reset").raise_for_status()
    rows = []
    for r in todo:
        t0 = time.perf_counter()
        with open(DATA / r["file"], "rb") as fh:
            resp = c.post(a.n8n, files={"data": (Path(r["file"]).name, fh, "application/pdf")})
        secs = time.perf_counter() - t0
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code != 200 or "route" not in body:
            print(f"{r['id']}: HTTP {resp.status_code} {resp.text[:200]}", file=sys.stderr)
            body = {"route": "error", "issues": [], "invoice": {}}
        inv = body.get("invoice") or {}
        fok = {f: field_ok(f, inv.get(f), r["truth"].get(f)) for f in FIELDS}
        fok["line_items"] = lines_ok(inv.get("line_items") or [], r["truth"]["line_items"])
        if not r.get("score_fields", True):
            fok = dict.fromkeys(fok, True)
        row = {"id": r["id"], "problem": r["problem"], "expected_route": r["expected_route"],
               "feature": r.get("feature"), "score_fields": r.get("score_fields", True),
               "expected_issues": r["expected_issues"], "route": body.get("route"),
               "issues": [i.get("code") for i in body.get("issues", [])], "seconds": round(secs, 2),
               "field_ok": fok, "all_fields_ok": all(fok.values()),
               "wrong_fields": [k for k, v in fok.items() if not v], "summary": body.get("summary", ""),
               "invoice": inv}  # fmt: skip
        rows.append(row)
        print(f"{r['id']} {r['problem'] or 'clean':15} expected={r['expected_route']:7} got={row['route']:7} "
              f"{secs:5.1f}s wrong={row['wrong_fields']}")  # fmt: skip
        time.sleep(a.pause)
    meta = {
        "split": a.split,
        "model": "stand-in LLM (plumbing check only)" if a.mock else "openai/gpt-oss-120b on Groq via llm-gateway",
    }
    if not a.mock:
        try:
            u = c.get(f"{a.gateway}/admin/usage", params={"group_by": "route", "hours": 6},
                      headers={"Authorization": f"Bearer {a.gateway_key}"}).json()  # fmt: skip
            meta["cost_usd"] = round(sum(float(x.get("cost_usd", 0) or 0) for x in u.get("rows", [])), 5)
            meta["gateway_usage"] = u.get("rows", [])
        except Exception as e:  # noqa: BLE001
            print("could not read gateway usage:", e, file=sys.stderr)
    s = score(rows)
    OUT.mkdir(exist_ok=True)
    name = f"e2e_{a.split}" + ("_mock" if a.mock else "")
    (OUT / f"{name}.json").write_text(json.dumps({"summary": s, "meta": meta, "rows": rows}, indent=1))
    (OUT / f"{name}.md").write_text(to_md(s, rows, meta))
    print(json.dumps(s, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
