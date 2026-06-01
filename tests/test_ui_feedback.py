# -*- coding: utf-8 -*-
import unittest

from sandbox_ui_feedback import get_friendly_status_text, safe_status


class UiFeedbackTest(unittest.TestCase):
    def test_known_stage_returns_friendly_text(self):
        text = get_friendly_status_text("intent_parse")
        self.assertIn("正在", text)
        self.assertIn("行动意图", text)

    def test_unknown_stage_returns_default_text(self):
        text = get_friendly_status_text("unknown_stage")
        self.assertIn("正在", text)
        self.assertIn("命运", text)

    def test_safe_status_calls_callback_with_stage(self):
        called = []
        safe_status(lambda stage: called.append(stage), "narration")
        self.assertEqual(called, ["narration"])

    def test_safe_status_ignores_callback_errors(self):
        def broken(_stage):
            raise RuntimeError("ui closed")

        safe_status(broken, "narration")


if __name__ == "__main__":
    unittest.main()
