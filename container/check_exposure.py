"""Read-only checks that APIs reject missing/wrong keys and presentation listeners are absent.

Run inside the Anki container. A failed assert exits nonzero, making the check
usable by scripts/poc exposure. Use normal Python, not python -O (which removes
assert statements). Host port bindings are inspected separately by the runner.
"""
import json
import socket
import urllib.request
import urllib.error

for key in (None, "wrong-key"):
    # Deliberately avoid the real key: this is a negative authentication test.
    body = {"action": "deckNames", "version": 6}
    if key is not None:
        body["key"] = key
    request = urllib.request.Request("http://127.0.0.1:8765", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        reply = json.load(response)
    assert reply.get("error"), "Legacy API accepted an unauthenticated read"
    # Legacy API errors are JSON in a 200 response; v1 authentication failures
    # instead use HTTP 401. Test each contract in its own way.
    request = urllib.request.Request("http://127.0.0.1:8765/api/v1",
        json.dumps({"jsonrpc":"2.0", "id":1, "method":"collection.get"}).encode(),
        {"Content-Type":"application/json", **({"Authorization":"Bearer " + key} if key else {})})
    try:
        urllib.request.urlopen(request, timeout=5)
        raise AssertionError("v1 API accepted an unauthenticated read")
    except urllib.error.HTTPError as error:
        assert error.code == 401
for port in (5900, 6080):
    # A published Docker port alone does not tell us whether a service is
    # listening. Confirm both removed display listeners are actually absent.
    with socket.socket() as sock:
        sock.settimeout(1)
        assert sock.connect_ex(("127.0.0.1", port)) != 0, "Unexpected presentation listener"
print("PASS: both API endpoints reject missing/wrong keys; presentation listeners are absent")
