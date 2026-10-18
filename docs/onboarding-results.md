# Unattended onboarding validation

Date: 2026-10-18. Outcome: **backend login without GUI demonstrated live**.

This extends the [original POC results](results.md); the earlier A–D evidence
remains a historical record. The new tests used the same authorized AnkiWeb test
account with a **fresh, separate** Compose project and volume. They do not establish
production multi-user readiness or phone delivery of the new notes.

## Changes delivered

- One-shot `onboarding.py` authenticates through the pinned Anki backend, saves its
  sync key, initializes a fresh collection by Download, and ensures the POC deck.
- Normal startup uses saved authentication, with no mounted AnkiWeb password.
- The host credential source is deleted after successful onboarding; the runtime
  copy is in a tmpfs and is deleted on bootstrap exit.
- Account/profile binding prevents switching a populated volume to another user.
- `POC_ENV_FILE` selects independent Compose projects, volumes, secret paths,
  request journals, API ports and networks. No production web connection form or
  tenant authorization/scheduling service is included.
- Removed x11vnc, noVNC, websockify, Openbox, display-password configuration,
  port 6080, `gui_mode.py`, and `setup`/`headless` commands. Qt and Xvfb remain for
  Anki Desktop/AnkiConnect; the one-shot bootstrap itself starts neither.

Final image: `sha256:2cdfc1cc186cf5c1304968b3124831131db5586de5ffe51a773a2e6f0aab1c8c`.
Anki 26.09.3, Qt 6.8.1, pinned AnkiConnect revision unchanged from the original POC.
Docker reports image size 1,439,029,788 bytes; dependency removal does not eliminate
the much larger Anki/Qt runtime.

## Executed checks

| Check | Result | Evidence |
|---|---|---|
| Fresh-volume backend login | PASS | `onboard` returned `ready`, with no desktop/VNC started |
| Initial AnkiWeb collection download | PASS | Original A UUID found in the new collection with the original note ID `1792243424144` |
| Password removal | PASS | Host source removed; normal service had neither credential mount nor runtime password copy |
| New note and collection sync | PASS | `E-onboarding`, note `1792333211224`, operation observed succeeded |
| Restart without password | PASS | Readiness and original note verification passed; `E-restart` synced successfully |
| Container recreation without password | PASS | Same volume/authentication retained; `E-recreate` synced successfully |
| Different-account rejection | PASS | Fictitious account on the already-bound test volume returned `account_binding_mismatch` before backend login |
| Same-account reauthentication | PASS | Reprovisioning returned `ready`; existing `E-recreate` note remained unchanged and unique |
| Removed presentation layer | PASS | No x11vnc/websockify/Openbox executable or noVNC assets; no 5900/6080 listener |
| API exposure | PASS | Only loopback API port published; both protocols rejected missing/wrong API keys |
| Legacy profile migration | PASS | Original POC recreated on new image without login; original A verified; service healthy |
| Python policy + real Rust binary fault tests | PASS | 20 tests, including 10 provisioning policy tests; final image's binary used for HTTP tests |
| Rust unit test | PASS | 1 readback-validation test in pinned build image |
| Rust formatting and Clippy | PASS | `cargo fmt --check`; `cargo clippy --locked --all-targets -- -D warnings` |
| Compose / Python / diagrams | PASS | Compose config valid; Python compiled; updated Mermaid diagrams rendered and inspected |

The initial local test configuration used incorrect driver UID/GID values, causing
secret-file permission failures. Correcting them to the host user's IDs resolved
this without changing secret permissions. The guide explicitly calls out these IDs.
The slim Rust build image lacks rustfmt/Clippy; those components were installed in
a disposable validation container, not the Anki runtime image.

Sanitized new-note records: [onboarding-evidence.json](onboarding-evidence.json).
All three have server sync confirmation and **no phone observation**. They are
synthetic notes retained in the test account; no pre-existing notes were deleted.

## Final state and remaining limits

The original `anki-poc-anki-1` service is healthy on `127.0.0.1:8765`, using the
original `anki-poc_anki-data` volume. The isolated `anki-onboarding-test` service
is stopped with exit code 0, and its volume/journal are retained for inspection.
Its local selector is `.state/onboarding.env`. Neither environment is intended to
be a concurrently running writer for this same test account.

- Only one real AnkiWeb account was available. Separate-project provisioning and
  mismatch guards are implemented; simultaneous distinct real-user accounts and
  resource scaling have not been live-tested.
- First provisioning assumes an existing remote collection and the English
  `Basic`/`Front`/`Back` contract. Full upload to initialize an empty remote account
  is not automatic. Media/audio is outside this text-only POC.
- Authentication failure, initial-download interruption and empty-server policy
  were exercised by fake-backend tests, not induced against the real account.
- Later full-sync conflicts in an established collection still require explicit
  administrative recovery. This image no longer offers an interactive recovery
  browser; the [onboarding guide](onboarding.md#errors-and-recovery) describes the boundary.
- No cloud deployment, production credential vault, web connection form, or new
  phone inspection is claimed. Internal Anki APIs remain version-pinned.
