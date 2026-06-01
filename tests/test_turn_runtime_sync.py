import sys
import types
import unittest

sys.modules.setdefault("streamlit", types.SimpleNamespace())

from turn_runtime import _apply_direct_state_patch, _apply_extracted_state_patch


class TurnRuntimeSyncTest(unittest.TestCase):
    def make_graph(self):
        return {
            "entities": {
                "柯酥卤": {
                    "2_dynamic_status": {"physical": {"desc": "健康", "multiplier": 1.0}},
                    "6_inventory": {},
                }
            }
        }

    def test_suppress_inventory_sync_keeps_status_but_skips_inventory(self):
        graph = self.make_graph()
        patch = {
            "柯酥卤": {
                "2_dynamic_status": {"physical": {"desc": "擦伤", "multiplier": 0.95}},
                "new_assets": [
                    {"category": "6_inventory", "name": "火把", "target_domains": ["照明"], "multiplier": 1.0}
                ],
                "removed_assets": [],
            }
        }

        updated = _apply_extracted_state_patch(graph, patch, "柯酥卤", suppress_inventory_sync=True)

        self.assertEqual(updated["entities"]["柯酥卤"]["2_dynamic_status"]["physical"]["desc"], "擦伤")
        self.assertNotIn("火把", updated["entities"]["柯酥卤"]["6_inventory"])

    def test_direct_state_patch_applies_held_item_changes(self):
        graph = self.make_graph()
        graph["entities"]["柯酥卤"]["7_held_items"] = {
            "石头": {"tags": ["投掷物"], "persistence": "ephemeral"}
        }
        patch = {
            "held_item_changes": {
                "pc_name": "柯酥卤",
                "add": {"火把": {"tags": ["燃烧", "照明"], "persistence": "ephemeral"}},
                "remove": ["石头"],
            }
        }

        updated = _apply_direct_state_patch(graph, patch, "柯酥卤")

        held_items = updated["entities"]["柯酥卤"]["7_held_items"]
        self.assertIn("火把", held_items)
        self.assertNotIn("石头", held_items)


if __name__ == "__main__":
    unittest.main()
