import json
import os
import tempfile
import unittest

from src.runtime_observability import legacy, paths


class RuntimeObservabilityLegacyTests(unittest.TestCase):
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

    def write_legacy(self, value):
        paths.ensure_state_root()
        paths.legacy_subagents_path().write_text(json.dumps(value), encoding="utf-8")

    def test_reads_existing_subagents_json_for_a_session(self):
        self.write_legacy({"sessions": {"s1": {"a2": {"name": "Review", "status": "blocked"}, "a1": {"name": "Explore", "status": "working", "started": 10}}}})
        children = legacy.children_for_session("s1")
        self.assertEqual([child["id"] for child in children], ["a1", "a2"])
        self.assertEqual(children[0]["agent_status"], "working")
        self.assertEqual(children[0]["started"], 10)

    def test_missing_malformed_or_missing_session_is_safe(self):
        self.assertEqual(legacy.children_for_session("s1"), [])
        paths.ensure_state_root()
        paths.legacy_subagents_path().write_text("not json", encoding="utf-8")
        self.assertEqual(legacy.children_for_session("s1"), [])
        self.write_legacy({"sessions": {"other": {}}})
        self.assertEqual(legacy.children_for_session("s1"), [])
        self.assertEqual(legacy.children_for_session(None), [])


if __name__ == "__main__":
    unittest.main()
