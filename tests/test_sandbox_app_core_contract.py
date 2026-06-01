# -*- coding: utf-8 -*-
import unittest
import ast
from pathlib import Path


class SandboxAppCoreContractTest(unittest.TestCase):
    def test_sandbox_core_engine_exports_ui_required_functions(self):
        source = Path("sandbox_core_engine.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        exported_functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        required = [
            "login_user",
            "register_user",
            "get_security_question",
            "retrieve_password",
            "modify_password",
            "sync_world_anchor_and_scale",
            "rename_user_session",
            "delete_user_session",
            "build_context",
            "generate_ai_suggestions",
            "extract_memory_summary",
        ]
        missing = [name for name in required if name not in exported_functions]
        self.assertEqual(missing, [])

    def test_sandbox_auth_uses_existing_users_auth_table(self):
        source = Path("sandbox_core_engine.py").read_text(encoding="utf-8")
        self.assertIn('return "users_auth"', source)
        self.assertNotIn('return "users"', source)

    def test_sandbox_app_uses_core_engine_alias_consistently(self):
        source = Path("sandbox_app.py").read_text(encoding="utf-8")
        self.assertIn("import sandbox_core_engine as core_engine", source)
        self.assertNotIn("sandbox_core_engine.execute_sandbox_turn", source)
        self.assertIn("core_engine.execute_sandbox_turn", source)

    def test_show_turn_status_defined_before_callback_use(self):
        source = Path("sandbox_app.py").read_text(encoding="utf-8")
        define_idx = source.find("def show_turn_status(stage):")
        use_idx = source.find("status_callback=show_turn_status")
        self.assertGreaterEqual(define_idx, 0)
        self.assertGreater(use_idx, define_idx)


if __name__ == "__main__":
    unittest.main()
