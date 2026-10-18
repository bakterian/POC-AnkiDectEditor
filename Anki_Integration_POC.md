# Anki integration POC

## Objective

Prove a personal, add-only Anki pipeline before building the Rust web utility. **Implement this POC only.** [Review and optional follow-up](Anki_Integration_POC_Notes.md) explain the assumptions.

Timebox: **8–10 working hours**. Full-project target: **6 December 2026**, at **10 hours/week**. These are planning constraints, not feasibility guarantees.

```text
Test driver → private AnkiConnect → Anki Desktop + Xvfb in Docker
                                           ↓
                                        AnkiWeb
                                           ↓
                                  Phone (explicit sync)
```

Use a Linux container and a small CLI driver, preferably Rust; shell is acceptable for diagnostics. One-time interactive setup is allowed. Routine creation, sync, and restart should need no GUI. Exclude browser UI, application login, AI, audio generation, production queues, multiple users, and editing/deleting existing notes.

## Setup

1. Record host architecture and Docker, Anki, and AnkiConnect versions; pin the image and application/add-on revisions. Verify their compatibility. Use a persistent Docker host/VM for the hosted experiment, not a disposable request-driven container.
2. Prefer a dedicated test account and collection. Before using an existing account, back it up and explicitly choose the initial sync direction. Never automatically resolve a destructive full-sync prompt.
3. Persist the complete Anki user-data directory: collection, media, profiles, add-ons/configuration, and authentication state. Select the intended profile explicitly. Keep one Anki process per volume; stop it gracefully before recreation. Exclude data and secrets from source control.
4. Keep API and setup GUI private. A host driver can use a port published to `127.0.0.1`; separate containers should use a private bridge and service name. AnkiConnect must listen on the reachable container interface for either route, not only container loopback. Configure its API key and document/test exposure. See [Docker networking](https://docs.docker.com/engine/network/port-publishing/).
5. Use temporary protected GUI access for account login, initial sync, deck/note-type setup, and dialogs; disable it afterward. Later credential expiry or prompts may still require maintenance.
6. Readiness must confirm an open collection and the expected profile/deck/fields, not merely a responding `version` endpoint. Bound all waits and sanitize logs.

## Driver behavior

- Check the installed API contract. Candidate actions: `version`, `deckNames`, `modelNames`, `modelFieldNames`, `addNote`, `findNotes`, `notesInfo`, and `sync`.
- Serialize operations. Create a note with a unique request tag, unique first-field text, and Unicode such as `zażółć gęślą jaźń`. Persist the request identifier before sending; reuse it on retries. Save the returned note ID and read back fields, tags, and generated cards.
- Check transport and API errors. After an ambiguous creation response, wait for the original operation to settle and search the request tag. Reuse a matching note; stop on uncertainty or multiple matches. Do not blindly repeat `addNote`.
- Separate **created locally**, **sync requested**, **sync confirmed**, and **failed/unknown**. A successful `sync` response may only acknowledge starting synchronization. Verify the pinned version's completion behavior; do not equate HTTP success or an arbitrary sleep with completion. [Source qualification](Anki_Integration_POC_Notes.md#corrections-to-the-original-idea).

## Required experiments

| Test | Procedure | Pass evidence |
| --- | --- | --- |
| A. Startup and creation | Start the configured container, wait for collection readiness, create and read back one unique note. | No bootstrap interaction; exactly one matching note with expected fields, tags, and cards. |
| B. End-to-end sync | Request sync; capture available completion/error evidence and hidden prompts. Explicitly sync the phone and inspect the new card. | Correct text and Unicode on the phone. Record request latency separately from confirmed delivery. |
| C. Persistence | Test both restart and removal/recreation with the volume retained. After each, find earlier notes, create a new one, and repeat B. | Add-on, collection, and authentication survive; another complete cycle works without GUI/login. |
| D. Failure and recovery | Create a note; block external connectivity while retaining driver access. Request sync, observe the failure/unknown state, restore connectivity, let the prior attempt settle, and retry sync only. Repeat phone verification. | No false completion claim; recovery delivers exactly one matching note. A successful API acknowledgement during the outage is not evidence of successful sync. |

## Deliverables and decision

Deliver container configuration, driver, placeholder-only configuration, setup/test commands, an automated readiness/create/readback check, and a short results report. Record **pass/fail/not tested**, sanitized evidence, timing, and limitations for each experiment. Phone observations remain pending until a person actually verifies them. State whether the intended cloud host was tested.

Conclude **proceed**, **proceed with constraints**, **change approach**, or **inconclusive**. Unobservable sync completion is a constraint to resolve before promising automatic status/retries. Local success does not prove cloud operation; persistent GUI problems may favor AnkiConnect on an existing desktop. Proceed to `/10x-shape` when the evidence supports the chosen route.
