#!/bin/sh
# Import both workflows from the repo (overwriting older copies), publish the intake workflow, then start n8n.
set -e
n8n import:workflow --input=/workflows/intake-errors.json
n8n import:workflow --input=/workflows/invoice-intake.json
n8n publish:workflow --id=InvoiceIntake001
exec n8n start
