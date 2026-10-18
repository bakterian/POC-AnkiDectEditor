#!/usr/bin/env python3
"""Capture allowlisted completion metadata; omit upstream free-text errors."""
import json
from pathlib import Path
import urllib.request

root = Path(__file__).resolve().parent.parent
key = (root / ".secrets/api-key").read_text().strip()
records = []
for path in sorted((root / ".state").glob("*.json")):
    record = json.loads(path.read_text())
    for attempt in record["sync"]:
        # These handles belong to the running Anki process. Older handles may
        # have expired or disappeared after a restart; keep that fact visible.
        operation_id = attempt["operation_id"]
        if not operation_id:
            continue
        body = json.dumps({"jsonrpc":"2.0", "id":1, "method":"operations.get",
                           "params":{"operationId":operation_id}}).encode()
        request = urllib.request.Request("http://127.0.0.1:8765/api/v1", body,
            {"Authorization":"Bearer " + key, "Content-Type":"application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            # The context manager closes the HTTP response even if parsing fails.
            reply = json.load(response)
        result = {"label": record["label"], "operationId": operation_id}
        if "error" in reply:
            # This marks an unavailable observation, not a failed historical sync.
            # It does not overwrite the driver's already-persisted evidence.
            result["available"] = False
        else:
            result["available"] = True
            operation = reply["result"]
            for field in ("method", "state", "createdAt", "updatedAt"):
                # Copy an allowlist of fields rather than serializing the whole
                # response, whose free-text errors could contain private details.
                result[field] = operation.get(field)
            result["collectionComplete"] = operation.get("result", {}).get("collectionComplete")
            result["errorType"] = operation.get("error", {}).get("data", {}).get("type")
        records.append(result)
(root / "docs/operations.json").write_text(json.dumps(records, indent=2) + "\n")
print("Saved sanitized operation metadata (handles from earlier processes may be unavailable).")
