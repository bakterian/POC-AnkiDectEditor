"""Keep Anki and its virtual display alive, and coordinate a graceful shutdown.

Anki is still a desktop application. Xvfb supplies its invisible screen, but no
VNC server, browser bridge, or window manager is needed for this API-only service.
"""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request

# Adopt the descriptor locked by entrypoint.py. Keeping this object alive
# keeps the volume lock held for this supervisor's entire lifetime.
lock = os.fdopen(int(os.environ["POC_LOCK_FD"]), "a+")
os.umask(0o077)
children = []
stopping = False

def stop(*_):
    """A signal handler only sets a flag; normal code below does the cleanup."""
    global stopping
    stopping = True

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

def launch(args):
    """Popen starts a child without waiting for it; retain it for health/cleanup."""
    proc = subprocess.Popen(args)
    children.append(proc)
    return proc

launch(["Xvfb", ":99", "-screen", "0", "1280x800x24", "-nolisten", "tcp"])
# Wait for a concrete startup signal (the X11 socket), with a deadline.
# monotonic() measures elapsed time even if the wall clock changes.
deadline = time.monotonic() + 15
while not Path("/tmp/.X11-unix/X99").exists():
    if time.monotonic() > deadline:
        raise SystemExit("Xvfb startup timed out")
    time.sleep(0.1)
# Profile metadata must be ready before the desktop app opens the collection.
# check=True aborts startup if this child reports a nonzero exit status.
subprocess.run(["python3", "/opt/poc/prepare_profile.py"], check=True)
anki = launch(["anki", "-b", "/data", "-p", os.environ["ANKI_PROFILE"]])
# poll() returns None while a child is running, otherwise its exit status.
# Required-child failure triggers shutdown; there are no optional presentation processes.
while anki.poll() is None and not stopping:
    if any(p.poll() is not None for p in children):
        stopping = True
        break
    time.sleep(0.25)
if anki.poll() is None:
    # Ask the application to close its collection itself. Killing it immediately
    # would skip that cleanup and would not prove safe persistent storage.
    try:
        body = json.dumps({"action": "guiExitAnki", "version": 6,
                           "key": Path("/run/poc/api-key").read_text()}).encode()
        request = urllib.request.Request("http://127.0.0.1:8765", body,
                                         {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            reply = json.load(response)
        if reply.get("error"):
            print("Graceful close request rejected; inspect logs and onboarding status", flush=True)
    except Exception:
        print("Graceful close unavailable; inspect logs and onboarding status", flush=True)
    try:
        # Leave room inside Compose's 90-second stop timeout for other cleanup.
        anki.wait(timeout=70)
    except subprocess.TimeoutExpired:
        print("Anki did not close gracefully; shutdown is NOT verified", flush=True)
        # Docker eventually enforces its stop timeout. Never report a clean stop.
        raise SystemExit(2)
for proc in reversed(children):
    # Anki has already exited here. Only remaining support processes are stopped;
    # forced termination here is not our method of closing the collection.
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
raise SystemExit(anki.returncode or 0)
