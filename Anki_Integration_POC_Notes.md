# Anki POC review and optional follow-up

Reviewed **17 October 2026**. The [POC brief](Anki_Integration_POC.md) defines required work. This review checks documentation/source; it does not demonstrate a running container.

## Assessment

**This is a more feasible first project than the earlier cloud deck editor**, chiefly because it is personal and add-only. Anki Desktop owns the collection and synchronization; there is no second editable replica in Supabase or custom headless sync orchestration. It does not validate bulk editing or a multi-user service.

AnkiConnect is a maintainer-suggested integration route. That supports this direction, but is not an endorsement of a particular Docker deployment or future hosted service. [Maintainer response](https://forums.ankiweb.net/t/authentication-with-ankiweb-for-add-on-deploy-from-github/40999).

The remaining risks are desktop/add-on compatibility, hidden dialogs, persistent storage, and observing sync completion. Xvfb supplies a display; it does not turn Anki into a supported unattended server. Budget for an always-running host and occasional maintenance. Check the selected image against [Anki's Linux requirements](https://docs.ankiweb.net/manual/platform/linux/installing).

## Corrections to the original idea

Treat these as qualifications to [the original proposal](Anki_Card_Adding_Utility_Idea.md):

- **Sync acknowledgement is not completion.** The archived upstream `sync` implementation calls `onSync()` without returning a completion result. Inspect/test the selected version; phone delivery is independent evidence. [Implementation](https://github.com/FooSoft/anki-connect/blob/master/plugin/__init__.py).
- **API authentication exists.** AnkiConnect supports a configurable `apiKey`; the archived default is unset. Keep the API private even with a key. [Configuration](https://github.com/FooSoft/anki-connect/blob/master/plugin/config.json).
- **Networking is topology-dependent.** Another container's `localhost` is not Anki's. The protocol is an HTTP JSON action API, not standard JSON-RPC 2.0.
- **No instant phone delivery or inevitable review lock.** Devices must sync; ordinary changes generally merge. Initial/structural changes can require destructive one-way sync. [Sync manual](https://docs.ankiweb.net/manual/syncing).
- **Base64 is not the only media route.** The inspected API also accepts paths/URLs; a path must be accessible inside the Anki container. [Media API implementation](https://github.com/FooSoft/anki-connect/blob/master/plugin/__init__.py).

The upstream [GitHub repository](https://github.com/FooSoft/anki-connect) moved to SourceHut. That site was inaccessible to the review tool; archived code establishes the qualifications above, not current-version compatibility. Verify the exact installed revision. Preserve the complete user-data directory and avoid live network-mounted collections. [Anki storage guidance](https://docs.ankiweb.net/manual/files).

## Optional checks after the core POC

- **Phone activity:** sync both clients, review/edit an existing test note on the phone, add a different note through the driver, then sync both. Verify both changes survive; stop on unexpected full-sync prompts.
- **Audio transport:** store a short usable fixture under a unique filename, reference it as `[sound:filename]`, and verify phone playback after sync. Recreate the container and verify the actual server media file remains, not just the phone's cached copy.
- **Enrichment:** audio generation and etymology remain separate. GitHub currently lists a Rust Copilot SDK using its CLI runtime; test authentication, usage limits, deployment, and answer quality. Disable unnecessary agent tools for a text-only request. Require review of generated etymology. [Copilot SDK](https://github.com/github/copilot-sdk).

## Planning and course fit

At 10 hours/week, 17 October to 6 December provides roughly **70 hours before deductions**, not a delivery estimate. Preserve time for tests, documentation, and deployment. Keep browser authentication, duplicate handling, validation, formatting, and sync status in shaping; audio/AI remain optional.

The course requires appropriate access control, meaningful CRUD, domain logic, context documents, and a user-perspective test. An add-only integration POC is not the whole submission. Resolve management scope during shaping. Deployment wording varies; ask mentors about a concrete desktop fallback if needed. Submit the chosen badge scope once. See [certification](.agents/skills/10x-idea-check/references/10xdevs-4-certification.md) and [deadlines](.agents/skills/10x-idea-check/references/10xdevs-4-dates.md).

Next: take the POC evidence into `/10x-shape`; define the smallest useful product around the integration that actually worked.
