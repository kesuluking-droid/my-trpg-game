# -*- coding: utf-8 -*-
"""
test_secondary_match_removal.py — 二次判断移除后的回归测试

二次判断原本的功能：
1. 当意图解析没有识别到 detected_ability 时，用 FLASH 从 NPC 能力列表中匹配
2. 作为兜底机制，确保 NPC 使用的能力能被正确识别

移除后的风险点：
- 意图解析必须完全承担能力识别责任
- 如果意图解析漏判能力，将没有二次补救

本测试验证：意图解析在以下场景能否正确识别 NPC 能力
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import json

# 注意：测试沙盒版本
import sys
sys.path.insert(0, 'd:\\game\\AI')

from sandbox_intent_engine import build_intent_parse_prompt, _normalize_parsed_intent


class SecondaryMatchRemovalTest(unittest.TestCase):
    """
    验证移除二次判断后，意图解析能否独立正确识别 NPC 能力
    """

    def test_prompt_contains_npc_capabilities_for_matching(self):
        """
        【关键测试】验证意图解析 prompt 中包含 NPC 能力列表
        这是二次判断移除后的核心依赖：意图解析必须能看到 NPC 能力
        """
        entity_glossary = (
            "山贼[敌人,山贼] 能力:快刀,铁布衫 | "
            "黑衣人[刺客] 能力:偷袭,毒镖 | "
            "方拓[玩家]"
        )
        
        prompt = build_intent_parse_prompt(
            pc_name="方拓",
            inventory_snapshot="长剑",
            entity_glossary=entity_glossary,
            recent_context="山贼冲了过来",
        )
        
        # 验证能力列表在 prompt 中
        self.assertIn("快刀", prompt)
        self.assertIn("铁布衫", prompt)
        self.assertIn("偷袭", prompt)
        self.assertIn("毒镖", prompt)
        self.assertIn("山贼", prompt)
        
        # 验证 detected_ability 字段存在
        self.assertIn("detected_ability", prompt)

    def test_prompt_structure_allows_npc_ability_detection(self):
        """
        验证 prompt 结构支持 NPC 能力识别
        - 实体名录格式正确
        - 有明确的 detected_ability 输出字段
        """
        prompt = build_intent_parse_prompt(
            pc_name="主角",
            inventory_snapshot="",
            entity_glossary="敌人[敌对] 能力:招式A,招式B",
            recent_context="",
        )
        
        # 验证实体名录格式
        self.assertIn("【已知实体名录", prompt)
        self.assertIn("能力:", prompt)
        
        # 验证输出字段要求
        self.assertIn('"detected_ability":', prompt)
        self.assertIn("发起方使用的具体能力、招式或技能名", prompt)

    def test_normalize_handles_missing_detected_ability(self):
        """
        验证当意图解析返回 null/None 时，_normalize_parsed_intent 正确处理
        （这是二次判断原本会兜底的情况）
        """
        # 情况1：字符串 "None"
        parsed1 = _normalize_parsed_intent({
            "intended_action": "攻击山贼",
            "detected_ability": "None",
            "target_entity": "山贼",
        })
        self.assertIsNone(parsed1["detected_ability"])
        
        # 情况2：字符串 "null"
        parsed2 = _normalize_parsed_intent({
            "intended_action": "攻击山贼", 
            "detected_ability": "null",
            "target_entity": "山贼",
        })
        self.assertIsNone(parsed2["detected_ability"])
        
        # 情况3：字段缺失
        parsed3 = _normalize_parsed_intent({
            "intended_action": "攻击山贼",
            "target_entity": "山贼",
        })
        self.assertIsNone(parsed3.get("detected_ability"))

    def test_normalize_preserves_valid_npc_ability(self):
        """
        验证当意图解析正确识别 NPC 能力时，能够保留
        """
        parsed = _normalize_parsed_intent({
            "intended_action": "山贼使用快刀劈向玩家",
            "detected_ability": "快刀",
            "initiator_entity": "山贼",
            "target_entity": "主角",
            "action_category": "combat",
        })
        
        self.assertEqual(parsed["detected_ability"], "快刀")
        self.assertEqual(parsed["initiator_entity"], "山贼")


class IntentParsingScenariosTest(unittest.TestCase):
    """
    关键场景测试：这些场景在二次判断移除后需要特别关注
    """

    def test_scenario_npc_attacks_with_ability(self):
        """
        场景：NPC 主动攻击玩家，使用特定招式
        例："山贼使用快刀劈向你"
        
        期望：detected_ability = "快刀"
        """
        # 这个测试需要实际调用 LLM，这里验证 prompt 结构
        entity_glossary = "山贼[敌人] 能力:快刀,铁布衫"
        
        prompt = build_intent_parse_prompt(
            pc_name="主角",
            inventory_snapshot="长剑",
            entity_glossary=entity_glossary,
            recent_context="山贼：吃我一刀！",
        )
        
        # 验证 prompt 包含足够信息让 LLM 判断
        self.assertIn("山贼", prompt)
        self.assertIn("快刀", prompt)
        self.assertIn("detected_ability", prompt)

    def test_scenario_player_defends_against_npc_ability(self):
        """
        场景：玩家防御 NPC 的特定招式
        例："挡住山贼的快刀攻击"
        
        期望：target_ongoing_action = "快刀" 或 detected_ability 正确识别
        """
        entity_glossary = "山贼[敌人] 能力:快刀"
        
        prompt = build_intent_parse_prompt(
            pc_name="主角",
            inventory_snapshot="长剑,盾牌",
            entity_glossary=entity_glossary,
            recent_context="山贼挥舞快刀冲来",
        )
        
        # 验证 prompt 包含防御方需要的信息
        self.assertIn("快刀", prompt)
        self.assertIn("target_ongoing_action", prompt)

    def test_scenario_multiple_npcs_different_abilities(self):
        """
        场景：多个 NPC 同时使用不同能力
        例："山贼用快刀攻击，黑衣人用毒镖偷袭"
        
        期望：action_sequence 中每个动作都有正确的 detected_ability
        """
        entity_glossary = (
            "山贼[敌人] 能力:快刀,铁布衫 | "
            "黑衣人[刺客] 能力:偷袭,毒镖"
        )
        
        prompt = build_intent_parse_prompt(
            pc_name="主角",
            inventory_snapshot="",
            entity_glossary=entity_glossary,
            recent_context="山贼和黑衣人同时攻来",
        )
        
        # 验证所有 NPC 和能力都在 prompt 中
        self.assertIn("山贼", prompt)
        self.assertIn("黑衣人", prompt)
        self.assertIn("快刀", prompt)
        self.assertIn("毒镖", prompt)
        self.assertIn("action_sequence", prompt)

    def test_scenario_ambiguous_ability_reference(self):
        """
        场景：玩家输入中能力引用不明确
        例："山贼使出了他的绝招"
        
        风险：二次判断原本可以从能力列表中匹配，现在依赖意图解析的语义理解
        """
        entity_glossary = "山贼[敌人] 能力:快刀,铁布衫,绝招"
        
        prompt = build_intent_parse_prompt(
            pc_name="主角",
            inventory_snapshot="",
            entity_glossary=entity_glossary,
            recent_context="山贼冷笑一声",
        )
        
        # 验证即使模糊的引用，prompt 也提供了完整能力列表
        self.assertIn("绝招", prompt)


class EdgeCasesTest(unittest.TestCase):
    """
    边界情况测试
    """

    def test_empty_npc_capabilities(self):
        """
        场景：NPC 还没有初始化能力（3_capabilities 为空）
        """
        entity_glossary = "神秘人[未知]"  # 没有能力列表
        
        prompt = build_intent_parse_prompt(
            pc_name="主角",
            inventory_snapshot="",
            entity_glossary=entity_glossary,
            recent_context="一个神秘人出现",
        )
        
        # 验证 prompt 仍然可用
        self.assertIn("神秘人", prompt)
        self.assertIn("detected_ability", prompt)

    def test_no_npc_in_scene(self):
        """
        场景：场景中没有 NPC（只有环境）
        """
        entity_glossary = "无已知NPC"
        
        prompt = build_intent_parse_prompt(
            pc_name="主角",
            inventory_snapshot="火把",
            entity_glossary=entity_glossary,
            recent_context="你独自在房间里",
        )
        
        # 验证 prompt 结构完整
        self.assertIn("detected_ability", prompt)


if __name__ == "__main__":
    unittest.main()
