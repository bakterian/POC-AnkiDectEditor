# POC results

This is the original 2026-10-17 experiment record. The subsequent removal of VNC
and unattended onboarding validation are documented in [onboarding results](onboarding-results.md).

Date: 2026-10-17. Decision: **proceed with constraints**.
This report distinguishes implementation tests from actual AnkiWeb/phone evidence.

All required local experiments passed, including human verification on the test
phone. The evidence supports this personal, add-only Docker route for shaping the
product. It does not validate a hosted service, audio, bulk editing or multiple users.

## Environment

- Accessible execution environment: Linux x86-64, Debian 13.
- Docker client/server: 29.9.1, linux/amd64. Compose: 5.6.0.
- Anki: 26.09.3 (aqt/anki packages 26.9.3); Qt 6.8.1.
- AnkiConnect: `760ff48d8bbcfbc956f57c40475a8ab960c36a9c`, retrieved from upstream
  SourceHut, built into the image; legacy API 6 and v1 operation API available.
- Dedicated Docker volume and profile/deck `POC`. Host Anki collection untouched.
- AnkiWeb account is user-provided; credentials are omitted from this report.
- Intended cloud host: **not tested**.
- Built image ID:
  `sha256:fc36ff9033c20aa65858dbd90b6d8e92d02fbee9010b4cabbc3e2d89104807c8`.
  Full package and Docker inventory: [environment.txt](environment.txt).

## Completed engineering checks

| Check | Status | Evidence |
|---|---|---|
| Rust compilation/unit test | PASS | Rust 1.90.0; Unicode/field/tag/card validation test passed |
| Rust lint | PASS | `cargo clippy --offline --all-targets -- -D warnings` |
| Fault-injection integration tests | PASS | Ten real-CLI tests against a stateful local HTTP fixture |
| Compose schema | PASS | `docker compose config --quiet` |
| Container build | PASS | Pinned base images, Anki/Qt and add-on source downloaded and built |
| Anki startup and add-on compatibility | PASS | Real container reports Anki 26.09.3; API version=6; profile=POC |
| Collection readiness | PASS | Live driver verified collection/session, deck, fields, version and sync capabilities |
| Private bindings | PASS (configuration/live inspection) | Both published ports bind 127.0.0.1; no public bind |
| API authentication / GUI-off check | PASS | Both API endpoints reject missing/wrong keys; VNC and noVNC listeners disabled |
| Maintenance display toggle | PASS | Enabled and disabled without restarting Anki; current operation handles remained queryable |
| One process per volume | PASS | A second instance failed on the exclusive volume lock before changing the profile/add-on |

The startup attempt initially failed because Qt required `libatomic.so.1`.
Adding `libatomic1` (and the GBM runtime dependency) fixed startup. This was a
container dependency issue, not evidence of a working sync pipeline.

## Required experiments

| Experiment | Status | Evidence / remaining work |
|---|---|---|
| A — unattended startup, creation, exact readback | PASS | Created A, checked fields/tags/cards/deck and one matching note; repeated create reused the same ID; later starts needed no GUI |
| B — AnkiWeb sync and phone | PASS | Server operation succeeded; user explicitly synced AnkiDroid and confirmed both sides including Unicode |
| C — restart and removal/recreation | PASS | Graceful stop/start and full container removal/recreation retained old notes and authentication; new notes synced in both cases; user confirmed each exactly once on the phone |
| D — network outage and recovery | PASS | Removed only the internet network; control/readiness remained reachable; accepted sync ended in ioError, not success; restored network and retried sync only; same single note delivered and user-confirmed |

The user confirmed A separately, then confirmed C-restart, C-recreate and D all
present exactly once with correct text/Unicode on both sides. Their observations
are recorded in [evidence.json](evidence.json). These timestamps are when the
confirmation was recorded, not instrumented phone arrival times.

| Request | Note ID | Sync request latency | Client-observed server completion | Phone |
|---|---|---:|---:|---|
| A | 1792243424144 | 46 ms | 648 ms | Confirmed |
| C-restart | 1792243474068 | 47 ms | 649 ms | Confirmed |
| C-recreate | 1792243520744 | 47 ms | 649 ms | Confirmed |
| D, outage | 1792243553267 | 46 ms | Failed after 30.320 s upstream | Not claimed |
| D, recovery | same ID | 47 ms | 648 ms | Confirmed |

Completion durations include the driver's polling interval; they are not precise
backend timings or performance guarantees. [operations.json](operations.json)
contains allowlisted upstream timestamps and the outage error type. Handles for A
and C-restart were unavailable after process restarts, as the API contract predicts;
their successful observations had already been persisted locally.

Setup encountered one expected configuration change: initial Download replaced
the empty pre-created POC deck, so it was created again afterward. All subsequent
creation/sync/restart/recreation work ran without login or GUI intervention.

Final state: Anki running and healthy; internet network restored; both ports bound
to localhost; setup GUI listeners off; four synthetic test notes retained in the
POC deck. The host's separately installed Anki was not changed.

## Contract qualification and limits

The pinned current upstream supports `collection.sync` → operation handle →
`operations.get`; its source resolves collection completion only after the native
sync future succeeds, reports failures, and exposes full-sync prompts as
`waitingForUser`. The driver uses that path with media disabled for this text-only
POC. Legacy `sync` remains an admission acknowledgement.

This is stronger observability than the archived source described in the brief's
notes. Live success, live outage failure, recovery and independent phone inspection
were verified here. The `waitingForUser` branch was checked in upstream source and
fault-injection tests; a later forced full-sync prompt was not deliberately induced.

If the sync handle is lost or expires, the driver stops rather than guessing that
work settled. Existing operation handles do not survive Anki process restart.
Unknown creation never automatically issues another addNote. These conservative
stops can require manual diagnosis. Setup/maintenance may also be required for
credential expiry and full-sync prompts.

Constraints for the next phase: keep the service private and single-user, preserve
the volume and request journal, retain a manual maintenance path, and repeat these
experiments on the intended persistent cloud host before making hosted-operation
claims. No additional product functionality has been implemented. The evidence is
ready to take into `/10x-shape`.
