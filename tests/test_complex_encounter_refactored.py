"""
复杂对抗环境测试 - 业界规范版本

================================================================================
🔔 AI 助手维护提醒（每次修改前必读）
================================================================================

1. 测试命名规范
   - 格式: test_{{given}}_when_{{condition}}_should_{{expected}}
   - 示例: test_given_scene_plausible_false_when_validate_should_block_action

2. 代码结构规范（AAA 模式）
   - Arrange: 准备测试数据，使用固件方法
   - Act: 执行被测操作
   - Assert: 断言结果，提供描述性失败消息

3. 固件复用
   - 使用基类 ComplexEncounterTestBase 提供通用固件
   - 新增固件方法以 make_ 开头

4. 测试组织
   - 按功能领域分组（TestBasicCompositeActionFlow, TestItemConstraintValidation 等）
   - 每个测试类顶部写 Given-When-Then 场景描述

5. 新增测试步骤
   - [1] 确定测试场景和预期结果
   - [2] 选择合适的测试类或创建新类
   - [3] 使用基类固件或创建新固件
   - [4] 按 AAA 模式编写测试
   - [5] 运行测试确保通过: python -m unittest tests.test_complex_encounter_refactored -v

================================================================================
"""

import unittest
from typing import Any
from dataclasses import dataclass

from rules.complex_encounter import ComplexEncounterResolver


# ============================================================================
# 测试固件（Fixtures）
# ============================================================================

@dataclass
class FakeAdjudicatorRequest:
    """原子裁判请求的记录对象"""
    action_id: str
    action_type: str
    initiator_assets: dict
    major_graph: dict


class FakeAtomicAdjudicator:
    """用于测试的原子裁判器替身（Spy）"""
    backend_id = "fake_v1"

    def __init__(self):
        self.requests: list[FakeAdjudicatorRequest] = []

    def resolve(self, request) -> Any:
        """记录请求并返回预设的成功结果"""
        self.requests.append(FakeAdjudicatorRequest(
            action_id=request.action_id,
            action_type=request.action_type,
            initiator_assets=request.initiator_assets,
            major_graph=request.major_graph,
        ))
        return type("FakeResult", (), {
            "action_id": request.action_id,
            "numeric_result": "success",
            "tier": "测试成功",
            "system_injection": f"[TEST] {request.action_id}",
            "backend_id": self.backend_id,
            "debug": {},
        })()


class NeverCalledAdjudicator:
    """用于验证不应调用原子裁判的场景"""
    backend_id = "never_called"

    def resolve(self, request) -> Any:
        raise AssertionError(
            f"不应调用原子裁判器，但收到了请求: {request.action_id}"
        )


# ============================================================================
# 测试基类
# ============================================================================

class ComplexEncounterTestBase(unittest.TestCase):
    """复杂对抗测试基类，提供通用固件"""

    def make_pc_entity(self, name: str = "柯酥卤") -> dict:
        """创建玩家角色实体"""
        return {
            "3_capabilities": {
                "基础行动": {"base_power": 10, "mastery_level": 1.0, "domains": ["通用"]}
            },
            "2_dynamic_status": {
                "physical": {"desc": "健康", "multiplier": 1.0},
                "mental": {"desc": "平静", "multiplier": 1.0},
            },
            "4_experience_factors": {"general_combat": 1.0, "specific_match": {}},
            "5_traits": [],
            "6_inventory": {"短剑": {"tags": ["武器"], "multiplier": 1.0}},
        }

    def make_npc_entity(self, name: str = "山贼") -> dict:
        """创建 NPC 实体"""
        return {
            "3_capabilities": {
                "格挡": {"base_power": 8, "mastery_level": 1.0, "domains": ["防御"]}
            },
            "2_dynamic_status": {
                "physical": {"desc": "健康", "multiplier": 1.0},
                "mental": {"desc": "平静", "multiplier": 1.0},
            },
            "4_experience_factors": {"general_combat": 1.0, "specific_match": {}},
            "5_traits": [],
            "6_inventory": {},
        }

    def make_graph(self) -> dict:
        """创建测试用的图谱"""
        return {
            "entities": {
                "柯酥卤": self.make_pc_entity(),
                "山贼": self.make_npc_entity(),
            },
            "relations": [],
        }

    def make_pickup_torch_action(self) -> dict:
        """创建"拾取火把"动作"""
        return {
            "action_id": "pickup_torch",
            "actor": "柯酥卤",
            "target": "墙上的火把",
            "action_type": "skill",
            "intended_action": "从墙上拔下燃烧的火把",
            "is_risk": False,
            "temporary_items": {
                "火把": {
                    "tags": ["燃烧", "照明"],
                    "persistence": "ephemeral",
                }
            },
            "narrative_weight": "LOW",
        }

    def make_attack_with_torch_action(self) -> dict:
        """创建"用火把攻击"动作"""
        return {
            "action_id": "attack_with_torch",
            "actor": "柯酥卤",
            "target": "山贼",
            "action_type": "combat",
            "intended_action": "用燃烧的火把逼退山贼",
            "depends_on": ["pickup_torch"],
            "required_items": {"火把": 1},
            "narrative_weight": "HIGH",
        }


# ============================================================================
# 测试类：基础复合动作流程
# ============================================================================

class TestBasicCompositeActionFlow(ComplexEncounterTestBase):
    """
    测试基础复合动作流程

    Given: 玩家执行复合动作（拾取物品 -> 使用物品攻击）
    When: 复合对抗解析器处理动作序列
    Then: 应正确流转临时物品并调用原子裁判
    """

    def test_given_temporary_item_acquired_when_used_in_later_action_should_be_visible_to_adjudicator(self):
        """
        测试临时物品在后续动作中对原子裁判可见

        Arrange:
            - 玩家先拾取火把（临时物品）
            - 然后用火把攻击山贼
        Act:
            - 执行复合对抗解析
        Assert:
            - 原子裁判应能看到火把在玩家资产中
        """
        # Arrange
        fake_adjudicator = FakeAtomicAdjudicator()
        resolver = ComplexEncounterResolver(adjudicator=fake_adjudicator)
        graph = self.make_graph()
        actions = [
            self.make_pickup_torch_action(),
            self.make_attack_with_torch_action(),
        ]

        # Act
        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        # Assert
        self.assertEqual(
            len(fake_adjudicator.requests), 1,
            "应只调用一次原子裁判（拾取动作为 setup，不调用裁判）"
        )

        request = fake_adjudicator.requests[0]
        self.assertIn(
            "火把", request.initiator_assets,
            "原子裁判应能看到火把在玩家资产中"
        )
        self.assertIn(
            "火把", request.major_graph["entities"]["柯酥卤"]["6_inventory"],
            "临时物品应被注入虚拟背包"
        )

    def test_given_setup_action_when_no_risk_should_skip_adjudicator_and_succeed(self):
        """
        测试低风险准备动作应跳过原子裁判直接成功

        Arrange:
            - 拾取火把动作标记为 is_risk=False
        Act:
            - 执行复合对抗解析
        Assert:
            - 不应调用原子裁判
            - 动作结果应为 success
        """
        # Arrange
        resolver = ComplexEncounterResolver(adjudicator=NeverCalledAdjudicator())
        graph = self.make_graph()
        actions = [self.make_pickup_torch_action()]

        # Act
        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        # Assert
        action_result = result["action_results"]["pickup_torch"]
        self.assertEqual(
            action_result["numeric_result"], "success",
            "低风险准备动作应直接成功"
        )
        self.assertEqual(
            action_result["adjudicator_backend"], "setup_gate",
            "应标记为 setup_gate 而非真实裁判器"
        )


# ============================================================================
# 测试类：物品约束校验
# ============================================================================

class TestItemConstraintValidation(ComplexEncounterTestBase):
    """
    测试物品六维度约束校验

    Given: 动作包含 temporary_items
    When: 约束校验不通过
    Then: 应拒绝动作并返回约束失败标记
    """

    def test_given_scene_plausible_false_when_validate_should_block_action(self):
        """
        测试 scene_plausible=false 时应阻止动作

        Arrange:
            - 手雷在当前武侠场景中不合理
        Act:
            - 执行约束校验
        Assert:
            - 动作应被标记为约束失败
        """
        # Arrange
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [{
            "action_id": "pickup_grenade",
            "actor": "柯酥卤",
            "target": "手雷",
            "action_type": "skill",
            "intended_action": "捡起手雷",
            "temporary_items": {
                "手雷": {
                    "tags": ["爆炸物"],
                    "persistence": "ephemeral",
                    "constraints": {
                        "scene_plausible": False,
                        "obtainable": False,
                        "ownership_clear": True,
                        "prerequisites_met": True,
                        "safe_to_use": False,
                        "world_compatible": False,
                    }
                }
            },
            "narrative_weight": "HIGH",
        }]

        # Act
        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        # Assert
        action_result = result["action_results"]["pickup_grenade"]
        self.assertTrue(
            action_result.get("constraint_violation", False),
            "约束失败的动作应标记 constraint_violation"
        )
        self.assertEqual(
            action_result["numeric_result"], "failure",
            "约束失败的动作结果应为 failure"
        )


# ============================================================================
# 测试类：动作依赖链
# ============================================================================

class TestActionDependencyChain(ComplexEncounterTestBase):
    """
    测试动作依赖链

    Given: 动作 A 依赖于动作 B
    When: 动作 B 失败
    Then: 动作 A 应被跳过
    """

    def test_given_prerequisite_fails_when_dependent_action_should_be_skipped(self):
        """
        测试前置动作失败时，依赖动作应被跳过

        Arrange:
            - a1: 拾取火把（约束失败）
            - a2: 用火把攻击（依赖于 a1）
        Act:
            - 执行复合对抗解析
        Assert:
            - a1 应失败
            - a2 应被跳过
        """
        # Arrange
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "不存在的手雷",
                "action_type": "skill",
                "intended_action": "捡起手雷",
                "temporary_items": {
                    "手雷": {
                        "tags": ["爆炸物"],
                        "constraints": {"scene_plausible": False, "obtainable": False},
                    }
                },
                "narrative_weight": "HIGH",
            },
            {
                "action_id": "a2",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "intended_action": "扔手雷",
                "depends_on": ["a1"],
                "required_items": {"手雷": 1},
                "narrative_weight": "CRITICAL",
            },
        ]

        # Act
        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        # Assert
        self.assertEqual(
            result["action_results"]["a1"]["numeric_result"], "failure",
            "前置动作应失败"
        )
        self.assertTrue(
            result["action_results"]["a2"].get("skipped_by_cascade", False),
            "依赖动作应被标记为跳过"
        )


# ============================================================================
# 测试类：物品流转与状态补丁
# ============================================================================

class TestItemFlowAndStatePatch(ComplexEncounterTestBase):
    """
    测试物品流转与状态补丁生成

    Given: 复合动作涉及物品获得/消耗
    When: 解析完成
    Then: 应生成正确的 state_patch
    """

    def test_given_ephemeral_temporary_item_when_resolved_should_not_enter_inventory(self):
        """
        测试临时 ephemeral 物品不应进入最终背包

        Arrange:
            - 拾取火把（ephemeral）
            - 使用火把攻击
        Act:
            - 执行解析
        Assert:
            - 火把不应出现在 inventory_changes.add 中
        """
        # Arrange
        fake = FakeAtomicAdjudicator()
        resolver = ComplexEncounterResolver(adjudicator=fake)
        graph = self.make_graph()
        actions = [
            self.make_pickup_torch_action(),
            self.make_attack_with_torch_action(),
        ]

        # Act
        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        # Assert
        inventory_adds = result["state_patch"]["inventory_changes"]["add"]
        self.assertNotIn(
            "火把", inventory_adds,
            "ephemeral 临时物品不应进入最终背包"
        )

    def test_given_persistent_reward_when_resolved_should_enter_inventory(self):
        """
        测试 persistent 奖励物品应进入最终背包

        Arrange:
            - 击败山贼获得长刀（persistent）
        Act:
            - 执行解析
        Assert:
            - 长刀应出现在 inventory_changes.add 中
        """
        # Arrange
        fake = FakeAtomicAdjudicator()
        resolver = ComplexEncounterResolver(adjudicator=fake)
        graph = self.make_graph()
        actions = [{
            "action_id": "loot_sword",
            "actor": "柯酥卤",
            "target": "山贼",
            "action_type": "combat",
            "intended_action": "夺取山贼的长刀",
            "reward_items": {
                "长刀": {
                    "tags": ["武器", "锋利"],
                    "persistence": "persistent",
                    "multiplier": 1.2,
                }
            },
            "narrative_weight": "HIGH",
        }]

        # Act
        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        # Assert
        inventory_adds = result["state_patch"]["inventory_changes"]["add"]
        self.assertIn(
            "长刀", inventory_adds,
            "persistent 奖励物品应进入最终背包"
        )
        self.assertEqual(
            inventory_adds["长刀"]["multiplier"], 1.2,
            "奖励物品属性应被保留"
        )


# ============================================================================
# 测试类：约束失败全阻断
# ============================================================================

class TestAllActionsConstraintFailed(ComplexEncounterTestBase):
    """
    测试所有子动作约束失败场景

    Given: 所有执行的子动作都因约束失败
    When: 解析完成
    Then: 应返回 all_actions_constraint_failed 标记
    """

    def test_given_all_actions_constraint_fail_when_resolve_should_return_all_failed_flag(self):
        """
        测试所有动作约束失败时应返回全失败标记

        Arrange:
            - 拾取手雷（约束失败）
            - 扔向令狐冲（依赖于前者，被跳过）
        Act:
            - 执行解析
        Assert:
            - 应返回 all_actions_constraint_failed=True
        """
        # Arrange
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "pickup_grenade",
                "actor": "柯酥卤",
                "target": "手雷",
                "action_type": "skill",
                "intended_action": "捡起手雷",
                "temporary_items": {
                    "手雷": {
                        "tags": ["爆炸物"],
                        "constraints": {"scene_plausible": False, "obtainable": False},
                    }
                },
                "narrative_weight": "HIGH",
            },
            {
                "action_id": "throw_grenade",
                "actor": "柯酥卤",
                "target": "令狐冲",
                "action_type": "combat",
                "intended_action": "扔向令狐冲",
                "depends_on": ["pickup_grenade"],
                "required_items": {"手雷": 1},
                "narrative_weight": "CRITICAL",
            },
        ]

        # Act
        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        # Assert
        self.assertTrue(
            result.get("all_actions_constraint_failed", False),
            "所有动作约束失败时应返回 all_actions_constraint_failed=True"
        )


if __name__ == "__main__":
    unittest.main()
