"""The intake steps in Python, mirroring the n8n workflow node for node. Used by the web demo, which cannot run n8n;
the benchmark always goes through real n8n.

    Invoice received -> Fingerprint file -> Read PDF text -> Extract fields (LLM) -> Check against AP rules
    -> Route -> Post to ledger | Queue for review | Reject duplicate -> Reply
"""

from __future__ import annotations

import hashlib
import io
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .decide import decide
from .extract import messages, parse_json
from .store import Store

STATUS = {"approve": "approved", "review": "review", "reject": "rejected"}


@dataclass
class Step:
    node: str
    ms: float
    output: Any


@dataclass
class Run:
    steps: list[Step] = field(default_factory=list)
    route: str = ""
    invoice_id: int | None = None
    summary: str = ""
    issues: list[dict] = field(default_factory=list)
    checks_passed: list[str] = field(default_factory=list)
    invoice: dict = field(default_factory=dict)
    cost_usd: float = 0.0


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    try:
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    except Exception:  # noqa: BLE001  (a broken PDF reads as no text and goes to review)
        return ""


class GatewayLLM:
    """My llm-gateway, embedded in-process: Groq gpt-oss-120b with fallback to 20b, retries and cost tracking."""

    def __init__(self) -> None:
        from llmgw.config import GatewayConfig
        from llmgw.gateway import Gateway

        self.gw = Gateway(GatewayConfig.model_validate({
            "providers": {"groq": {"type": "openai", "base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY",
                                   "timeout_s": 90, "models": {"openai/gpt-oss-120b": {"input_per_1m": 0.15, "output_per_1m": 0.60},
                                                               "openai/gpt-oss-20b": {"input_per_1m": 0.075, "output_per_1m": 0.30}}}},
            "routes": {"intake": ["groq/openai/gpt-oss-120b", "groq/openai/gpt-oss-20b"]}, "default_route": "intake",
            "database": ":memory:", "require_auth": False, "cache": {"enabled": False},
            "retry": {"attempts_per_target": 3, "backoff_s": 1.0, "max_retry_after_s": 20},
        }))  # fmt: skip

    async def chat(self, msgs: list[dict]) -> tuple[str | None, float, str]:
        from llmgw.gateway import GatewayError

        body = {"model": "intake", "messages": msgs, "temperature": 0, "response_format": {"type": "json_object"}}
        try:
            out = await self.gw.chat(body, None)
        except GatewayError as e:
            return None, 0.0, f"{e.status}: {e.message}"[:200]
        content = ((out.body or {}).get("choices") or [{}])[0].get("message", {}).get("content")
        return content, float(out.headers.get("x-gateway-cost-usd", 0) or 0), out.headers.get("x-gateway-target", "")


async def run_intake(data: bytes, file_name: str, llm: Any, store: Store, buyer_gstin: str, today: date,
                     recorded: dict | None = None) -> Run:  # fmt: skip
    """`recorded`: a stored extraction to replay instead of calling the LLM (the demo without a key)."""
    r = Run()

    def step(node: str, t0: float, output: Any) -> None:
        r.steps.append(Step(node, round((time.perf_counter() - t0) * 1000, 1), output))

    t = time.perf_counter()
    step("Invoice received", t, {"file": file_name, "bytes": len(data)})
    t = time.perf_counter()
    sha = hashlib.sha256(data).hexdigest()
    step("Fingerprint file", t, {"file_sha256": sha})
    t = time.perf_counter()
    text = pdf_text(data)
    step("Read PDF text", t, {"characters": len(text), "text": text})
    t = time.perf_counter()
    if recorded is not None:
        content, cost, target = recorded, 0.0, "recorded answer (no API key on this deployment)"
    elif llm is None:
        content, cost, target = None, 0.0, "no LLM configured"
    else:
        content, cost, target = await llm.chat(messages(text))
    r.cost_usd = cost
    step("Extract fields (LLM)", t, {"model": target, "answer": parse_json(content) if content else None})
    t = time.perf_counter()
    d = decide(content, len(text.strip()), sha, store, buyer_gstin, today)
    r.route, r.issues, r.checks_passed, r.invoice, r.summary = (
        d["route"],
        d["issues"],
        d["checks_passed"],
        d["invoice"],
        d["summary"],
    )
    issues = r.issues
    store.audit("validated", None, file=file_name, route=r.route, issues=[i["code"] for i in issues])
    step("Check against AP rules", t, {"route": r.route, "issues": issues, "checks_passed": r.checks_passed})
    node = {"approve": "Post to ledger", "review": "Queue for review", "reject": "Reject duplicate"}[r.route]
    t = time.perf_counter()
    r.invoice_id = store.add(STATUS[r.route], r.invoice, {"route": r.route, "issues": issues}, file_name, sha)
    store.audit(f"recorded_{STATUS[r.route]}", r.invoice_id, file=file_name)
    step("Route", t, {"branch": node})
    step(node, t, {"id": r.invoice_id, "status": STATUS[r.route]})
    step("Reply", time.perf_counter(), {"route": r.route, "invoice_id": r.invoice_id, "summary": r.summary})
    return r
