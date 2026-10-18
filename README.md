# POC-AnkiDectEditor

POC of the an Application allowing remote edition/expansion of your private ANKI Card Decs. In this POC we are testing more specifically the Anki integraion part.  

Personal, add-only experiment: Rust CLI → private AnkiConnect → Anki Desktop under
Xvfb in Docker → AnkiWeb → explicit sync on a test phone. The host's installed Anki
and its collection are not used. See [original results](docs/results.md) and [onboarding results](docs/onboarding-results.md) for what was actually
tested; implementation alone is not proof of phone delivery or cloud operation.

For a guided explanation of the Python/Rust code, rendered component/sequence
diagrams, and hands-on command examples, read the
[architecture and walkthrough](docs/architecture-and-walkthrough.md).

## Requirements and pinned components

- Linux x86-64 host, Docker Engine 28+ and Docker Compose with Buildx. This run uses
  Engine 29.9.1 and Compose 5.6.0. Only x86-64 is being validated.
- Dedicated AnkiWeb account and isolated AnkiDroid/AnkiMobile collection.
- Rust 1.90.0 builds inside Docker; a host Rust installation is optional.
- Anki/aqt 26.9.3, Qt 6.8.1, AnkiConnect revision
  `760ff48d8bbcfbc956f57c40475a8ab960c36a9c` (requires Anki ≥26.8).
- Python and Rust base images are pinned by digest in `container/Dockerfile`.
  Cargo.lock pins Rust transitive dependencies and `container/constraints.txt` pins
  the resolved Python dependencies. OS packages are inventoried below and their
  repositories can change between rebuilds. Record
  the final image ID with `scripts/poc doctor` and retain that image for experiments.

## Initialize, connect an account, and start

```sh
scripts/poc init
scripts/poc build
scripts/poc credentials  # Host terminal prompt; password input is hidden
scripts/poc onboard     # Backend login + initial Download
scripts/poc up
scripts/poc driver ready
scripts/poc exposure
```

For an existing authenticated POC volume, `scripts/poc up` is sufficient. To apply
this new image to the old running container, use `scripts/poc recreate` after the
build. It preserves the data volume. Account onboarding and reauthentication must
run while that user's service is stopped.

Read [unattended onboarding](docs/onboarding.md) for the credential JSON contract,
initial-download policy, multiple-user configuration, error codes and tests.
The host secret file is deleted after successful onboarding; normal starts use the
saved authentication key. No credential is baked into the image. `.env`, `.secrets/`
and `.state/` are local, ignored files. The runner handles Docker group membership
with `sg docker` when necessary; it does not change host permissions.

Xvfb Qt are needed because AnkiConnect runs inside Anki Desktop.
Only the authenticated AnkiConnect port is published on **127.0.0.1**. Do not forward
it publicly. First onboarding downloads an existing AnkiWeb collection; later
full-sync conflicts stop automation and require explicit administrative recovery.

## Experiments

All commands must use the same `.state/` directory. Labels identify durable requests:
reuse a label after interruption; use a new label only for a genuinely new note.
Each note has a UUID tag, unique first field and Unicode. Never delete ambiguous
request state to make a retry work. The CLI serializes processes with a filesystem
lock; do not run another writer against this test collection.

### A — readiness, creation and readback

```sh
scripts/poc smoke A
scripts/poc driver create A  # reuses the original note, does not add another
```

Readiness checks the pinned Anki version, active profile, open collection/session,
deck, exact field order, and sync operation capabilities. Readback checks fields,
tags, note ID, generated cards and their deck, and exactly one matching request tag.

### B — sync and phone delivery

```sh
scripts/poc driver sync A
scripts/poc driver show A
```

Explicitly sync the test phone, find the card with the UUID shown by `show`, and
inspect both sides including `zażółć gęślą jaźń`, `Łódź`, `日本語`, and `🧠`.
Only after actually doing so, record the observation:

```sh
scripts/poc driver confirm-phone A --observed
```

States distinguish `created_locally`, `sync_requested`, `sync_confirmed`, and
`failed_unknown`; a phone observation has its own timestamp. Request latency is
separate from server completion and human observation time. The latter is when
delivery was observed, not the exact instant the phone first received the card.

### C — restart and removal/recreation with retained volume

```sh
scripts/poc restart
scripts/poc driver verify A
scripts/poc smoke C-restart
scripts/poc driver sync C-restart
# Explicit phone sync/check; then confirm-phone C-restart --observed.

scripts/poc recreate
scripts/poc driver verify A
scripts/poc driver verify C-restart
scripts/poc smoke C-recreate
scripts/poc driver sync C-recreate
# Repeat the phone observation for C-recreate.
```

`restart` stops/starts the same container; `recreate` removes only the stopped
container and creates another with the existing `anki-data` volume. Exit-code
verification refuses to continue after an unclean shutdown. The entire `/data`
directory persists: profiles, collection, media, add-ons/config and sync auth.
A volume lock prevents two Anki processes sharing it. **Do not use `down -v`.**

### D — external connectivity failure and recovery

```sh
scripts/poc smoke D
scripts/poc offline
scripts/poc driver sync D
# Expected: failed/unknown, never a false completion claim.
scripts/poc online
scripts/poc driver sync-status D
# Only after the original operation is explicitly failed/cancelled:
scripts/poc driver retry-sync D
scripts/poc driver verify D
# Explicit phone sync/check; then confirm-phone D --observed.
```

Disconnecting the selected project's internet network retains the separate internal control network.
The runner verifies API readiness after disconnecting. Restore connectivity even
if the experiment fails. Do not recreate during an active sync; observe or cancel
it through Anki first. `retry-sync` never calls `addNote`.

## Sync contract and recovery limits

This pinned upstream revision differs from the archived implementation reviewed
in the original notes. Legacy `sync` still acknowledges admission, whereas
`/api/v1` exposes `collection.sync` and `operations.get`. The driver uses legacy
actions for notes and v1 for sync. Source inspection found that the operation
resolves after the collection sync future succeeds; full sync changes the state
to `waitingForUser`, and errors produce a terminal failure. See the pinned
[source](https://git.sr.ht/~foosoft/anki-connect/tree/760ff48d8bbcfbc956f57c40475a8ab960c36a9c/item/plugin/gui.py)
and [API reference](https://git.sr.ht/~foosoft/anki-connect/tree/760ff48d8bbcfbc956f57c40475a8ab960c36a9c/item/API_V1.md).

The text-only POC sends `includeMedia: false`; it makes no media/audio-delivery
claim. `sync_confirmed` requires `state=succeeded` and `collectionComplete=true`.
It never means the phone has synced. Tests against a fake server validate the
driver's decisions, not upstream behavior or actual AnkiWeb delivery.

HTTP calls time out after 5 seconds; readiness retries for approximately 60 seconds
(plus the last bounded check), creation reconciliation for approximately 20 seconds,
and sync polling for approximately 60 seconds. Timeout does not cancel server work.
Run `sync-status LABEL` to resume polling the saved operation. Normal operation never
automatically chooses a full-sync direction for an established collection.

Operation handles are in-memory upstream and can disappear on restart or expire
after completion. If a sync response is lost before its handle is saved, or a
handle disappears, the CLI conservatively refuses a retry. Inspect saved evidence and
verify phone delivery; retain the evidence and state for manual diagnosis. There
is deliberately no automatic reset or arbitrary-sleep retry path. Likewise,
ambiguous creation with zero or multiple matches stops without another addNote.

There is no runtime presentation server. See [onboarding recovery](docs/onboarding.md#errors-and-recovery)
for credential renewal and exceptional collection conflicts.

## Development validation

```sh
cargo test --locked
cargo build --locked
python3 -m unittest discover -s tests -v
docker compose config --quiet
```

Integration tests run the real CLI against a local fault-injecting HTTP server:
ambiguous writes, duplicate tags, corrupted fields, wrong profiles, concurrent
commands, failed sync recovery, user prompts, lost sync acknowledgements, and
phone-observation separation. Network tests require permission to bind loopback.

After recording actual phone observations, `python3 scripts/export_evidence.py`
exports the synthetic request records to `docs/evidence.json`.
`python3 scripts/capture_operations.py` captures allowlisted operation metadata
before handles expire or Anki restarts; it omits upstream free-text errors.

No cloud host has been provisioned by these commands. A hosted experiment requires
a persistent Linux Docker host, private API access, and
repeating A–D there. Never put an active collection on a network filesystem.
