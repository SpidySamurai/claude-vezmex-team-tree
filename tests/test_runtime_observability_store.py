import json
import os
import tempfile
import unittest
from pathlib import Path

from src.runtime_observability import ids, model, paths, store


class RuntimeObservabilityStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.tmp.name

    def tearDown(self):
        if self.old is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self.old
        self.tmp.cleanup()

    def test_paths_preserve_existing_state_root_and_file_names(self):
        root = Path(self.tmp.name) / "herdr" / "claude-vezmex-team-tree"
        self.assertEqual(paths.state_root(), root)
        self.assertEqual(paths.snapshot_path(), root / "runtime-observability.json")
        self.assertEqual(paths.lock_path(), root / ".runtime-observability.lock")

    def test_write_session_creates_valid_snapshot_schema_and_private_root(self):
        session = model.Session("claude", "s1", presence="present", status="working", observed_at=1.0)
        store.update_session(session)
        data = json.loads(paths.snapshot_path().read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], model.SCHEMA)
        self.assertEqual(data["schema_version"], model.SCHEMA_VERSION)
        self.assertIn(ids.session_id("claude", "s1"), data["sessions"])
        self.assertEqual(paths.state_root().stat().st_mode & 0o777, 0o700)

    def test_malformed_or_invalid_snapshot_is_unavailable_safe(self):
        paths.ensure_state_root()
        paths.snapshot_path().write_text("{not json", encoding="utf-8")
        result = store.read_snapshot()
        self.assertFalse(result.available)
        self.assertEqual(result.sessions, {})
        paths.snapshot_path().write_text(json.dumps({"schema_version": 999, "sessions": {}}), encoding="utf-8")
        self.assertFalse(store.read_snapshot().available)

    def test_scoped_updates_do_not_overwrite_runtime_session_or_activity_siblings(self):
        claude = model.Session("claude", "same", presence="present", status="working")
        codex = model.Session("codex", "same", presence="present", status="idle")
        store.update_session(claude)
        store.update_session(codex)
        store.update_activity(model.Activity("claude", "same", "a1", "Explore", "working"))
        store.update_activity(model.Activity("claude", "other", "a1", "Review", "blocked"))
        snap = store.read_snapshot()
        self.assertEqual(set(snap.sessions), {ids.session_id("claude", "same"), ids.session_id("codex", "same"), ids.session_id("claude", "other")})
        self.assertIn(ids.activity_id(ids.session_id("claude", "same"), "a1"), snap.sessions[ids.session_id("claude", "same")]["activities"])
        self.assertIn(ids.activity_id(ids.session_id("claude", "other"), "a1"), snap.sessions[ids.session_id("claude", "other")]["activities"])

    def test_partial_file_read_is_safe_and_activity_updates_preserve_siblings(self):
        store.update_activity(model.Activity("pi", "s", "a1", "Tool", "working"))
        store.update_activity(model.Activity("pi", "s", "a2", "Prompt", "blocked"))
        snap = store.read_snapshot()
        self.assertEqual(len(snap.sessions[ids.session_id("pi", "s")]["activities"]), 2)
        paths.snapshot_path().write_text('{"schema":"herdr.runtime_observability.snapshot",', encoding="utf-8")
        self.assertFalse(store.read_snapshot().available)

    def test_one_invalid_session_entry_does_not_discard_valid_sessions(self):
        store.update_session(model.Session("claude", "keep", presence="present", status="working", observed_at=1.0))
        data = json.loads(paths.snapshot_path().read_text(encoding="utf-8"))
        data["sessions"]["not-a-canonical-id"] = {"runtime": "claude"}
        paths.snapshot_path().write_text(json.dumps(data), encoding="utf-8")
        result = store.read_snapshot()
        self.assertTrue(result.available)
        self.assertEqual(set(result.sessions), {ids.session_id("claude", "keep")})


if __name__ == "__main__":
    unittest.main()
