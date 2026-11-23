"""Build the n8n workflows from source, so the extraction prompt lives in one file (prompts/extract_system.md) and the
workflow JSON is reviewable and reproducible.

    python workflows/build.py        # writes workflows/invoice-intake.json and workflows/intake-errors.json

The workflow reads three environment variables at run time: LLM_URL (an OpenAI-compatible chat endpoint; in the
stack, my llm-gateway), LLM_MODEL (the gateway route) and INTAKE_API_URL (the rules service).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPT = (ROOT / "prompts" / "extract_system.md").read_text()
INTAKE_ID = "InvoiceIntake001"
ERRORS_ID = "IntakeErrors0001"


def node(name: str, type_: str, version: float, x: int, y: int, params: dict, **extra) -> dict:
    return {"id": name.lower().replace(" ", "-").replace("(", "").replace(")", ""), "name": name, "type": type_,
            "typeVersion": version, "position": [x, y], "parameters": params, **extra}  # fmt: skip


def http_post(url_expr: str, body_expr: str, timeout_ms: int = 30_000) -> dict:
    return {
        "method": "POST",
        "url": url_expr,
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": body_expr,
        "options": {"timeout": timeout_ms},
    }


BUILD_REQUEST = """// Build the chat request for the extraction model. The prompt is injected by workflows/build.py from
// prompts/extract_system.md, the same file the Python demo uses.
const PROMPT = %s;
const MAX_TEXT = 12000;
return $input.all().map((item, index) => {
  const text = (item.json.text || '').trim();
  return {
    json: {
      text_chars: text.length,
      llm_request: {
        model: $env.LLM_MODEL || 'intake',
        temperature: 0,
        response_format: { type: 'json_object' },
        messages: [
          { role: 'system', content: PROMPT },
          { role: 'user', content: 'Invoice text:\\n<invoice>\\n' + text.slice(0, MAX_TEXT) + '\\n</invoice>' },
        ],
      },
    },
    pairedItem: { item: index },  // keeps $('Earlier node').item lookups working downstream
  };
});"""

VALIDATE_BODY = (
    "={{ JSON.stringify({"
    " extraction: ($json.choices && $json.choices[0] && $json.choices[0].message) ? $json.choices[0].message.content : null,"
    " file_name: $('Invoice received').item.binary.data ? $('Invoice received').item.binary.data.fileName : '',"
    " file_sha256: $('Fingerprint file').item.json.file_sha256,"
    " text_chars: $('Build extraction request').item.json.text_chars"
    " }) }}"
)


def record_body(route: str) -> str:
    v = "$('Check against AP rules').item.json"
    return (
        "={{ JSON.stringify({ route: '" + route + "', invoice: " + v + ".invoice, decision: " + v + ","
        " file_name: $('Invoice received').item.binary.data ? $('Invoice received').item.binary.data.fileName : '',"
        " file_sha256: $('Fingerprint file').item.json.file_sha256 }) }}"
    )


def switch_rule(value: str, key: str) -> dict:
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
            "conditions": [
                {
                    "id": f"route-{value}",
                    "leftValue": "={{ $json.route }}",
                    "rightValue": value,
                    "operator": {"type": "string", "operation": "equals"},
                }
            ],  # fmt: skip
            "combinator": "and",
        },
        "renameOutput": True,
        "outputKey": key,
    }


def intake() -> dict:
    if "{{" in PROMPT or "}}" in PROMPT:
        raise ValueError("the prompt must not contain '{{' or '}}' (n8n expression delimiters)")
    api = "={{ $env.INTAKE_API_URL }}"
    reply = (
        "={{ JSON.stringify({ route: $('Check against AP rules').item.json.route,"
        " invoice_id: $json.id, status: $json.status,"
        " summary: $('Check against AP rules').item.json.summary,"
        " issues: $('Check against AP rules').item.json.issues,"
        " checks_passed: $('Check against AP rules').item.json.checks_passed,"
        " invoice: $('Check against AP rules').item.json.invoice }) }}"
    )
    nodes = [
        node("Invoice received", "n8n-nodes-base.webhook", 2, 0, 300,
             {"httpMethod": "POST", "path": "invoice", "responseMode": "responseNode", "options": {}},
             webhookId="7f1c2a90-intake-invoice"),
        node("Fingerprint file", "n8n-nodes-base.crypto", 2, 220, 300,
             {"action": "hash", "type": "SHA256", "binaryData": True, "binaryPropertyName": "data",
              "dataPropertyName": "file_sha256", "encoding": "hex"}),
        node("Read PDF text", "n8n-nodes-base.extractFromFile", 1, 440, 300,
             {"operation": "pdf", "binaryPropertyName": "data", "options": {}}),
        node("Build extraction request", "n8n-nodes-base.code", 2, 660, 300,
             {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": BUILD_REQUEST % json.dumps(PROMPT)}),
        node("Extract fields (LLM)", "n8n-nodes-base.httpRequest", 4.2, 880, 300,
             http_post("={{ $env.LLM_URL }}", "={{ JSON.stringify($json.llm_request) }}", 180_000),
             retryOnFail=True, maxTries=3, waitBetweenTries=3000, onError="continueRegularOutput",
             notes="If the model fails after 3 tries, the empty answer flows on and the rules send the invoice to review."),
        node("Check against AP rules", "n8n-nodes-base.httpRequest", 4.2, 1100, 300,
             {**http_post("=" + api[1:] + "/validate", VALIDATE_BODY)}),
        node("Route", "n8n-nodes-base.switch", 3.2, 1320, 300,
             {"rules": {"values": [switch_rule("approve", "Approve"), switch_rule("review", "Review"),
                                   switch_rule("reject", "Reject")]}, "options": {}}),
        node("Post to ledger", "n8n-nodes-base.httpRequest", 4.2, 1560, 120, http_post("=" + api[1:] + "/record", record_body("approve"))),
        node("Queue for review", "n8n-nodes-base.httpRequest", 4.2, 1560, 300, http_post("=" + api[1:] + "/record", record_body("review"))),
        node("Reject duplicate", "n8n-nodes-base.httpRequest", 4.2, 1560, 480, http_post("=" + api[1:] + "/record", record_body("reject"))),
        node("Reply", "n8n-nodes-base.respondToWebhook", 1.1, 1800, 300,
             {"respondWith": "json", "responseBody": reply, "options": {}}),
    ]  # fmt: skip
    connections = {
        "Invoice received": {"main": [[{"node": "Fingerprint file", "type": "main", "index": 0}]]},
        "Fingerprint file": {"main": [[{"node": "Read PDF text", "type": "main", "index": 0}]]},
        "Read PDF text": {"main": [[{"node": "Build extraction request", "type": "main", "index": 0}]]},
        "Build extraction request": {"main": [[{"node": "Extract fields (LLM)", "type": "main", "index": 0}]]},
        "Extract fields (LLM)": {"main": [[{"node": "Check against AP rules", "type": "main", "index": 0}]]},
        "Check against AP rules": {"main": [[{"node": "Route", "type": "main", "index": 0}]]},
        "Route": {"main": [[{"node": "Post to ledger", "type": "main", "index": 0}],
                           [{"node": "Queue for review", "type": "main", "index": 0}],
                           [{"node": "Reject duplicate", "type": "main", "index": 0}]]},
        "Post to ledger": {"main": [[{"node": "Reply", "type": "main", "index": 0}]]},
        "Queue for review": {"main": [[{"node": "Reply", "type": "main", "index": 0}]]},
        "Reject duplicate": {"main": [[{"node": "Reply", "type": "main", "index": 0}]]},
    }  # fmt: skip
    return {
        "id": INTAKE_ID,
        "name": "Invoice intake",
        "nodes": nodes,
        "connections": connections,
        "settings": {
            "executionOrder": "v1",
            "errorWorkflow": ERRORS_ID,
            "saveDataSuccessExecution": "all",
            "saveManualExecutions": True,
            "timezone": "Asia/Kolkata",
        },  # fmt: skip
        "active": False,
        "pinData": {},
        "tags": [],
    }


def errors() -> dict:
    body = (
        "={{ JSON.stringify({ event: 'workflow_error', detail: { workflow: $json.workflow.name,"
        " node: $json.execution.lastNodeExecuted, message: $json.execution.error.message,"
        " execution_id: $json.execution.id } }) }}"
    )
    nodes = [
        node("Workflow failed", "n8n-nodes-base.errorTrigger", 1, 0, 300, {}),
        node("Log to audit trail", "n8n-nodes-base.httpRequest", 4.2, 240, 300,
             http_post("={{ $env.INTAKE_API_URL }}/events", body)),
    ]  # fmt: skip
    return {
        "id": ERRORS_ID,
        "name": "Invoice intake errors",
        "nodes": nodes,
        "connections": {"Workflow failed": {"main": [[{"node": "Log to audit trail", "type": "main", "index": 0}]]}},
        "settings": {"executionOrder": "v1"},
        "active": False,
        "pinData": {},
        "tags": [],
    }


def main() -> None:
    out = ROOT / "workflows"
    (out / "invoice-intake.json").write_text(json.dumps(intake(), indent=2) + "\n")
    (out / "intake-errors.json").write_text(json.dumps(errors(), indent=2) + "\n")
    print("wrote", out / "invoice-intake.json", "and", out / "intake-errors.json")


if __name__ == "__main__":
    main()
