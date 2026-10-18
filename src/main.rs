//! Small, synchronous CLI for an add-only Anki experiment.
//!
//! Start reading at `run()`, which chooses a command. `Api` sends HTTP requests,
//! `Record` remembers work between CLI runs, and `create`/`sync` implement the
//! workflows. We keep them in one file because this is a deliberately small POC.
//!
//! Rust notes: `Result<T>` is either `Ok(T)` or an error; `?` returns early on an
//! error. `ensure!` checks a condition and returns an error when it is false.
//! `&T` borrows a value without taking ownership; `&mut T` also allows changes.
use anyhow::{bail, ensure, Context, Result};
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    env,
    fs::{self, File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

/// Wall-clock milliseconds are useful in saved evidence shared across processes.
/// Timeouts below use `Instant` instead, so clock adjustments cannot extend them.
fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64
}
/// Read configuration from the environment, falling back to a local POC default.
fn setting(key: &str, default: &str) -> String {
    env::var(key).unwrap_or_else(|_| default.into())
}

/// Reuse one HTTP client and the expected collection settings for a CLI command.
/// The API key authenticates our local AnkiConnect requests, not AnkiWeb login.
struct Api {
    url: String,
    key: String,
    agent: ureq::Agent,
    profile: String,
    deck: String,
    model: String,
}
impl Api {
    /// Construct the client without making a network request.
    fn new() -> Result<Self> {
        let url = setting("ANKI_URL", "http://127.0.0.1:8765");
        // The POC intentionally supports only loopback or its private Compose service.
        ensure!(
            ["http://127.0.0.1:", "http://localhost:", "http://anki:"]
                .iter()
                .any(|prefix| url
                    .strip_prefix(prefix)
                    .is_some_and(|p| p.parse::<u16>().is_ok())),
            "ANKI_URL must be loopback or the private anki service, with a port"
        );
        // Read the secret from a file so it is not supplied as a command-line
        // argument, where other processes or shell history could reveal it.
        let key = fs::read_to_string(setting("ANKI_API_KEY_FILE", ".secrets/api-key"))
            .context("API key file unavailable; run scripts/init.py")?
            .trim()
            .to_string();
        ensure!(
            key.len() >= 32,
            "API key must contain at least 32 characters"
        );
        Ok(Self {
            url,
            key,
            // Bound each HTTP call. Disable redirects so a server cannot forward
            // a request carrying our API key to a different destination.
            agent: ureq::AgentBuilder::new()
                .timeout(Duration::from_secs(5))
                .redirects(0)
                .build(),
            profile: setting("ANKI_PROFILE", "POC"),
            deck: setting("ANKI_DECK", "POC"),
            model: setting("ANKI_MODEL", "Basic"),
        })
    }
    /// Send a legacy API-v6 action, used for creating/searching/reading notes.
    /// `Value` is serde_json's general JSON type; `json!` constructs one for us.
    fn call(&self, action: &str, params: Value) -> Result<Value> {
        let response = self
            .agent
            .post(&self.url)
            .send_json(json!({"action":action,
            "version":6,"key":self.key,"params":params}))
            .map_err(|_| {
                anyhow::anyhow!("{action}: HTTP/transport failure; outcome may be unknown")
            })?;
        // HTTP success alone is insufficient: this protocol can return status
        // 200 with an application-level error inside its JSON envelope.
        let reply: Value = response
            .into_json()
            .map_err(|_| anyhow::anyhow!("{action}: invalid JSON reply"))?;
        ensure!(
            reply.get("error").is_some() && reply.get("result").is_some(),
            "{action}: invalid envelope"
        );
        // Do not print the upstream error text, which might contain private data.
        ensure!(
            reply["error"].is_null(),
            "{action}: API rejected request (details omitted)"
        );
        Ok(reply["result"].clone())
    }
    /// The newer endpoint is JSON-RPC 2.0, unlike the legacy action endpoint.
    /// It uses a Bearer header and provides observable sync-operation handles.
    fn rpc(&self, method: &str, params: Value) -> Result<Value> {
        let response = self
            .agent
            .post(&format!("{}/api/v1", self.url))
            .set("Authorization", &format!("Bearer {}", self.key))
            // Calls are synchronous, so there is only one outstanding request
            // here. This id matches a reply; it does NOT prevent duplicate work.
            .send_json(json!({"jsonrpc":"2.0","id":1,"method":method,"params":params}))
            .map_err(|_| {
                anyhow::anyhow!("{method}: HTTP/transport failure; outcome may be unknown")
            })?;
        let reply: Value = response
            .into_json()
            .map_err(|_| anyhow::anyhow!("{method}: invalid JSON reply"))?;
        ensure!(
            reply["jsonrpc"] == "2.0" && reply["id"] == 1,
            "{method}: invalid envelope"
        );
        ensure!(
            reply.get("error").is_none(),
            "{method}: API rejected request (details omitted)"
        );
        reply.get("result").cloned().context("RPC result missing")
    }
    /// Check that it is safe to work with the intended collection, not just that
    /// an HTTP port answers. Return the current collection's session identifier.
    fn ready_once(&self) -> Result<String> {
        ensure!(
            self.call("version", json!({}))? == 6,
            "Unexpected legacy API version"
        );
        ensure!(
            self.call("getActiveProfile", json!({}))? == self.profile,
            "Wrong active profile"
        );
        let col = self.rpc("collection.get", json!({}))?;
        ensure!(
            col["profile"] == self.profile,
            "Collection profile mismatch"
        );
        let decks = self.call("deckNames", json!({}))?;
        ensure!(
            decks
                .as_array()
                .is_some_and(|v| v.contains(&json!(self.deck))),
            "Expected deck missing; complete GUI setup"
        );
        let models = self.call("modelNames", json!({}))?;
        ensure!(
            models
                .as_array()
                .is_some_and(|v| v.contains(&json!(self.model))),
            "Expected note type missing"
        );
        ensure!(
            self.call("modelFieldNames", json!({"modelName":self.model}))?
                == json!(["Front", "Back"]),
            "Expected exactly Front and Back fields, in that order"
        );
        // Pinning versions would be ineffective if we silently accepted a
        // different running application or a missing sync-status capability.
        let description = self.rpc("api.describe", json!({}))?;
        ensure!(
            description["ankiVersion"] == "26.09.3" || description["ankiVersion"] == "26.9.3",
            "Anki version differs from pinned 26.9.3"
        );
        for method in ["collection.sync", "operations.get"] {
            ensure!(
                description["methods"].as_array().is_some_and(|list| list
                    .iter()
                    .any(|item| item["name"] == method && item["available"] == true)),
                "Required method unavailable: {method}"
            );
        }
        Ok(col["session"]
            .as_str()
            .context("Collection session missing")?
            .into())
    }
    /// Retry only read-only readiness checks during startup. A complete check
    /// contains several bounded HTTP calls, so the last check can overrun 60 s.
    fn ready(&self, once: bool) -> Result<String> {
        let start = Instant::now();
        loop {
            match self.ready_once() {
                Ok(session) => return Ok(session),
                Err(error) if once || start.elapsed() >= Duration::from_secs(60) => {
                    return Err(error)
                }
                Err(_) => thread::sleep(Duration::from_secs(1)),
            }
        }
    }
}

/// One sync submission. Keep earlier attempts so a recovered outage remains
/// visible in the evidence. `Option<T>` represents a value we may not know yet;
/// `None` becomes JSON null, rather than a misleading zero or empty identifier.
#[derive(Serialize, Deserialize)]
struct SyncAttempt {
    requested_at_ms: u64,
    request_latency_ms: Option<u64>,
    operation_id: Option<String>,
    status: String,
    confirmed_at_ms: Option<u64>,
}
/// Durable journal for one logical note request, stored as `.state/<label>.json`.
/// Serde derives generate the code that converts this struct to/from JSON.
/// Anki owns the real collection; this record only tracks our request and evidence.
#[derive(Serialize, Deserialize)]
struct Record {
    label: String,
    request_id: String,
    profile: String,
    deck: String,
    model: String,
    front: String,
    back: String,
    created_at_ms: u64,
    creation: String,
    note_id: Option<u64>,
    readback_at_ms: Option<u64>,
    sync: Vec<SyncAttempt>,
    phone_observed_at_ms: Option<u64>,
}
impl Record {
    /// Generate the UUID exactly once. Repeated commands load the saved record
    /// instead; a fresh UUID on every retry would defeat duplicate prevention.
    fn new(label: &str, api: &Api) -> Self {
        let id = uuid::Uuid::new_v4().simple().to_string();
        Self {
            label: label.into(),
            request_id: id.clone(),
            profile: api.profile.clone(),
            deck: api.deck.clone(),
            model: api.model.clone(),
            front: format!("POC {label} {id} — zażółć gęślą jaźń"),
            back: "Anki integration POC — Unicode: Łódź, 日本語, 🧠".into(),
            created_at_ms: now(),
            creation: "prepared".into(),
            note_id: None,
            readback_at_ms: None,
            sync: vec![],
            phone_observed_at_ms: None,
        }
    }
    /// An exact, searchable marker that connects an Anki note to its journal.
    fn tag(&self) -> String {
        format!("poc_request_{}", self.request_id)
    }
    /// Refuse to reuse old request state against a different profile/deck/model.
    fn check_config(&self, api: &Api) -> Result<()> {
        ensure!(
            self.profile == api.profile && self.deck == api.deck && self.model == api.model,
            "Configuration differs from saved request; restore original configuration"
        );
        Ok(())
    }
}
/// Replace the journal atomically: readers see either the old complete file or
/// the new complete file, not half-written JSON. The CLI lock prevents two
/// writers from using the same temporary path at once.
fn save(path: &Path, record: &Record) -> Result<()> {
    let tmp = path.with_extension("json.tmp");
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(&tmp)?;
    file.write_all(&serde_json::to_vec_pretty(record)?)?;
    // First flush file contents, then rename within the same directory/filesystem.
    // Finally flush the directory so its renamed entry is persisted too.
    file.sync_all()?;
    fs::rename(tmp, path)?;
    File::open(path.parent().unwrap())?.sync_all()?;
    Ok(())
}
/// Loading a record restores both the UUID and the last known workflow state.
fn load(path: &Path) -> Result<Record> {
    serde_json::from_slice(&fs::read(path).context("Saved request not found")?)
        .context("Invalid saved request")
}
/// Return every note with this request tag. Callers must handle zero, one, and
/// multiple matches differently; choosing the first of several would hide a bug.
fn matches(api: &Api, record: &Record) -> Result<Vec<u64>> {
    serde_json::from_value(api.call(
        "findNotes",
        json!({"query":format!("tag:{}", record.tag())}),
    )?)
    .context("Invalid note search response")
}
/// Pure validation, with no network or disk access: useful for a fast unit test.
/// A note stores fields; Anki generates one or more reviewable cards from it.
fn validate_note(note: &Value, record: &Record, id: u64) -> Result<Vec<u64>> {
    ensure!(
        note["noteId"] == id && note["modelName"] == record.model,
        "Readback identity mismatch"
    );
    ensure!(
        note["fields"]["Front"]["value"] == record.front
            && note["fields"]["Back"]["value"] == record.back,
        "Readback field mismatch"
    );
    let tags = note["tags"].as_array().context("Readback tags missing")?;
    ensure!(
        tags.contains(&json!(record.tag())) && tags.contains(&json!("anki_poc")),
        "Readback tags mismatch"
    );
    let cards: Vec<u64> = serde_json::from_value(note["cards"].clone())?;
    ensure!(!cards.is_empty(), "No generated cards");
    Ok(cards)
}
/// Read the actual Anki data back before claiming local success. `&mut Record`
/// lets us update the caller's journal only after the checks have passed.
fn verify(api: &Api, path: &Path, record: &mut Record, id: u64) -> Result<()> {
    ensure!(
        record.note_id.is_none_or(|saved| saved == id),
        "Saved note ID differs from matching note; stop and investigate"
    );
    let info = api.call("notesInfo", json!({"notes":[id]}))?;
    ensure!(
        info.as_array().is_some_and(|v| v.len() == 1),
        "Expected one note in readback"
    );
    let cards = validate_note(&info[0], record, id)?;
    // The note's fields alone do not prove that a usable card was generated in
    // the correct deck. Inspect those cards as a separate check.
    let info = api.call("cardsInfo", json!({"cards":cards}))?;
    ensure!(
        info.as_array().is_some_and(|list| list.len() == cards.len()
            && list.iter().all(|c| c["deckName"] == record.deck
                && c["note"] == id
                && c["cardId"].as_u64().is_some_and(|cid| cards.contains(&cid)))),
        "Generated card/deck mismatch"
    );
    ensure!(
        matches(api, record)? == vec![id],
        "Expected exactly one matching note"
    );
    record.note_id = Some(id);
    record.creation = "created_locally".into();
    record.readback_at_ms = Some(now());
    save(path, record)
}
/// Create at most once from this journal, or verify a note that already exists.
/// This is conservative retry handling, not a distributed exactly-once guarantee.
fn create(api: &Api, path: &Path, record: &mut Record) -> Result<()> {
    record.check_config(api)?;
    api.ready(false)?;
    let ids = matches(api, record)?;
    ensure!(
        ids.len() <= 1,
        "Multiple matches; manual investigation required"
    );
    // A previous command may have created the note and then lost its response.
    if let Some(id) = ids.first() {
        return verify(api, path, record, *id);
    }
    ensure!(
        record.creation == "prepared",
        "Previous creation may have executed; use reconcile. Never resend addNote blindly"
    );
    // Persist intent BEFORE the network call, including the crash-before-send window.
    // Even if we crash before sending anything, we cannot safely prove that on
    // the next run. Prefer a manual stop over the possibility of a duplicate.
    record.creation = "failed_unknown".into();
    save(path, record)?;
    let result = api.call(
        "addNote",
        json!({"note":{"deckName":record.deck,
        "modelName":record.model,"fields":{"Front":record.front,"Back":record.back},
        "options":{"allowDuplicate":false},"tags":["anki_poc",record.tag()]}}),
    );
    if let Ok(value) = result {
        if let Some(id) = value.as_u64() {
            record.note_id = Some(id);
            save(path, record)?;
            return verify(api, path, record, id);
        }
    }
    // Transport failure, API rejection, or an unexpected result all take the
    // cautious path: search for the note instead of submitting addNote again.
    reconcile(api, path, record)
}
/// Resolve an ambiguous creation using read-only searches. A timeout is evidence
/// that we do not know the outcome; it is not permission to create another note.
fn reconcile(api: &Api, path: &Path, record: &mut Record) -> Result<()> {
    record.check_config(api)?;
    let deadline = Instant::now() + Duration::from_secs(20);
    while Instant::now() < deadline {
        // Check readiness and then search through the server's serialized read
        // queue. This lets earlier work settle; we do not guess from a sleep.
        if api.ready_once().is_ok() {
            let ids = matches(api, record)?;
            ensure!(ids.len() <= 1, "Multiple matches; stop and investigate");
            if let Some(id) = ids.first() {
                return verify(api, path, record, *id);
            }
        }
        thread::sleep(Duration::from_millis(500));
    }
    bail!("No verified matching note after bounded reconciliation; creation remains unknown, not resent")
}
/// Observe the SAME sync operation until success, failure, user input, or timeout.
/// Polling never starts a new sync and never adds a note.
fn poll_sync(api: &Api, path: &Path, record: &mut Record) -> Result<()> {
    let attempt = record.sync.last_mut().context("No sync attempt exists")?;
    // Clone the handle into an owned String so it remains usable while we mutate
    // other fields in the record. Rust prevents overlapping conflicting borrows.
    let id = attempt
        .operation_id
        .clone()
        .context("Sync handle was not received; do not retry until manually settled")?;
    let deadline = Instant::now() + Duration::from_secs(60);
    loop {
        let operation = match api.rpc("operations.get", json!({"operationId":id})) {
            Ok(value) => value,
            Err(error) => {
                record.sync.last_mut().unwrap().status = "failed_unknown".into();
                save(path, record)?;
                return Err(
                    error.context("Cannot observe sync; handle retained, no automatic retry")
                );
            }
        };
        ensure!(
            operation["operationId"] == id && operation["method"] == "collection.sync",
            "Operation identity mismatch"
        );
        let state = operation["state"]
            .as_str()
            .context("Operation state missing")?;
        let attempt = record.sync.last_mut().unwrap();
        match state {
            "succeeded" => {
                // This proves collection synchronization, not phone delivery.
                // The phone must still explicitly sync and be checked by a person.
                ensure!(
                    operation["result"]["collectionComplete"] == true,
                    "No collection completion evidence"
                );
                attempt.status = "sync_confirmed".into();
                attempt.confirmed_at_ms = Some(now());
                save(path, record)?;
                return Ok(());
            }
            "failed" | "cancelled" => {
                attempt.status = state.into();
                save(path, record)?;
                bail!("Sync operation {state}; restore connectivity/auth, then use retry-sync");
            }
            "waitingForUser" => {
                // A full sync may replace one side's collection. Leave the choice
                // to the user through the temporary setup display.
                attempt.status = "waiting_for_user".into();
                save(path, record)?;
                bail!(
                    "Sync requires a collection conflict decision; stop automation and see docs/onboarding.md"
                );
            }
            "queued" | "running" => {
                attempt.status = "sync_requested".into();
                save(path, record)?;
            }
            _ => bail!("Unknown operation state; stop and investigate"),
        }
        if Instant::now() >= deadline {
            // Client timeout does not cancel work already accepted by Anki.
            record.sync.last_mut().unwrap().status = "failed_unknown".into();
            save(path, record)?;
            bail!(
                "Sync observation timed out; use sync-status to resume polling the same operation"
            );
        }
        thread::sleep(Duration::from_millis(500));
    }
}
/// Start a first sync, resume observation, or explicitly retry a terminal failure.
/// `sync LABEL` is safe to repeat: it does not resubmit an already confirmed sync.
fn sync(api: &Api, path: &Path, record: &mut Record, retry: bool) -> Result<()> {
    record.check_config(api)?;
    ensure!(
        record.creation == "created_locally",
        "Verify local creation before syncing"
    );
    if let Some(last) = record.sync.last() {
        if !retry {
            if last.status == "sync_confirmed" {
                return Ok(());
            }
            return poll_sync(api, path, record);
        }
        ensure!(
            last.status == "failed" || last.status == "cancelled",
            "Only a terminal failed/cancelled operation may be retried; observe the original first"
        );
    } else {
        ensure!(!retry, "No prior sync to retry");
    }
    let session = api.ready(false)?;
    let ids = matches(api, record)?;
    ensure!(
        ids.len() == 1 && Some(ids[0]) == record.note_id,
        "Note identity changed; reconcile first"
    );
    verify(api, path, record, ids[0])?;
    // As with creation, persist the attempt BEFORE making the request. If the
    // response disappears before we save its handle, the journal stays unknown.
    record.sync.push(SyncAttempt {
        requested_at_ms: now(),
        request_latency_ms: None,
        operation_id: None,
        status: "failed_unknown".into(),
        confirmed_at_ms: None,
    });
    // A previous phone observation cannot prove delivery of a new sync attempt.
    record.phone_observed_at_ms = None;
    save(path, record)?;
    let start = Instant::now();
    let handle = api.rpc(
        "collection.sync",
        // The collection session guards against a profile change between the
        // readiness check and admission. This POC deliberately syncs text only.
        json!({"includeMedia":false,"session":session}),
    )?;
    ensure!(handle["method"] == "collection.sync", "Wrong sync handle");
    let id = handle["operationId"]
        .as_str()
        .context("Sync handle missing")?
        .to_string();
    let attempt = record.sync.last_mut().unwrap();
    attempt.operation_id = Some(id);
    attempt.status = "sync_requested".into();
    attempt.request_latency_ms = Some(start.elapsed().as_millis() as u64);
    save(path, record)?;
    poll_sync(api, path, record)
}
/// Print synthetic card data and workflow evidence, never configuration secrets.
fn output(record: &Record) -> Result<()> {
    println!("{}", serde_json::to_string_pretty(record)?);
    Ok(())
}
/// Convert a Rust error into a readable message and a failing shell exit status.
/// Keeping the implementation in `run()` lets it use `?` for error propagation.
fn main() {
    if let Err(error) = run() {
        eprintln!("ERROR: {error:#}");
        std::process::exit(1);
    }
}
/// CLI entry point: parse the command, take the journal lock, load/create a record,
/// run its workflow, and print the resulting state even for many failed operations.
fn run() -> Result<()> {
    let args: Vec<String> = env::args().skip(1).collect();
    let command = args.first().map(String::as_str).unwrap_or("help");
    if matches!(command, "help" | "--help" | "-h") {
        println!("anki-poc ready [--once]\nanki-poc create|reconcile|verify|sync|sync-status|retry-sync|show LABEL\nanki-poc confirm-phone LABEL --observed\nState lives in ANKI_STATE_DIR (.state). Reuse LABEL on retries. Never delete ambiguous state.");
        return Ok(());
    }
    let api = Api::new()?;
    if command == "ready" {
        api.ready(args.get(1).is_some_and(|x| x == "--once"))?;
        println!(
            "READY: pinned Anki, open collection, profile, deck, fields and sync contract verified"
        );
        return Ok(());
    }
    ensure!(
        [
            "create",
            "reconcile",
            "verify",
            "sync",
            "sync-status",
            "retry-sync",
            "show",
            "confirm-phone"
        ]
        .contains(&command),
        "Unknown command"
    );
    let label = args
        .get(1)
        .context("Request label required, e.g. A, C-restart, C-recreate, D")?;
    // Labels become filenames. Restricting their characters also rejects paths
    // such as ../other-file, keeping all request records in the state directory.
    ensure!(
        !label.is_empty()
            && label.len() <= 64
            && label
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_'),
        "Invalid request label"
    );
    let dir = PathBuf::from(setting("ANKI_STATE_DIR", ".state"));
    fs::create_dir_all(&dir)?;
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(dir.join("driver.lock"))?;
    // Keep this File alive until run() returns: dropping it releases the OS lock.
    // Use one shared state directory for all writers; separate directories would
    // have separate locks and would not serialize each other.
    lock.try_lock_exclusive()
        .context("Another driver command is active; commands must be serialized")?;
    let path = dir.join(format!("{label}.json"));
    let mut record = if path.exists() {
        load(&path)?
    } else {
        ensure!(command == "create", "Request not found; run create first");
        let record = Record::new(label, &api);
        save(&path, &record)?;
        record
    };
    record.check_config(&api)?;
    let result = match command {
        "create" => create(&api, &path, &mut record),
        "reconcile" => reconcile(&api, &path, &mut record),
        "verify" => {
            api.ready(false)?;
            let id = record.note_id.context("No saved note ID; use reconcile")?;
            verify(&api, &path, &mut record, id)
        }
        "sync" => sync(&api, &path, &mut record, false),
        "retry-sync" => sync(&api, &path, &mut record, true),
        "sync-status" => poll_sync(&api, &path, &mut record),
        "show" => Ok(()),
        "confirm-phone" => {
            // This is a human assertion recorded by the CLI, not remote phone
            // automation. The flag must follow an actual visual inspection.
            ensure!(
                args.get(2).is_some_and(|v| v == "--observed"),
                "Requires human observation: --observed"
            );
            ensure!(
                record
                    .sync
                    .last()
                    .is_some_and(|s| s.status == "sync_confirmed"),
                "Server sync must be confirmed first"
            );
            record.phone_observed_at_ms = Some(now());
            save(&path, &record)
        }
        _ => unreachable!(),
    };
    output(&record)?;
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unicode_readback_requires_cards_tags_and_exact_fields() {
        // Begin with a valid response, then break individual facts. A validator
        // must reject the broken examples rather than merely accept happy paths.
        let record = Record {
            label: "A".into(),
            request_id: "123".into(),
            profile: "POC".into(),
            deck: "POC".into(),
            model: "Basic".into(),
            front: "zażółć gęślą jaźń".into(),
            back: "日本語".into(),
            created_at_ms: 0,
            creation: "prepared".into(),
            note_id: None,
            readback_at_ms: None,
            sync: vec![],
            phone_observed_at_ms: None,
        };
        let mut note = json!({"noteId":42,"modelName":"Basic","fields":{"Front":{"value":record.front},
            "Back":{"value":record.back}},"tags":[record.tag(),"anki_poc"],"cards":[43]});
        assert_eq!(validate_note(&note, &record, 42).unwrap(), vec![43]);
        note["fields"]["Front"]["value"] = json!("zazolc");
        assert!(validate_note(&note, &record, 42).is_err());
        note["fields"]["Front"]["value"] = json!(record.front);
        note["cards"] = json!([]);
        assert!(validate_note(&note, &record, 42).is_err());
    }
}
