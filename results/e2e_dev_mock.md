# End-to-end benchmark (dev split)

16 invoice PDFs posted to the n8n webhook, one at a time, in order. Model: stand-in LLM (plumbing check only).

| | Result |
|---|---|
| Routing decision correct | **100%** |
| Clean invoices posted straight to the ledger | **9 / 9** |
| Clean invoices sent to review unnecessarily | 0 |
| Problem invoices stopped (review or reject) | **7 / 7** |
| ... stopped for the right reason | 7 / 7 |
| Invoices with every field extracted correctly | 16 / 16 |
| Time per invoice through n8n (p50 / p95) | 0.1 s / 0.2 s |

| Planted problem | Invoices | Stopped | Right reason |
|---|---|---|---|
| duplicate | 1 | 1 | 1 |
| future date | 1 | 1 | 1 |
| missing field | 3 | 3 | 3 |
| over limit | 2 | 2 | 2 |

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
| `inv-001` | none | approve | ✅ approve | - | - |
| `inv-005` | future_date | review | ✅ review | future_date | - |
| `inv-009` | none | approve | ✅ approve | - | - |
| `inv-013` | missing_field | review | ✅ review | missing_field | - |
| `inv-017` | none | approve | ✅ approve | - | - |
| `inv-021` | missing_field | review | ✅ review | missing_field | - |
| `inv-025` | over_limit | review | ✅ review | over_limit | - |
| `inv-029` | over_limit | review | ✅ review | over_limit | - |
| `inv-033` | none | approve | ✅ approve | - | - |
| `inv-037` | none | approve | ✅ approve | - | - |
| `inv-041` | missing_field | review | ✅ review | missing_field | - |
| `inv-045` | none | approve | ✅ approve | - | - |
| `inv-049` | none | approve | ✅ approve | - | - |
| `inv-053` | none | approve | ✅ approve | - | - |
| `inv-057` | none | approve | ✅ approve | - | - |
| `inv-063` | duplicate | reject | ✅ reject | duplicate | - |
