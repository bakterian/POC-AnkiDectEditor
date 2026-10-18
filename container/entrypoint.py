"""Prepare the container as root, then run Anki as an ordinary Linux user.

Docker starts this file first. It prepares files and permissions; it does not
log in to AnkiWeb, create notes, or decide which collection wins a full sync.
"""
import json
import fcntl
import os
from pathlib import Path
import shutil

# A umask removes permission bits from newly created files. 0o077 means that
# group/other users receive no access; secret files normally become mode 0600.
os.umask(0o077)
Path("/tmp/.X11-unix").mkdir(exist_ok=True)
# X11 expects this shared socket directory to have the sticky bit (0o1000),
# like /tmp. Individual users cannot remove each other's entries there.
os.chmod("/tmp/.X11-unix", 0o1777)
base = Path("/data")
base.mkdir(exist_ok=True)
# LOCK_EX is exclusive; LOCK_NB means fail immediately instead of waiting.
# Take the lock BEFORE touching add-on/profile files. A second container must
# not change the live collection even if it will fail later when opening Anki.
lock = open(base / ".process.lock", "a+")
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
# exec replaces this process. Keep its lock file descriptor open across that
# replacement, and tell supervisor.py which descriptor number to adopt.
os.set_inheritable(lock.fileno(), True)
os.environ["POC_LOCK_FD"] = str(lock.fileno())
run = Path("/run/poc")
run.mkdir(exist_ok=True)
for name in ("api-key",):
    # Compose mounts host secret files read-only. Copy them into a private
    # runtime directory that we can give to the non-root Anki user below.
    value = Path("/run/secrets", name).read_text().strip()
    if not value or "PLACEHOLDER" in value:
        raise SystemExit("Initialize local secrets before starting")
    (run / name).write_text(value)
if os.environ.get("POC_BOOTSTRAP_ONLY") == "1":
    # Passwords are bytes in a read-only secret mount, never environment values.
    # Preserve JSON/password whitespace exactly; only the API key is stripped.
    source = Path("/run/secrets/ankiweb.json")
    if not source.is_file():
        raise SystemExit("Credential secret required for onboarding")
    (run / "ankiweb.json").write_bytes(source.read_bytes())
addon = base / "addons21" / "ankiconnect"
revision = Path("/opt/poc/ankiconnect-revision").read_text().strip()
marker = base / "ankiconnect-revision"
# Persist the installed revision beside the collection. A newly built image
# must not silently upgrade/downgrade this add-on in an existing volume.
if marker.exists() and marker.read_text().strip() != revision:
    raise SystemExit("Add-on revision changed: back up and explicitly migrate the volume")
shutil.copytree("/opt/anki-connect/plugin", addon, dirs_exist_ok=True)
config = json.loads((addon / "config.json").read_text())
# 0.0.0.0 is inside the container: the driver uses a different container, so
# container-loopback would not be reachable. Compose limits host publication
# to 127.0.0.1, and this key authenticates both AnkiConnect API endpoints.
config.update(apiKey=(run / "api-key").read_text(), apiLogPath=None,
              webBindAddress="0.0.0.0", webBindPort=8765,
              webCorsOriginList=[], ignoreOriginList=[])
(addon / "config.json").write_text(json.dumps(config))
# Anki stores user overrides in meta.json; make the effective configuration explicit.
(addon / "meta.json").write_text(json.dumps({"disabled": False, "config": config}))
marker.write_text(revision + "\n")
for tree in (base, run):
    # These are dedicated POC paths, not the host user's installed Anki files.
    for current, directories, files in os.walk(tree):
        os.chown(current, 1000, 1000)
        for name in directories + files:
            os.chown(Path(current, name), 1000, 1000)
# gosu switches user and exec replaces the program, rather than leaving a root
# parent shell behind. supervisor.py then receives Docker's shutdown signals.
program = "onboarding.py" if os.environ.get("POC_BOOTSTRAP_ONLY") == "1" else "supervisor.py"
os.execvp("gosu", ["gosu", "anki", "python3", f"/opt/poc/{program}"])
