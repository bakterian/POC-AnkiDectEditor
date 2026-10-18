"""Exercise the compiled CLI against a stateful fault-injecting HTTP server."""
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import unittest

BINARY = Path(os.environ.get("ANKI_TEST_BINARY",
    str(Path(__file__).resolve().parents[1] / "target/debug/anki-poc")))

class DriverTests(unittest.TestCase):
    def setUp(self):
        # unittest calls setUp before EACH test. Give every test its own fake
        # collection, journal directory and counters so order does not matter.
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.key = "test-key-" + "a" * 40
        (self.root / "key").write_text(self.key)
        self.notes = []
        self.add_count = 0
        self.sync_count = 0
        self.mode = "normal"
        self.sync_state = "succeeded"
        self.profile = "POC"
        owner = self
        # Handler methods have their own `self` (the HTTP request handler).
        # `owner` keeps access to this enclosing test case and its fake data.
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/api/v1":
                    assert self.headers["Authorization"] == "Bearer " + owner.key
                    name = data["method"]
                    if name == "collection.get": result = {"profile":owner.profile, "session":"session"}
                    elif name == "api.describe": result = {"ankiVersion":"26.09.3", "methods":[
                        {"name":n,"available":True} for n in ("collection.sync","operations.get")]}
                    elif name == "collection.sync":
                        # Count submissions independently of status polling: a
                        # faulty retry must not hide behind a plausible result.
                        owner.sync_count += 1
                        result = {"operationId":"op1", "method":"collection.sync", "session":"session"}
                        if owner.mode == "lost-sync":
                            self.connection.shutdown(socket.SHUT_RDWR)
                            self.connection.close()
                            return
                    elif name == "operations.get":
                        result = {"operationId":"op1", "method":"collection.sync", "state":owner.sync_state,
                                  "result":{"collectionComplete":True,"mediaComplete":False}}
                    else: raise AssertionError(name)
                    reply = {"jsonrpc":"2.0", "id":data["id"], "result":result}
                else:
                    assert data["key"] == owner.key
                    name, params = data["action"], data.get("params", {})
                    error = None
                    if name == "version": result = 6
                    elif name == "getActiveProfile": result = owner.profile
                    elif name == "deckNames": result = ["POC"]
                    elif name == "modelNames": result = ["Basic"]
                    elif name == "modelFieldNames": result = ["Front","Back"]
                    elif name == "findNotes": result = [n["noteId"] for n in owner.notes if params["query"][4:] in n["tags"]]
                    elif name == "addNote":
                        owner.add_count += 1
                        if owner.mode == "reject-add":
                            result, error = None, "deliberate rejection"
                        else:
                            draft = params["note"]
                            result = 100 + len(owner.notes)
                            note = {"noteId":result, "modelName":draft["modelName"], "tags":draft["tags"],
                                    "fields":{k:{"value":v} for k,v in draft["fields"].items()},"cards":[result+1000]}
                            owner.notes.append(note)
                            if owner.mode == "lost-add":
                                # Commit the fake note, then close the connection
                                # before replying. This models an ambiguous write:
                                # the client sees failure but the note exists.
                                self.connection.shutdown(socket.SHUT_RDWR)
                                self.connection.close()
                                return
                    elif name == "notesInfo": result = [n for n in owner.notes if n["noteId"] in params["notes"]]
                    elif name == "cardsInfo": result = [{"cardId":c,"note":c-1000,"deckName":"POC"} for c in params["cards"]]
                    else: raise AssertionError(name)
                    reply = {"result":result,"error":error}
                encoded = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
        # Port 0 asks the OS for an unused local port. The server runs on a
        # background thread while the real Rust CLI runs as a separate process.
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.env = {**os.environ, "ANKI_URL":f"http://127.0.0.1:{self.server.server_port}",
            "ANKI_API_KEY_FILE":str(self.root / "key"), "ANKI_STATE_DIR":str(self.root / "state"),
            "ANKI_PROFILE":"POC", "ANKI_DECK":"POC", "ANKI_MODEL":"Basic"}

    def tearDown(self):
        # Stop the server and join its thread before deleting temporary files.
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def cli(self, *args, ok=True):
        """Run the actual binary, assert its exit status, and check secret hygiene."""
        proc = subprocess.run([BINARY, *args], env=self.env, capture_output=True, text=True, timeout=40)
        self.assertEqual(proc.returncode == 0, ok, proc.stdout + proc.stderr)
        self.assertNotIn(self.key, proc.stdout + proc.stderr)
        return proc

    def record(self): return json.loads((self.root / "state/A.json").read_text())

    def test_create_readback_repeat_and_sync(self):
        self.cli("create","A")
        self.cli("create","A")
        self.assertEqual(self.add_count,1)
        self.assertIn("zażółć gęślą jaźń",self.record()["front"])
        self.cli("sync","A")
        self.cli("sync","A")
        self.assertEqual(self.sync_count,1)
        self.assertEqual(self.record()["sync"][-1]["status"],"sync_confirmed")
        self.assertIsNone(self.record()["phone_observed_at_ms"])
        self.cli("confirm-phone","A",ok=False)
        self.cli("confirm-phone","A","--observed")

    def test_lost_creation_response_reuses_original(self):
        self.mode = "lost-add"
        self.cli("create","A")
        self.cli("create","A")
        self.assertEqual(self.add_count,1)
        self.assertEqual(self.record()["creation"],"created_locally")

    def test_ambiguous_zero_matches_never_reposts(self):
        # Even after a rejection, the POC deliberately takes its cautious path.
        # This test includes the real ~20-second reconciliation deadline.
        self.mode = "reject-add"
        self.cli("create","A",ok=False)
        self.cli("create","A",ok=False)
        self.assertEqual(self.add_count,1)
        self.assertEqual(self.record()["creation"],"failed_unknown")

    def test_duplicate_matches_stop(self):
        self.cli("create","A")
        self.notes.append({**self.notes[0], "noteId":101})
        self.cli("create","A",ok=False)
        self.assertEqual(self.add_count,1)

    def test_wrong_profile_is_not_ready(self):
        self.profile = "Other"
        self.cli("ready","--once",ok=False)

    def test_waiting_for_user_is_not_success_and_cannot_retry(self):
        self.cli("create","A")
        self.sync_state = "waitingForUser"
        self.cli("sync","A",ok=False)
        self.cli("retry-sync","A",ok=False)
        self.assertEqual(self.sync_count,1)
        self.assertEqual(self.record()["sync"][-1]["status"],"waiting_for_user")

    def test_failed_sync_retry_never_adds_again(self):
        # Changing the fake operation to success models restored connectivity.
        # We expect two sync submissions but still only one note submission.
        self.cli("create","A")
        self.sync_state = "failed"
        self.cli("sync","A",ok=False)
        self.sync_state = "succeeded"
        self.cli("retry-sync","A")
        self.assertEqual(self.add_count,1)
        self.assertEqual(self.sync_count,2)

    def test_lost_sync_ack_blocks_retry(self):
        self.cli("create","A")
        self.mode = "lost-sync"
        self.cli("sync","A",ok=False)
        self.cli("sync","A",ok=False)
        self.cli("retry-sync","A",ok=False)
        self.assertEqual(self.sync_count,1)

    def test_readback_corruption_is_rejected(self):
        self.cli("create","A")
        self.notes[0]["fields"]["Front"]["value"] = "corrupted"
        self.cli("verify","A",ok=False)

    def test_concurrent_command_is_rejected(self):
        # Hold the same OS lock in Python. The separate Rust process must fail
        # to acquire it; merely testing two functions in one process would miss it.
        self.cli("create","A")
        with (self.root / "state/driver.lock").open("r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.cli("create","A",ok=False)
        self.assertEqual(self.add_count,1)

if __name__ == "__main__": unittest.main(verbosity=2)
