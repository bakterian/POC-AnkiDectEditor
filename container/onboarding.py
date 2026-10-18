"""Provision one account without a desktop login dialog.

Only this one-shot command reads an AnkiWeb password. The normal desktop process
uses the saved sync key. The entrypoint holds the volume lock for both modes, so
this script can never open a collection that the desktop already owns.
"""
import json
import os
from pathlib import Path


class ProvisionError(Exception):
    """A stable error code that is safe to show without exposing credentials."""


def write_json(path, value):
    """Replace the journal atomically; fsync makes crash recovery meaningful."""
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def account_id(value):
    # AnkiWeb identifiers are email addresses. This is local identity comparison,
    # not a claim that we have verified who owns the remote account.
    return value.strip().casefold()


def check_binding(binding, username, profile, saved_username, collection_exists):
    """Reject account/profile switching BEFORE any login or collection write."""
    if binding and (binding["account"] != account_id(username)
                    or binding["profile"] != profile):
        raise ProvisionError("account_binding_mismatch")
    if saved_username and account_id(saved_username) != account_id(username):
        raise ProvisionError("account_binding_mismatch")
    if collection_exists and not binding and not saved_username:
        raise ProvisionError("existing_unbound_collection")


def initialize_collection(col, pm, auth, binding, journal, allow_download):
    """Only a never-served, bootstrap-owned collection may be replaced remotely.

    An interrupted initial download can be retried because Desktop cannot start
    until initialized=True is durably recorded. Existing collections are never
    uploaded or downloaded by this provisioning command.
    """
    if binding["initialized"]:
        return
    if not allow_download:
        raise ProvisionError("initial_download_policy_required")
    result = col.sync_collection(auth, sync_media=False)
    pm.set_host_number(result.host_number)
    if result.new_endpoint:
        pm.set_current_sync_url(result.new_endpoint)
        auth.endpoint = result.new_endpoint
    pm.save()
    if result.required == result.FULL_UPLOAD:
        # Empty AnkiWeb accounts need a separately approved initial upload policy.
        raise ProvisionError("ankiweb_collection_required")
    if result.required != result.NO_CHANGES:
        col.close_for_full_sync()
        try:
            col.full_upload_or_download(auth=auth, server_usn=None, upload=False)
        finally:
            # The backend reopens its collection after full sync; rebuild Python's
            # DB proxy as Desktop does, even when a transfer raises an error.
            col.reopen(after_full_sync=True)
    binding["initialized"] = True
    write_json(journal, binding)


def provision(pm, credentials_path, allow_download):
    from anki.collection import Collection

    credentials = json.loads(credentials_path.read_text())
    username, password = credentials["username"].strip(), credentials["password"]
    if not username or not isinstance(password, str) or not password:
        raise ProvisionError("credentials_required")
    root = Path(pm.base)
    journal = root / "onboarding.json"
    binding = json.loads(journal.read_text()) if journal.exists() else None
    exists = Path(pm.collectionPath()).exists()
    check_binding(binding, username, pm.name, pm.profile.get("syncUser"), exists)
    if binding is None:
        # Old POC profiles may be adopted only when their saved account matches.
        # Fresh volumes are bound before opening a new collection, so a crash
        # cannot leave an ambiguous, apparently pre-existing collection behind.
        if not exists and not allow_download:
            raise ProvisionError("initial_download_policy_required")
        binding = {"account": account_id(username), "profile": pm.name,
                   "initialized": exists, "version": 1}
        write_json(journal, binding)
    col = Collection(pm.collectionPath())
    try:
        # This is the backend method, NOT aqt.sync.sync_login(), which shows UI.
        auth = col.sync_login(username=username, password=password,
                              endpoint=pm.sync_endpoint())
        pm.set_sync_key(auth.hkey)
        pm.set_sync_username(username)
        pm.save()
        initialize_collection(col, pm, auth, binding, journal, allow_download)
        model = col.models.by_name(os.environ.get("ANKI_MODEL", "Basic"))
        if not model or [f["name"] for f in model["flds"]] != ["Front", "Back"]:
            raise ProvisionError("incompatible_note_type")
        # Download replaces the entire collection, so create our test deck AFTER
        # initialization. Deck creation does not force a note-type/schema change.
        col.decks.id(os.environ.get("ANKI_DECK", "POC"))
    finally:
        col.close()


def main():
    from prepare_profile import prepare
    from anki.errors import SyncError

    os.umask(0o077)
    status = Path("/data/onboarding-status.json")
    pm = None
    try:
        pm = prepare()
        provision(pm, Path("/run/poc/ankiweb.json"),
                  os.environ.get("ANKI_INITIAL_SYNC") == "download")
    except ProvisionError as error:
        code = str(error)
    except SyncError as error:
        # Do not print the exception message or traceback: third-party messages
        # may include account details. The enum is sufficient for remediation.
        code = "sync_" + error.kind.name.lower()
    except Exception:
        code = "onboarding_failed"
    else:
        code = "ready"
    finally:
        if pm is not None:
            pm.db.close()
        # Delete the writable runtime copy. The host source is controlled by the
        # caller and is removed by scripts/poc only after successful onboarding.
        Path("/run/poc/ankiweb.json").unlink(missing_ok=True)
    write_json(status, {"status": code})
    print(json.dumps({"status": code}), flush=True)
    raise SystemExit(0 if code == "ready" else 1)


if __name__ == "__main__":
    main()
