"""Test provisioning policy with fake Anki objects, without a remote account.

The fake records calls so tests can prove that unsafe actions never happened.
Real network authentication and persistent-volume behavior are separate live tests.
"""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "container"))
from onboarding import ProvisionError, provision, write_json


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.secret = self.root / "credentials.json"
        self.secret.write_text(json.dumps({"username": "user@example.test", "password": "test"}))
        self.pm = Mock(base=self.root, profile={})
        self.pm.name = "POC"
        self.pm.collectionPath.return_value = str(self.root / "collection.anki2")
        self.col = Mock()
        self.col.sync_login.return_value = SimpleNamespace(hkey="fake-key", endpoint="")
        self.result = SimpleNamespace(required=2, NO_CHANGES=0, FULL_UPLOAD=1,
                                      FULL_DOWNLOAD=2, host_number=1, new_endpoint="")
        self.col.sync_collection.return_value = self.result
        self.col.models.by_name.return_value = {"flds": [{"name": "Front"}, {"name": "Back"}]}
        self.factory = Mock(return_value=self.col)
        self.modules = patch.dict(sys.modules, {"anki.collection": SimpleNamespace(Collection=self.factory)})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def run_provision(self, allow=True):
        provision(self.pm, self.secret, allow)

    def test_fresh_login_download_then_deck(self):
        self.run_provision()
        self.col.sync_login.assert_called_once()
        self.col.full_upload_or_download.assert_called_once_with(
            auth=self.col.sync_login.return_value, server_usn=None, upload=False)
        self.col.close_for_full_sync.assert_called_once()
        self.col.reopen.assert_called_once_with(after_full_sync=True)
        self.col.decks.id.assert_called_once()
        self.assertTrue(json.loads((self.root / "onboarding.json").read_text())["initialized"])

    def test_new_account_cannot_replace_bound_volume(self):
        write_json(self.root / "onboarding.json", {
            "account": "someone-else@example.test", "profile": "POC", "initialized": True})
        with self.assertRaisesRegex(ProvisionError, "account_binding_mismatch"):
            self.run_provision()
        self.factory.assert_not_called()

    def test_same_account_wrong_profile_is_rejected(self):
        write_json(self.root / "onboarding.json", {
            "account": "user@example.test", "profile": "Other", "initialized": True})
        with self.assertRaisesRegex(ProvisionError, "account_binding_mismatch"):
            self.run_provision()
        self.factory.assert_not_called()

    def test_legacy_account_mismatch_is_rejected(self):
        self.pm.profile = {"syncUser": "someone-else@example.test"}
        with self.assertRaisesRegex(ProvisionError, "account_binding_mismatch"):
            self.run_provision()
        self.factory.assert_not_called()

    def test_existing_unbound_collection_is_preserved(self):
        Path(self.pm.collectionPath()).touch()
        with self.assertRaisesRegex(ProvisionError, "existing_unbound_collection"):
            self.run_provision()
        self.factory.assert_not_called()

    def test_existing_account_reauth_never_downloads(self):
        Path(self.pm.collectionPath()).touch()
        self.pm.profile = {"syncUser": "USER@example.test"}
        self.run_provision()
        self.col.sync_login.assert_called_once()
        self.col.sync_collection.assert_not_called()
        self.col.full_upload_or_download.assert_not_called()

    def test_password_error_does_not_initialize_or_sync(self):
        self.col.sync_login.side_effect = RuntimeError("fake auth failure")
        with self.assertRaises(RuntimeError):
            self.run_provision()
        self.assertFalse(json.loads((self.root / "onboarding.json").read_text())["initialized"])
        self.col.sync_collection.assert_not_called()
        self.col.close.assert_called_once()

    def test_initial_download_requires_policy(self):
        with self.assertRaisesRegex(ProvisionError, "initial_download_policy_required"):
            self.run_provision(allow=False)
        self.factory.assert_not_called()

    def test_empty_remote_never_triggers_upload(self):
        self.result.required = self.result.FULL_UPLOAD
        with self.assertRaisesRegex(ProvisionError, "ankiweb_collection_required"):
            self.run_provision()
        self.col.full_upload_or_download.assert_not_called()
        self.assertFalse(json.loads((self.root / "onboarding.json").read_text())["initialized"])

    def test_failed_download_is_retryable_only_before_initialization(self):
        self.col.full_upload_or_download.side_effect = RuntimeError("fake outage")
        with self.assertRaises(RuntimeError):
            self.run_provision()
        self.assertFalse(json.loads((self.root / "onboarding.json").read_text())["initialized"])
        self.col.full_upload_or_download.side_effect = None
        self.run_provision()
        self.assertTrue(json.loads((self.root / "onboarding.json").read_text())["initialized"])
        self.col.sync_collection.reset_mock()
        self.run_provision()
        self.col.sync_collection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
