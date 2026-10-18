"""Prepare deterministic preferences without changing saved authentication."""
import os
from pathlib import Path


def prepare():
    # Import Anki lazily so policy unit tests can run on hosts without Qt/Anki.
    from aqt.profiles import ProfileManager
    from anki.lang import set_lang

    set_lang("en_US")
    name = os.environ["ANKI_PROFILE"]
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise RuntimeError("Invalid profile name")
    pm = ProfileManager(Path("/data"))
    if pm.setupMeta().loadError:
        raise RuntimeError("Profile metadata needs recovery")
    pm.create(name)
    pm.load(name)
    pm.meta.update(defaultLang="en_US", firstRun=False, suppressUpdate=True)
    # Sync stays under the observable Rust workflow's control.
    pm.profile["autoSync"] = False
    pm.save()
    return pm


def main():
    import json

    pm = prepare()
    try:
        journal = Path("/data/onboarding.json")
        if journal.exists():
            binding = json.loads(journal.read_text())
            from onboarding import check_binding
            check_binding(binding, pm.profile.get("syncUser") or "", pm.name,
                          pm.profile.get("syncUser"), True)
            if not binding["initialized"]:
                raise RuntimeError("Initial download incomplete; run scripts/poc onboard")
        # Legacy authenticated POC volumes remain usable. Fresh ones must be
        # provisioned first; Desktop must never offer an invisible login dialog.
        if not pm.sync_auth() or not Path(pm.collectionPath()).exists():
            raise RuntimeError("Authentication missing; run scripts/poc onboard")
    finally:
        pm.db.close()


if __name__ == "__main__":
    main()
