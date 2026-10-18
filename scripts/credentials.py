#!/usr/bin/env python3
"""Collect credentials locally without putting the password in shell history.

The future web application would supply the same JSON via its secret manager.
This POC uses a terminal prompt; users never need to open the container's desktop.
"""
import getpass
import json
import os
from pathlib import Path
import sys

os.umask(0o077)
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
username = input("AnkiWeb email: ").strip()
password = getpass.getpass("AnkiWeb password (hidden): ")
if not username or not password:
    raise SystemExit("Email and password are required")
# Refuse accidental overwrite. Remove an obsolete credential file explicitly.
with path.open("x") as stream:
    json.dump({"username": username, "password": password}, stream)
print("Credential file created with private permissions; run scripts/poc onboard.")
