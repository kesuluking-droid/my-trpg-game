import unittest
import sys
import types

sys.modules.setdefault("streamlit", types.SimpleNamespace())
from turn_engine import _canonical_entity_name, _should_initialize_entity_as_npc


class EntityFilterTest(unittest.TestCase):
    def test_object_annotation_does_not_initialize_npc(self):
        annotations = [
            {
                "name": "墙上的火把",
                "entity_type": "object",
                "role_in_action": "temporary_tool",
                "persistence": "ephemeral",
                "should_initialize_npc": False,
            }
        ]

        self.assertFalse(_should_initialize_entity_as_npc("墙上的火把", annotations))

    def test_character_annotation_initializes_npc(self):
        annotations = [
            {
                "name": "山贼",
                "entity_type": "character",
                "role_in_action": "opponent",
                "persistence": "persistent",
                "should_initialize_npc": True,
            }
        ]

        self.assertTrue(_should_initialize_entity_as_npc("山贼", annotations))

    def test_unknown_without_annotation_does_not_initialize_npc(self):
        self.assertFalse(_should_initialize_entity_as_npc("某个模糊实体", []))

    def test_canonical_name_matches_modified_surface_name(self):
        annotations = [
            {
                "name": "冲过来的山贼",
                "canonical_name": "山贼",
                "entity_type": "character",
                "role_in_action": "opponent",
                "persistence": "persistent",
                "should_initialize_npc": True,
            }
        ]

        self.assertTrue(_should_initialize_entity_as_npc("山贼", annotations))
        self.assertEqual(_canonical_entity_name("冲过来的山贼", annotations), "山贼")


if __name__ == "__main__":
    unittest.main()
