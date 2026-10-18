#!/usr/bin/env python3
"""Export only synthetic POC request evidence; never copy configuration or logs."""
from datetime import datetime, timezone
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
records = []
for label in ("A", "C-restart", "C-recreate", "D"):
    # Restrict the report to the four named experiments. Tutorial labels such
    # as demo-01 should not silently replace the evidence from the original run.
    path = root / ".state" / (label + ".json")
    if path.exists():
        record = json.loads(path.read_text())
        records.append(record)
payload = {"exported_at": datetime.now(timezone.utc).isoformat(),
           "scope": "Synthetic text-only test cards; phone timestamps require human confirmation",
           "records": records}
# ensure_ascii=False keeps Polish/Japanese text readable rather than escaping
# it as \uXXXX. The output contains synthetic cards, not account credentials.
(root / "docs" / "evidence.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
for record in records:
    print(record["label"], "note", record["note_id"], "phone", bool(record["phone_observed_at_ms"]))
    for attempt in record["sync"]:
        # Missing completion is None, not a duration of zero. Phone observation
        # time is separate and must not be presented as exact delivery latency.
        elapsed = (attempt["confirmed_at_ms"] - attempt["requested_at_ms"]
                   if attempt["confirmed_at_ms"] else None)
        print(" ", attempt["status"], "request_ms", attempt["request_latency_ms"], "confirmed_ms", elapsed)
