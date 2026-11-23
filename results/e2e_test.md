# End-to-end benchmark (test split)

47 invoice PDFs posted to the n8n webhook, one at a time, in order. Model: openai/gpt-oss-120b on Groq via llm-gateway.

| | Result |
|---|---|
| Routing decision correct | **100%** |
| Clean invoices posted straight to the ledger | **25 / 25** |
| Clean invoices sent to review unnecessarily | 0 |
| Problem invoices stopped (review or reject) | **22 / 22** |
| ... stopped for the right reason | 22 / 22 |
| Invoices with every field extracted correctly | 47 / 47 |
| Time per invoice through n8n (p50 / p95) | 6.6 s / 11.1 s |
| LLM cost | $0.0230 in total, $0.00049 per invoice |

| Planted problem | Invoices | Stopped | Right reason |
|---|---|---|---|
| duplicate | 3 | 3 | 3 |
| future date | 2 | 2 | 2 |
| invalid gstin | 3 | 3 | 3 |
| line math | 2 | 2 | 2 |
| over limit | 1 | 1 | 1 |
| stale date | 3 | 3 | 3 |
| tax math | 3 | 3 | 3 |
| total math | 2 | 2 | 2 |
| wrong tax type | 3 | 3 | 3 |

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
| total | 100% |
| line_items | 100% |

| Invoice | Planted problem | Expected | Got | Issues raised | Wrong fields |
|---|---|---|---|---|---|
| `inv-002` | invalid_gstin | review | ✅ review | invalid_gstin | - |
| `inv-003` | future_date | review | ✅ review | future_date | - |
| `inv-004` | wrong_tax_type | review | ✅ review | wrong_tax_type | - |
| `inv-006` | none | approve | ✅ approve | - | - |
| `inv-007` | wrong_tax_type | review | ✅ review | wrong_tax_type | - |
| `inv-008` | none | approve | ✅ approve | - | - |
| `inv-010` | tax_math | review | ✅ review | tax_math | - |
| `inv-011` | invalid_gstin | review | ✅ review | invalid_gstin | - |
| `inv-012` | none | approve | ✅ approve | - | - |
| `inv-014` | line_math | review | ✅ review | line_math | - |
| `inv-015` | none | approve | ✅ approve | - | - |
| `inv-016` | stale_date | review | ✅ review | stale_date | - |
| `inv-018` | line_math | review | ✅ review | line_math | - |
| `inv-019` | none | approve | ✅ approve | - | - |
| `inv-020` | none | approve | ✅ approve | - | - |
| `inv-022` | none | approve | ✅ approve | - | - |
| `inv-023` | none | approve | ✅ approve | - | - |
| `inv-024` | total_math | review | ✅ review | total_math | - |
| `inv-026` | none | approve | ✅ approve | - | - |
| `inv-027` | none | approve | ✅ approve | - | - |
| `inv-028` | none | approve | ✅ approve | - | - |
| `inv-030` | none | approve | ✅ approve | - | - |
| `inv-031` | wrong_tax_type | review | ✅ review | wrong_tax_type | - |
| `inv-032` | none | approve | ✅ approve | - | - |
| `inv-034` | stale_date | review | ✅ review | stale_date | - |
| `inv-035` | none | approve | ✅ approve | - | - |
| `inv-036` | none | approve | ✅ approve | - | - |
| `inv-038` | none | approve | ✅ approve | - | - |
| `inv-039` | invalid_gstin | review | ✅ review | invalid_gstin | - |
| `inv-040` | none | approve | ✅ approve | - | - |
| `inv-042` | total_math | review | ✅ review | total_math | - |
| `inv-043` | none | approve | ✅ approve | - | - |
| `inv-044` | none | approve | ✅ approve | - | - |
| `inv-046` | none | approve | ✅ approve | - | - |
| `inv-047` | none | approve | ✅ approve | - | - |
| `inv-048` | over_limit | review | ✅ review | over_limit | - |
| `inv-050` | future_date | review | ✅ review | future_date | - |
| `inv-051` | stale_date | review | ✅ review | stale_date | - |
| `inv-052` | none | approve | ✅ approve | - | - |
| `inv-054` | none | approve | ✅ approve | - | - |
| `inv-055` | none | approve | ✅ approve | - | - |
| `inv-056` | tax_math | review | ✅ review | tax_math | - |
| `inv-058` | tax_math | review | ✅ review | tax_math | - |
| `inv-059` | none | approve | ✅ approve | - | - |
| `inv-060` | duplicate | reject | ✅ reject | duplicate | - |
| `inv-061` | duplicate | reject | ✅ reject | duplicate | - |
| `inv-062` | duplicate | reject | ✅ reject | duplicate | - |
