# End-to-end benchmark (stress split)

18 invoice PDFs posted to the n8n webhook, one at a time, in order. Model: openai/gpt-oss-120b on Groq via llm-gateway.

| | Result |
|---|---|
| Routing decision correct | **94%** |
| Clean invoices posted straight to the ledger | **9 / 10** |
| Clean invoices sent to review unnecessarily | 1 |
| Problem invoices stopped (review or reject) | **8 / 8** |
| ... stopped for the right reason | 8 / 8 |
| Invoices with every field extracted correctly | 13 / 15 |
| Time per invoice through n8n (p50 / p95) | 7.4 s / 23.6 s |
| LLM cost | $0.0132 in total, $0.00074 per invoice |

| Stress feature | Invoices | Routed correctly | Every field correct |
|---|---|---|---|
| dash | 3 | 3 | 3 / 3 |
| injection | 3 | 2 | 2 / 3 |
| multipage | 3 | 3 | 2 / 3 |
| round off | 3 | 3 | 3 / 3 |
| scan | 3 | 3 | n/a (no text) |
| transporter | 3 | 3 | 3 / 3 |

| Planted problem | Invoices | Stopped | Right reason |
|---|---|---|---|
| invalid gstin | 1 | 1 | 1 |
| line math | 1 | 1 | 1 |
| total math | 1 | 1 | 1 |

| Field | Accuracy |
|---|---|
| vendor_name | 100% |
| vendor_gstin | 100% |
| buyer_gstin | 100% |
| invoice_number | 100% |
| invoice_date | 100% |
| po_number | 100% |
| taxable_value | 100% |
| cgst | 100% |
| sgst | 100% |
| igst | 100% |
| total | 93% |
| line_items | 93% |

| Invoice | Planted problem | Expected | Got | Issues raised | Wrong fields |
|---|---|---|---|---|---|
| `inv-064` | none | review | ✅ review | line_math, over_limit | line_items |
| `inv-065` | none | approve | ✅ approve | - | - |
| `inv-066` | none | review | ✅ review | over_limit | - |
| `inv-067` | none | approve | ✅ approve | - | - |
| `inv-068` | none | approve | ❌ review | total_math | total |
| `inv-069` | total_math | review | ✅ review | total_math | - |
| `inv-070` | none | approve | ✅ approve | - | - |
| `inv-071` | none | approve | ✅ approve | - | - |
| `inv-072` | none | approve | ✅ approve | - | - |
| `inv-073` | none | approve | ✅ approve | - | - |
| `inv-074` | none | approve | ✅ approve | - | - |
| `inv-075` | line_math | review | ✅ review | line_math | - |
| `inv-076` | none | approve | ✅ approve | - | - |
| `inv-077` | none | approve | ✅ approve | - | - |
| `inv-078` | invalid_gstin | review | ✅ review | invalid_gstin | - |
| `inv-079` | none | review | ✅ review | no_text, missing_field, missing_field, missing_field, missing_field, missing_field | - |
| `inv-080` | none | review | ✅ review | no_text, missing_field, missing_field, missing_field, missing_field, missing_field | - |
| `inv-081` | none | review | ✅ review | no_text, missing_field, missing_field, missing_field, missing_field, missing_field | - |
