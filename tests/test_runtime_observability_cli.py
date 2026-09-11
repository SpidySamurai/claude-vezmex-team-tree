"""The ingestion boundary a Pi extension shells out to, one event per call."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.runtime_observability import ids, store

CLI = Path(__file__).resolve().parent.parent / "src" / "runtime_observability_cli.py"


class RuntimeObservabilityCliTests(unittest.TestCase):
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

    def run_cli(self, event) -> int:
        completed = subprocess.run(
            [sys.executable, str(CLI)],
            input="" if event is None else json.dumps(event), text=True, capture_output=True,
            env=os.environ | {"XDG_STATE_HOME": self.tmp.name}, timeout=30, check=False,
        )
        return completed.returncode

    def test_a_pi_event_reaches_canonical_state_tagged_as_pi(self):
        self.assertEqual(self.run_cli({"kind": "session_start", "session_id": "s1"}), 0)
        record = store.read_snapshot().sessions.get(ids.session_id("pi", "s1"))
        self.assertIsNotNone(record)
        self.assertEqual(record["source"]["runtime"], "pi")

    def test_malformed_or_empty_stdin_exits_zero_without_state(self):
        self.assertEqual(self.run_cli(None), 0)
        self.assertEqual(store.read_snapshot().sessions, {})

    def test_an_unsupported_event_kind_exits_zero_without_state(self):
        self.assertEqual(self.run_cli({"kind": "nested_askclaude_internal", "session_id": "s1"}), 0)
        self.assertEqual(store.read_snapshot().sessions, {})


if __name__ == "__main__":
    unittest.main()
