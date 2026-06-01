import unittest

from intent_engine import _normalize_parsed_intent, build_intent_parse_prompt


class IntentPromptTest(unittest.TestCase):
    def test_build_intent_parse_prompt_allows_nested_json_examples(self):
        prompt = build_intent_parse_prompt(
            pc_name="柯酥卤",
            inventory_snapshot="短剑",
            entity_glossary="山贼[敌对]",
            recent_context="无",
        )

        self.assertIn('"action_sequence"', prompt)
        self.assertIn('"required_items": {"物品规范名canonical_name": 1}', prompt)
        self.assertIn('"consumed_items": {"物品规范名canonical_name": 1}', prompt)
        self.assertIn('"reward_items"', prompt)
        self.assertIn('"action_label"', prompt)
        self.assertIn('"action_label": "可选机器标签', prompt)
        self.assertIn('"intended_action": "自然语言动作描述', prompt)
        self.assertIn("不得只填 use_tool", prompt)
        self.assertIn("world_state_change 不是裁判结果字段", prompt)
        self.assertIn("is_risk=true", prompt)
        self.assertIn("不得预写成功后果", prompt)
        self.assertIn("结果仍待裁决", prompt)
        self.assertIn("使用武器、火焰、盾牌、障碍物、地形", prompt)
        self.assertIn("禁止只默认写", prompt)
        self.assertIn("威慑", prompt)
        self.assertIn("entity_annotations.canonical_name", prompt)
        self.assertIn("柯酥卤", prompt)

    def test_normalize_converts_string_none_and_keeps_new_item_fields(self):
        parsed = _normalize_parsed_intent({
            "intended_action": "夺刀反击",
            "action_category": "combat",
            "initiator_entity": "柯酥卤",
            "detected_ability": "None",
            "target_entity": "山贼",
            "target_ongoing_action": "冲锋",
            "action_sequence": [
                {
                    "action_id": "a1",
                    "actor": "柯酥卤",
                    "target": "山贼",
                    "target_part": "手腕",
                    "detected_ability": "无",
                    "target_ongoing_action": "None",
                    "required_items": {"长刀": 1},
                    "consumed_items": {},
                    "temporary_items": {},
                    "reward_items": {},
                }
            ],
        })

        self.assertIsNone(parsed["detected_ability"])
        self.assertEqual(parsed["target_ongoing_action"], "冲锋")
        self.assertIsNone(parsed["action_sequence"][0]["detected_ability"])
        self.assertEqual(parsed["action_sequence"][0]["target_ongoing_action"], "冲锋")
        self.assertEqual(parsed["action_sequence"][0]["target_part"], "手腕")
        self.assertEqual(parsed["action_sequence"][0]["required_items"], {"长刀": 1})

    def test_normalize_canonicalizes_action_sequence_item_keys_from_entity_annotations(self):
        parsed = _normalize_parsed_intent({
            "intended_action": "拔火把逼退山贼",
            "action_category": "combat",
            "initiator_entity": "柯酥卤",
            "target_entity": "山贼",
            "entity_annotations": [
                {
                    "name": "墙上的火把",
                    "canonical_name": "火把",
                    "entity_type": "object",
                    "role_in_action": "temporary_tool",
                    "persistence": "ephemeral",
                    "should_initialize_npc": False,
                },
                {
                    "name": "燃烧的火把",
                    "canonical_name": "火把",
                    "entity_type": "object",
                    "role_in_action": "tool",
                    "persistence": "ephemeral",
                    "should_initialize_npc": False,
                },
            ],
            "action_sequence": [
                {
                    "action_id": "a1",
                    "actor": "柯酥卤",
                    "target": "墙上的火把",
                    "action_type": "skill",
                    "intended_action": "从墙上拔下燃烧的火把",
                    "temporary_items": {
                        "墙上的火把": {"tags": ["照明"], "persistence": "ephemeral"},
                        "燃烧的火把": {"tags": ["燃烧", "威慑"], "persistence": "ephemeral"},
                    },
                    "is_risk": False,
                },
                {
                    "action_id": "a2",
                    "actor": "柯酥卤",
                    "target": "山贼",
                    "action_type": "combat",
                    "intended_action": "用燃烧的火把逼退山贼",
                    "depends_on": ["a1"],
                    "required_items": {"燃烧的火把": 1, "火把": 1},
                },
            ],
        })

        temp_items = parsed["action_sequence"][0]["temporary_items"]
        self.assertIn("火把", temp_items)
        self.assertNotIn("墙上的火把", temp_items)
        self.assertNotIn("燃烧的火把", temp_items)
        self.assertEqual(sorted(temp_items["火把"]["tags"]), ["威慑", "照明", "燃烧"])
        self.assertEqual(parsed["action_sequence"][1]["required_items"], {"火把": 2})

    def test_normalize_keeps_unannotated_item_keys_unchanged(self):
        parsed = _normalize_parsed_intent({
            "intended_action": "使用未知道具",
            "action_category": "skill",
            "initiator_entity": "柯酥卤",
            "action_sequence": [
                {
                    "action_id": "a1",
                    "actor": "柯酥卤",
                    "target": "环境",
                    "action_type": "skill",
                    "intended_action": "使用奇怪机关钥匙",
                    "required_items": {"奇怪机关钥匙": 1},
                }
            ],
        })

        self.assertEqual(parsed["action_sequence"][0]["required_items"], {"奇怪机关钥匙": 1})

    def test_normalize_keeps_top_level_action_label_separate_from_intended_action(self):
        parsed = _normalize_parsed_intent({
            "intended_action": "用火把逼退山贼",
            "action_label": "use_tool",
            "action_category": "combat",
            "world_state_change": "玩家试图用火把逼退山贼，结果仍待裁决。",
            "is_risk": True,
        })

        self.assertEqual(parsed["intended_action"], "用火把逼退山贼")
        self.assertEqual(parsed["action_label"], "use_tool")
        self.assertEqual(parsed["world_state_change"], "玩家试图用火把逼退山贼，结果仍待裁决。")

    def test_normalize_action_label_none_values(self):
        parsed = _normalize_parsed_intent({
            "intended_action": "观察房间",
            "action_label": "None",
            "action_category": "none",
            "is_risk": False,
        })

        self.assertIsNone(parsed["action_label"])


if __name__ == "__main__":
    unittest.main()
