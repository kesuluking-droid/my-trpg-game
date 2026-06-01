# -*- coding: utf-8 -*-
import unittest

from sandbox_undo_manager import (
    apply_inverse_patch_to_state,
    build_inverse_patch,
    estimate_undo_size,
    restore_legacy_snapshot,
)


class DictSession(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value


class UndoManagerTest(unittest.TestCase):
    def test_dict_value_change_can_restore_before(self):
        before = {"major_graph": {"entities": {"方拓": {"hp": 10}}}}
        after = {"major_graph": {"entities": {"方拓": {"hp": 5}}}}

        patch = build_inverse_patch(before, after)
        apply_inverse_patch_to_state(after, patch)

        self.assertEqual(after, before)

    def test_added_npc_is_deleted_on_undo(self):
        before = {"major_graph": {"entities": {}}}
        after = {"major_graph": {"entities": {"山贼": {"tags": ["NPC"]}}}}

        patch = build_inverse_patch(before, after)
        apply_inverse_patch_to_state(after, patch)

        self.assertEqual(after, before)

    def test_removed_item_is_restored_on_undo(self):
        before = {"major_graph": {"entities": {"方拓": {"6_inventory": {"长剑": {"multiplier": 1.0}}}}}}
        after = {"major_graph": {"entities": {"方拓": {"6_inventory": {}}}}}

        patch = build_inverse_patch(before, after)
        apply_inverse_patch_to_state(after, patch)

        self.assertEqual(after, before)

    def test_list_change_is_restored_by_set(self):
        before = {"active_scene": [{"role": "user", "content": "旧"}]}
        after = {"active_scene": [{"role": "user", "content": "旧"}, {"role": "assistant", "content": "新"}]}

        patch = build_inverse_patch(before, after)
        apply_inverse_patch_to_state(after, patch)

        self.assertEqual(after, before)

    def test_legacy_snapshot_restore(self):
        session = DictSession(active_scene=[], major_graph={})
        snapshot = {"active_scene": [{"role": "assistant", "content": "旧场景"}], "major_graph": {"entities": {}}}

        restore_legacy_snapshot(session, snapshot)

        self.assertEqual(session["active_scene"], snapshot["active_scene"])
        self.assertEqual(session["major_graph"], snapshot["major_graph"])

    def test_patch_smaller_than_full_snapshot_for_local_change(self):
        large_text = "旧剧情" * 1000
        before = {
            "history_archive": [{"summary": large_text}],
            "major_graph": {"entities": {"方拓": {"hp": 10, "desc": large_text}}},
        }
        after = {
            "history_archive": [{"summary": large_text}],
            "major_graph": {"entities": {"方拓": {"hp": 9, "desc": large_text}}},
        }

        patch = build_inverse_patch(before, after)

        self.assertLess(estimate_undo_size(patch), estimate_undo_size(before))


if __name__ == "__main__":
    unittest.main()
