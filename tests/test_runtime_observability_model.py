import unittest

from src.runtime_observability import ids, model


class RuntimeObservabilityModelTests(unittest.TestCase):
    def test_runtime_and_status_vocabularies_are_bounded(self):
        self.assertEqual(model.ALLOWED_RUNTIMES, {"claude", "codex", "pi"})
        self.assertEqual(model.normalize_status("in_progress"), "working")
        self.assertEqual(model.normalize_status("succeeded"), "done")
        self.assertEqual(model.normalize_status("mystery"), "unknown")
        self.assertEqual(model.normalize_status({"bad": "shape"}), "unknown")
        self.assertEqual(model.normalize_status(None), "unknown")

    def test_ids_are_unpadded_reversible_and_runtime_namespaced(self):
        claude = ids.session_id("claude", "same/raw id")
        codex = ids.session_id("codex", "same/raw id")
        self.assertNotEqual(claude, codex)
        self.assertNotIn("=", claude)
        self.assertEqual(ids.raw_session_id(claude), "same/raw id")
        activity = ids.activity_id(claude, "child/one")
        self.assertEqual(ids.raw_activity_id(activity), "child/one")
        self.assertTrue(activity.startswith(claude + ":activity:"))

    def test_id_helpers_reject_missing_malformed_and_cross_runtime_values(self):
        for raw in ("", None):
            with self.assertRaises(ValueError):
                ids.session_id("claude", raw)
        with self.assertRaises(ValueError):
            ids.session_id("unknown", "s")
        with self.assertRaises(ValueError):
            ids.raw_session_id("not-a-runtime-id")
        with self.assertRaises(ValueError):
            ids.activity_id(ids.session_id("claude", "s"), "")

    def test_unicode_ids_and_same_activity_under_different_sessions_do_not_collide(self):
        first = ids.session_id("pi", "sesión/🙂")
        second = ids.session_id("pi", "otra")
        self.assertEqual(ids.raw_session_id(first), "sesión/🙂")
        self.assertNotEqual(ids.activity_id(first, "agent-1"), ids.activity_id(second, "agent-1"))

    def test_capabilities_distinguish_activity_certainty_and_legacy_features(self):
        caps = model.capabilities(activity="complete", history="legacy-only", artifacts="unsupported")
        self.assertEqual(caps["activity"], "complete")
        self.assertEqual(caps["history"], "legacy-only")
        self.assertEqual(caps["artifacts"], "unsupported")
        with self.assertRaises(ValueError):
            model.capabilities(activity="certain")

    def test_empty_status_payloads_and_misspelled_capability_keys_stay_bounded(self):
        for value in ("", "   ", "\n"):
            self.assertEqual(model.normalize_status(value), "unknown")
        self.assertEqual(model.normalize_capability("certain"), "unknown")
        # A misspelled key must not silently create an unreadable capability.
        with self.assertRaises(ValueError):
            model.capabilities(activty="complete")


if __name__ == "__main__":
    unittest.main()
