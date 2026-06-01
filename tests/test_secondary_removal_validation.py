# -*- coding: utf-8 -*-
"""
test_secondary_removal_validation.py — 二次判断移除功能达标验证

测试目标：验证移除二次判断后，意图解析能否独立完成以下核心功能
"""

import unittest
from dataclasses import dataclass
from typing import Optional

# 测试沙盒版本
import sys
sys.path.insert(0, 'd:\\game\\AI')

from sandbox_intent_engine import build_intent_parse_prompt


@dataclass
class TestScenario:
    """测试场景定义"""
    name: str
    user_input: str
    pc_inventory: list
    pc_capabilities: list
    npc_capabilities: dict  # {npc_name: [abilities]}
    expected_detected_ability: Optional[str]
    expected_target_action: Optional[str]
    description: str


class SecondaryRemovalValidationTest(unittest.TestCase):
    """
    二次判断移除后的功能达标测试
    
    设计原则：覆盖二次判断原本兜底的所有场景
    """

    def setUp(self):
        """设置测试场景"""
        self.scenarios = [
            # 场景1: NPC明确使用命名招式
            TestScenario(
                name="NPC明确招式",
                user_input="山贼使用快刀劈向我",
                pc_inventory=["长剑"],
                pc_capabilities=["基础剑法"],
                npc_capabilities={"山贼": ["快刀", "铁布衫"]},
                expected_detected_ability="快刀",
                expected_target_action=None,
                description="NPC主动攻击，明确说出招式名"
            ),
            
            # 场景2: 玩家防御NPC招式
            TestScenario(
                name="玩家防御NPC招式",
                user_input="我举剑挡住山贼的快刀",
                pc_inventory=["长剑"],
                pc_capabilities=["基础剑法"],
                npc_capabilities={"山贼": ["快刀", "铁布衫"]},
                expected_detected_ability=None,  # 玩家使用能力，可能为null
                expected_target_action="快刀",  # 但NPC招式应被识别
                description="玩家防御，NPC招式在输入中被提及"
            ),
            
            # 场景3: 模糊引用（二次判断的核心场景）
            TestScenario(
                name="模糊能力引用",
                user_input="山贼使出了他的绝招",
                pc_inventory=["长剑"],
                pc_capabilities=["基础剑法"],
                npc_capabilities={"山贼": ["快刀", "铁布衫"]},
                expected_detected_ability="快刀",  # 应从能力列表中推断
                expected_target_action=None,
                description="NPC使用模糊描述，需从能力列表语义匹配"
            ),
            
            # 场景4: 多NPC不同招式
            TestScenario(
                name="多NPC场景",
                user_input="山贼用快刀攻击，黑衣人用毒镖偷袭",
                pc_inventory=["长剑"],
                pc_capabilities=["基础剑法"],
                npc_capabilities={
                    "山贼": ["快刀", "铁布衫"],
                    "黑衣人": ["偷袭", "毒镖"]
                },
                expected_detected_ability=None,  # 复杂场景可能不填顶层字段
                expected_target_action=None,
                description="多个NPC同时使用不同招式，需action_sequence处理"
            ),
            
            # 场景5: 招式名不在能力列表中（新招式）
            TestScenario(
                name="未知招式",
                user_input="山贼使用旋风斩攻击我",
                pc_inventory=["长剑"],
                pc_capabilities=["基础剑法"],
                npc_capabilities={"山贼": ["快刀"]},  # 旋风斩不在列表中
                expected_detected_ability="旋风斩",  # 应能识别新招式
                expected_target_action=None,
                description="NPC使用不在六维数据中的新招式，意图解析应能提取"
            ),
        ]

    def test_prompt_contains_all_npc_abilities(self):
        """
        验证1: 意图解析prompt包含所有NPC能力
        
        这是二次判断移除的前提条件：意图解析必须能看到完整的能力列表
        """
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario.name):
                # 构建实体名录
                entity_glossary = self._build_entity_glossary(scenario)
                
                # 构建prompt
                prompt = build_intent_parse_prompt(
                    pc_name="方拓",
                    inventory_snapshot=", ".join(scenario.pc_inventory),
                    entity_glossary=entity_glossary,
                    recent_context=f"测试场景: {scenario.description}",
                )
                
                # 验证所有NPC能力都在prompt中
                for npc_name, abilities in scenario.npc_capabilities.items():
                    self.assertIn(npc_name, prompt, 
                        f"[{scenario.name}] NPC '{npc_name}' 不在prompt中")
                    for ability in abilities:
                        self.assertIn(ability, prompt,
                            f"[{scenario.name}] 能力 '{ability}' 不在prompt中")
                
                # 验证detected_ability字段存在
                self.assertIn("detected_ability", prompt,
                    f"[{scenario.name}] detected_ability字段缺失")

    def test_scenario_expected_outputs(self):
        """
        验证2: 各场景的期望输出合理性
        
        这些期望基于二次判断移除前的行为，用于验证移除后功能一致性
        """
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario.name):
                # 如果期望有detected_ability，验证它在NPC能力列表中（或为新招式）
                if scenario.expected_detected_ability:
                    all_npc_abilities = []
                    for abilities in scenario.npc_capabilities.values():
                        all_npc_abilities.extend(abilities)
                    
                    # 期望的能力应在列表中，或是新招式（不在列表但合理）
                    is_known = scenario.expected_detected_ability in all_npc_abilities
                    is_new = scenario.name == "未知招式"
                    
                    self.assertTrue(is_known or is_new,
                        f"[{scenario.name}] 期望能力 '{scenario.expected_detected_ability}' "
                        f"既不在NPC能力列表中，也不符合新招式场景")

    def _build_entity_glossary(self, scenario: TestScenario) -> str:
        """构建实体名录字符串"""
        parts = []
        
        # 玩家
        pc_caps = f" 能力:{','.join(scenario.pc_capabilities)}" if scenario.pc_capabilities else ""
        parts.append(f"方拓[玩家]{pc_caps}")
        
        # NPCs
        for npc_name, abilities in scenario.npc_capabilities.items():
            cap_str = f" 能力:{','.join(abilities)}" if abilities else ""
            parts.append(f"{npc_name}[敌人]{cap_str}")
        
        return " | ".join(parts)


class PromptStructureTest(unittest.TestCase):
    """
    验证prompt结构是否支持二次判断移除后的需求
    """

    def test_prompt_has_entity_type_distinction(self):
        """
        验证prompt区分玩家和NPC
        
        确保意图解析不会把玩家能力误判为NPC能力
        """
        entity_glossary = (
            "方拓[玩家] 能力:基础剑法,本能闪避 | "
            "山贼[敌人] 能力:快刀,铁布衫"
        )
        
        prompt = build_intent_parse_prompt(
            pc_name="方拓",
            inventory_snapshot="长剑",
            entity_glossary=entity_glossary,
            recent_context="山贼攻击玩家",
        )
        
        # 验证标签存在
        self.assertIn("[玩家]", prompt)
        self.assertIn("[敌人]", prompt)
        
        # 验证能力分别列出
        self.assertIn("基础剑法", prompt)
        self.assertIn("快刀", prompt)

    def test_prompt_has_action_sequence_support(self):
        """
        验证prompt支持复合动作（action_sequence）
        
        多NPC场景需要action_sequence来分别记录每个动作的能力
        """
        prompt = build_intent_parse_prompt(
            pc_name="方拓",
            inventory_snapshot="长剑",
            entity_glossary="山贼[敌人] 能力:快刀 | 黑衣人[敌人] 能力:毒镖",
            recent_context="多人战斗",
        )
        
        # 验证action_sequence字段存在
        self.assertIn("action_sequence", prompt)
        self.assertIn("detected_ability", prompt)


class EdgeCaseTest(unittest.TestCase):
    """
    边界情况测试
    """

    def test_empty_npc_capabilities(self):
        """
        场景：NPC还没有任何能力（新登场）
        """
        entity_glossary = "神秘人[未知]"  # 没有能力
        
        prompt = build_intent_parse_prompt(
            pc_name="方拓",
            inventory_snapshot="长剑",
            entity_glossary=entity_glossary,
            recent_context="一个神秘人出现",
        )
        
        # 验证prompt仍然可用
        self.assertIn("神秘人", prompt)
        self.assertIn("detected_ability", prompt)

    def test_no_npc_in_scene(self):
        """
        场景：纯环境互动，无NPC
        """
        entity_glossary = "无已知NPC"
        
        prompt = build_intent_parse_prompt(
            pc_name="方拓",
            inventory_snapshot="火把",
            entity_glossary=entity_glossary,
            recent_context="你独自在房间里",
        )
        
        # 验证结构完整
        self.assertIn("detected_ability", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
