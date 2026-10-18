#!/usr/bin/env python3
"""Generate local secrets once, never echo them or store account credentials."""
import os
from pathlib import Path
import secrets
import sys

# __file__ locates this script, even when invoked from another working directory.
root = Path(__file__).resolve().parent.parent
os.umask(0o077)
secret_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else root / ".secrets"
state_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else root / ".state"
for directory in (secret_dir, state_dir):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
for name, value in (("api-key", secrets.token_hex(32)),):
    # secrets uses the OS's secure random generator: 32 bytes = 64 hex characters.
    path = secret_dir / name
    if not path.exists():
        # Mode "x" refuses to overwrite an existing file, even if another init
        # process created it after our exists() check. Reruns preserve secrets.
        with path.open("x") as f:
            f.write(value + "\n")
if len(sys.argv) == 1 and not (root / ".env").exists():
    # Match host user/group IDs so the short-lived driver container can read
    # the private secret file and write .state without creating root-owned files.
    text = (root / ".env.example").read_text()
    text = text.replace("LOCAL_UID=1000", f"LOCAL_UID={os.getuid()}")
    text = text.replace("LOCAL_GID=1000", f"LOCAL_GID={os.getgid()}")
    (root / ".env").write_text(text)
print("Local configuration initialized. Secrets are in the configured private directory (not printed).")
