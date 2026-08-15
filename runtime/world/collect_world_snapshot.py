#!/usr/bin/env python3
"""Harbor ``[[verifier.collect]]`` hook: capture the final world snapshot.

Runs after the agent is torn down and before the verifier starts, so what it
writes is the state the grader diffs against the initial snapshot.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

PORT = os.environ.get("PORT", "8000")
DEST = Path(os.environ.get("WORLD_LOGS_DIR", "/logs/world")) / "final_snapshot.tar.gz"
HOOKS = Path("/app/tools/snapshot_hooks.json")
READ_TIMEOUT_SEC = 300
CHUNK = 65536


def main() -> None:
    body = b"{}"
    if HOOKS.exists():
        body = json.dumps({"pre_snapshot_hooks": json.loads(HOOKS.read_text())}).encode()

    request = urllib.request.Request(
        f"http://localhost:{PORT}/data/snapshot",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    partial = DEST.with_suffix(DEST.suffix + ".partial")
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=READ_TIMEOUT_SEC) as resp:
        if resp.status != 200:
            sys.exit(f"snapshot failed: HTTP {resp.status}")
        with partial.open("wb") as fh:
            while chunk := resp.read(CHUNK):
                fh.write(chunk)

    # Publish atomically: the grader treats "exists and non-empty" as complete,
    # so a truncated file would grade as a real (empty) world.
    partial.replace(DEST)
    print(f"final snapshot: {DEST.stat().st_size} bytes", flush=True)


if __name__ == "__main__":
    main()
