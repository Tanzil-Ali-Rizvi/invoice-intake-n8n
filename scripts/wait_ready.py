"""Wait until the intake service is up and n8n has registered the published webhook."""

import sys
import time

import httpx

deadline = time.time() + 240
while time.time() < deadline:
    try:
        api = httpx.get("http://localhost:8000/health", timeout=3).status_code == 200
        # The webhook answers 404 until the published workflow is registered. An empty POST then fails inside the
        # workflow (no file), which is fine: the benchmark resets the service before it starts.
        hook = httpx.post("http://localhost:5678/webhook/invoice", timeout=10)
        live = hook.status_code != 404
        if api and live:
            print("ready")
            sys.exit(0)
    except httpx.HTTPError:
        pass
    time.sleep(3)
print("timed out waiting for the stack", file=sys.stderr)
sys.exit(1)
