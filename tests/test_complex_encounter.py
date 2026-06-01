import unittest

from rules.complex_encounter import ComplexEncounterResolver


class FakeAtomicAdjudicator:
    backend_id = "fake_v1"

    def __init__(self):
        self.requests = []

    def resolve(self, request):
        self.requests.append(request)
        return type("FakeAtomicActionResult", (), {
            "action_id": request.action_id,
            "numeric_result": "success",
            "tier": "测试成功",
            "system_injection": f"原裁判注入:{request.action_id}:{request.action_type}",
            "backend_id": self.backend_id,
            "debug": {"backend_id": self.backend_id},
        })()


class InspectingAtomicAdjudicator:
    backend_id = "inspect_v1"

    def __init__(self):
        self.requests = []

    def resolve(self, request):
        self.requests.append(request)
        return type("InspectingAtomicActionResult", (), {
            "action_id": request.action_id,
            "numeric_result": "success",
            "tier": "测试成功",
            "system_injection": "检查裁判注入",
            "backend_id": self.backend_id,
            "debug": {"backend_id": self.backend_id},
        })()


class FailingIfCalledAdjudicator:
    backend_id = "should_not_call"

    def resolve(self, request):
        raise AssertionError("setup action should not call atomic adjudicator")


class ComplexEncounterResolverTest(unittest.TestCase):
    def make_graph(self):
        return {
            "entities": {
                "柯酥卤": {
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
                },
                "山贼": {
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
                },
            },
            "relations": [],
        }

    def test_resolver_uses_injected_atomic_adjudicator_for_sub_actions(self):
        fake = FakeAtomicAdjudicator()
        resolver = ComplexEncounterResolver(adjudicator=fake)
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "intended_action": "挥拳击退山贼",
                "narrative_weight": "HIGH",
            }
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(fake.requests[0].action_type, "combat")
        self.assertEqual(result["action_results"]["a1"]["numeric_result"], "success")
        self.assertIn("原裁判注入:a1:combat", result["system_injection"])

    def test_setup_action_does_not_call_adjudicator_and_adds_temporary_item(self):
        resolver = ComplexEncounterResolver(adjudicator=FailingIfCalledAdjudicator())
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "燃烧的火把",
                "action_type": "skill",
                "intended_action": "从墙上拔下燃烧的火把",
                "is_risk": False,
                "temporary_items": {"燃烧的火把": {"tags": ["照明", "燃烧"], "persistence": "ephemeral"}},
                "narrative_weight": "HIGH",
            },
            {
                "action_id": "a2",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "intended_action": "用燃烧火把逼退山贼",
                "numeric_result": "success",
                "depends_on": ["a1"],
                "required_items": {"燃烧的火把": 1},
                "narrative_weight": "CRITICAL",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertEqual(result["action_results"]["a1"]["numeric_result"], "success")
        self.assertEqual(result["action_results"]["a1"]["adjudicator_backend"], "setup_gate")
        self.assertEqual(result["action_results"]["a2"]["numeric_result"], "success")
        self.assertNotIn("燃烧的火把", result["state_patch"]["inventory_changes"]["add"])

    def test_required_items_are_visible_to_atomic_adjudicator(self):
        inspector = InspectingAtomicAdjudicator()
        resolver = ComplexEncounterResolver(adjudicator=inspector)
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "燃烧的火把",
                "action_type": "skill",
                "intended_action": "从墙上拔下一支燃烧的火把",
                "is_risk": False,
                "temporary_items": {"火把": {"tags": ["燃烧", "威慑"], "persistence": "ephemeral"}},
                "narrative_weight": "LOW",
            },
            {
                "action_id": "a2",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "intended_action": "用火把逼退山贼",
                "depends_on": ["a1"],
                "required_items": {"火把": 1},
                "narrative_weight": "HIGH",
            },
        ]

        resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertEqual(len(inspector.requests), 1)
        request = inspector.requests[0]
        self.assertIn("火把", request.initiator_assets)
        self.assertIn("火把", request.major_graph["entities"]["柯酥卤"]["6_inventory"])

    def test_entity_annotation_canonical_name_links_temporary_and_required_items(self):
        inspector = InspectingAtomicAdjudicator()
        resolver = ComplexEncounterResolver(adjudicator=inspector)
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "墙上的火把",
                "action_type": "skill",
                "intended_action": "从墙上拔下燃烧的火把",
                "is_risk": False,
                "temporary_items": {"墙上的火把": {"tags": ["燃烧", "照明"], "persistence": "ephemeral"}},
                "narrative_weight": "HIGH",
            },
            {
                "action_id": "a2",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "intended_action": "用火把逼退山贼",
                "depends_on": ["a1"],
                "required_items": {"火把": 1},
                "narrative_weight": "CRITICAL",
            },
        ]
        annotations = [
            {
                "name": "墙上的火把",
                "canonical_name": "火把",
                "entity_type": "object",
                "role_in_action": "temporary_tool",
                "persistence": "ephemeral",
                "should_initialize_npc": False,
            }
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界", entity_annotations=annotations)

        self.assertEqual(result["action_results"]["a2"]["numeric_result"], "success")
        request = inspector.requests[0]
        self.assertIn("火把", request.initiator_assets)
        self.assertIn("火把", request.major_graph["entities"]["柯酥卤"]["6_inventory"])
        self.assertNotIn("墙上的火把", request.major_graph["entities"]["柯酥卤"]["6_inventory"])
        self.assertNotIn("火把", result["state_patch"]["inventory_changes"]["add"])

    def test_canonicalized_persistent_reward_enters_inventory_under_canonical_key(self):
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "skill",
                "intended_action": "夺下山贼手里的长刀并带走",
                "numeric_result": "success",
                "reward_items": {"山贼手里的长刀": {"tags": ["武器", "刀"], "persistence": "persistent"}},
                "narrative_weight": "HIGH",
            }
        ]
        annotations = [
            {
                "name": "山贼手里的长刀",
                "canonical_name": "长刀",
                "entity_type": "object",
                "role_in_action": "loot",
                "persistence": "persistent",
                "should_initialize_npc": False,
            }
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界", entity_annotations=annotations)

        self.assertIn("长刀", result["state_patch"]["inventory_changes"]["add"])
        self.assertNotIn("山贼手里的长刀", result["state_patch"]["inventory_changes"]["add"])

    def test_successful_temporary_item_becomes_held_item_not_inventory(self):
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "火把",
                "action_type": "skill",
                "intended_action": "从墙上拔下燃烧的火把",
                "is_risk": False,
                "temporary_items": {"火把": {"tags": ["燃烧", "照明", "威慑"], "persistence": "ephemeral"}},
                "narrative_weight": "HIGH",
            },
            {
                "action_id": "a2",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "intended_action": "用火把逼退山贼",
                "numeric_result": "failure",
                "depends_on": ["a1"],
                "required_items": {"火把": 1},
                "narrative_weight": "CRITICAL",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertIn("火把", result["state_patch"]["held_item_changes"]["add"])
        self.assertNotIn("火把", result["state_patch"]["inventory_changes"]["add"])

    def test_consumed_temporary_item_does_not_become_held_item(self):
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "石头",
                "action_type": "skill",
                "intended_action": "捡起石头",
                "is_risk": False,
                "temporary_items": {"石头": {"tags": ["投掷物"], "persistence": "ephemeral"}},
                "narrative_weight": "LOW",
            },
            {
                "action_id": "a2",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "intended_action": "把石头砸向山贼",
                "numeric_result": "success",
                "depends_on": ["a1"],
                "required_items": {"石头": 1},
                "consumed_items": {"石头": 1},
                "narrative_weight": "HIGH",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        # 石头被消耗了，不应该在手持物里
        self.assertNotIn("石头", result["state_patch"]["held_item_changes"]["add"])
        # 石头从未正式加入手持物，所以也不在 remove 里
        self.assertNotIn("石头", result["state_patch"]["held_item_changes"]["remove"])

    def test_existing_held_item_is_visible_to_atomic_adjudicator(self):
        inspector = InspectingAtomicAdjudicator()
        resolver = ComplexEncounterResolver(adjudicator=inspector)
        graph = self.make_graph()
        graph["entities"]["柯酥卤"]["7_held_items"] = {
            "火把": {"tags": ["燃烧", "照明"], "persistence": "ephemeral"}
        }
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "intended_action": "继续用火把逼退山贼",
                "required_items": {"火把": 1},
                "narrative_weight": "HIGH",
            }
        ]

        resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        request = inspector.requests[0]
        self.assertIn("火把", request.initiator_assets)
        self.assertIn("火把", request.major_graph["entities"]["柯酥卤"]["6_inventory"])

    def test_reward_item_can_be_consumed_by_later_action(self):
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "skill",
                "intended_action": "夺取火把",
                "numeric_result": "success",
                "reward_items": {"火把": {"tags": ["照明", "燃烧"], "multiplier": 0.8}},
                "narrative_weight": "HIGH",
            },
            {
                "action_id": "a2",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "intended_action": "用火把逼退山贼",
                "numeric_result": "success",
                "cost_items": {"火把": 1},
                "depends_on": ["a1"],
                "narrative_weight": "HIGH",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertEqual(result["action_results"]["a1"]["numeric_result"], "success")
        self.assertEqual(result["action_results"]["a2"]["numeric_result"], "success")
        self.assertNotIn("火把", result["state_patch"]["inventory_changes"]["add"])
        self.assertNotIn("火把", result["state_patch"]["inventory_changes"]["remove"])

    def test_reward_item_remains_when_not_consumed(self):
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "skill",
                "intended_action": "夺取火把",
                "numeric_result": "success",
                "reward_items": {"火把": {"tags": ["照明", "燃烧"], "multiplier": 0.8}},
                "narrative_weight": "HIGH",
            }
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertIn("火把", result["state_patch"]["inventory_changes"]["add"])
        self.assertNotIn("火把", result["state_patch"]["inventory_changes"]["remove"])

    def test_same_action_reward_can_satisfy_same_action_cost(self):
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "intended_action": "拔下火把并立刻逼退山贼",
                "numeric_result": "success",
                "reward_items": {"火把": {"tags": ["照明", "燃烧"], "multiplier": 0.8}},
                "cost_items": {"火把": 1},
                "narrative_weight": "HIGH",
            }
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertEqual(result["action_results"]["a1"]["numeric_result"], "success")
        self.assertNotIn("火把", result["state_patch"]["inventory_changes"]["add"])
        self.assertNotIn("火把", result["state_patch"]["inventory_changes"]["remove"])

    def test_temporary_item_can_be_used_without_entering_inventory(self):
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "intended_action": "拔下墙上的火把并逼退山贼",
                "numeric_result": "success",
                "temporary_items": {"墙上的火把": {"tags": ["燃烧", "照明"], "persistence": "ephemeral"}},
                "cost_items": {"墙上的火把": 1},
                "narrative_weight": "HIGH",
            }
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertEqual(result["action_results"]["a1"]["numeric_result"], "success")
        self.assertEqual(result["state_patch"]["inventory_changes"]["add"], {})
        self.assertEqual(result["state_patch"]["inventory_changes"]["remove"], [])

    def test_ephemeral_reward_does_not_enter_inventory(self):
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "skill",
                "intended_action": "临时抓起燃烧的木棒",
                "numeric_result": "success",
                "reward_items": {"燃烧的木棒": {"tags": ["燃烧"], "persistence": "ephemeral"}},
                "narrative_weight": "HIGH",
            }
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertNotIn("燃烧的木棒", result["state_patch"]["inventory_changes"]["add"])

    def test_persistent_reward_enters_inventory(self):
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "skill",
                "intended_action": "把火把拿在手里继续前进",
                "numeric_result": "success",
                "reward_items": {"火把": {"tags": ["照明"], "persistence": "persistent"}},
                "narrative_weight": "HIGH",
            }
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertIn("火把", result["state_patch"]["inventory_changes"]["add"])

    def test_ephemeral_reward_is_available_to_later_required_item_but_not_final_inventory(self):
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "intended_action": "夺下山贼的长刀",
                "numeric_result": "success",
                "temporary_items": {"长刀": {"tags": ["武器", "刀"], "persistence": "ephemeral"}},
                "narrative_weight": "HIGH",
            },
            {
                "action_id": "a2",
                "actor": "柯酥卤",
                "target": "山贼",
                "target_part": "手腕",
                "action_type": "combat",
                "intended_action": "用长刀反砍山贼手腕",
                "numeric_result": "success",
                "depends_on": ["a1"],
                "required_items": {"长刀": 1},
                "narrative_weight": "CRITICAL",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertEqual(result["action_results"]["a2"]["numeric_result"], "success")
        self.assertEqual(result["action_results"]["a2"]["target_part"], "手腕")
        self.assertNotIn("长刀", result["state_patch"]["inventory_changes"]["add"])

    def test_required_items_do_not_consume_inventory_but_consumed_items_do(self):
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "intended_action": "用短剑攻击",
                "numeric_result": "success",
                "required_items": {"短剑": 1},
                "narrative_weight": "HIGH",
            },
            {
                "action_id": "a2",
                "actor": "柯酥卤",
                "target": "环境",
                "action_type": "skill",
                "intended_action": "把短剑丢入深井",
                "numeric_result": "success",
                "depends_on": ["a1"],
                "consumed_items": {"短剑": 1},
                "narrative_weight": "HIGH",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertEqual(result["action_results"]["a1"]["numeric_result"], "success")
        self.assertEqual(result["action_results"]["a2"]["numeric_result"], "success")
        self.assertIn("短剑", result["state_patch"]["inventory_changes"]["remove"])

    def test_failed_dependency_skips_later_action(self):
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "skill",
                "intended_action": "抢夺短剑",
                "numeric_result": "critical_failure",
                "narrative_weight": "HIGH",
            },
            {
                "action_id": "a2",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "intended_action": "用短剑反击",
                "numeric_result": "success",
                "depends_on": ["a1"],
                "narrative_weight": "HIGH",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertEqual(result["action_results"]["a2"]["numeric_result"], "failure")
        self.assertTrue(result["action_results"]["a2"].get("skipped_by_cascade"))
        self.assertIn("前置动作失败", result["system_injection"])

    def test_thrown_item_consumed_on_failure(self):
        """投掷物失败时也应消耗（离开玩家控制）"""
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "石头",
                "action_type": "skill",
                "intended_action": "捡起石头",
                "is_risk": False,
                "temporary_items": {"石头": {"tags": ["投掷", "钝器"], "persistence": "ephemeral"}},
                "narrative_weight": "LOW",
            },
            {
                "action_id": "a2",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "action_label": "ranged_attack",
                "intended_action": "扔石头砸山贼",
                "numeric_result": "failure",  # 失败
                "depends_on": ["a1"],
                "required_items": {"石头": 1},
                "consumed_items": {"石头": 1},
                "narrative_weight": "HIGH",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        # 石头应该不在 add 里（被扔出去了，不加入手持物）
        self.assertNotIn("石头", result["state_patch"]["held_item_changes"]["add"])

    def test_item_constraint_scene_plausible_blocks_action(self):
        """scene_plausible: false 时动作应被拒绝"""
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "手雷",
                "action_type": "skill",
                "intended_action": "捡起手雷",
                "is_risk": False,
                "temporary_items": {
                    "手雷": {
                        "tags": ["爆炸物"],
                        "persistence": "ephemeral",
                        "constraints": {
                            "scene_plausible": False,
                            "obtainable": True,
                            "ownership_clear": True,
                            "prerequisites_met": True,
                            "safe_to_use": True,
                            "world_compatible": False,
                            "reason": "武侠世界荒野中不可能出现手雷"
                        }
                    }
                },
                "narrative_weight": "LOW",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        # 动作应因约束未通过而失败
        self.assertEqual(result["action_results"]["a1"]["numeric_result"], "failure")
        self.assertIn("约束未通过", result["action_results"]["a1"]["scene_note"])
        self.assertIn("手雷", result["action_results"]["a1"]["scene_note"])

    def test_item_constraint_obtainable_blocks_action(self):
        """obtainable: false 时动作应被拒绝"""
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "大象",
                "action_type": "skill",
                "intended_action": "捡起大象",
                "is_risk": False,
                "temporary_items": {
                    "大象": {
                        "tags": ["生物", "巨型"],
                        "persistence": "ephemeral",
                        "constraints": {
                            "scene_plausible": True,
                            "obtainable": False,
                            "ownership_clear": True,
                            "prerequisites_met": True,
                            "safe_to_use": True,
                            "world_compatible": True,
                            "reason": "大象太重，无法捡起"
                        }
                    }
                },
                "narrative_weight": "LOW",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        # 动作应因约束未通过而失败
        self.assertEqual(result["action_results"]["a1"]["numeric_result"], "failure")
        self.assertIn("约束未通过", result["action_results"]["a1"]["scene_note"])

    def test_item_all_constraints_pass_action_succeeds(self):
        """所有约束通过时动作应正常执行"""
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "石头",
                "action_type": "skill",
                "intended_action": "捡起石头",
                "is_risk": False,
                "temporary_items": {
                    "石头": {
                        "tags": ["投掷"],
                        "persistence": "ephemeral",
                        "constraints": {
                            "scene_plausible": True,
                            "obtainable": True,
                            "ownership_clear": True,
                            "prerequisites_met": True,
                            "safe_to_use": True,
                            "world_compatible": True,
                        }
                    }
                },
                "narrative_weight": "LOW",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        # 动作应成功
        self.assertEqual(result["action_results"]["a1"]["numeric_result"], "success")

    def test_weapon_not_consumed_on_failure(self):
        """武器失败时不应消耗（仍在玩家控制）"""
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "长刀",
                "action_type": "skill",
                "intended_action": "拔出长刀",
                "is_risk": False,
                "temporary_items": {"长刀": {"tags": ["武器", "刀"], "persistence": "ephemeral"}},
                "narrative_weight": "LOW",
            },
            {
                "action_id": "a2",
                "actor": "柯酥卤",
                "target": "山贼",
                "action_type": "combat",
                "intended_action": "用长刀砍山贼",
                "numeric_result": "failure",  # 失败
                "depends_on": ["a1"],
                "required_items": {"长刀": 1},
                "consumed_items": {"长刀": 1},  # LLM 可能错误标记
                "narrative_weight": "HIGH",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        # 长刀不应该被消耗（因为它是武器，不是投掷物）
        self.assertNotIn("长刀", result["state_patch"]["held_item_changes"]["remove"])


    def test_action_constraint_target_exists_blocks(self):
        """target_exists: false 时动作应被拒绝"""
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "张三",
                "action_type": "social",
                "intended_action": "说服张三投降",
                "is_risk": True,
                "action_constraints": {
                    "target_exists": False,
                    "target_reachable": True,
                    "environment_supports": True,
                    "actor_capable": True,
                    "reason": "张三不在当前场景中"
                },
                "narrative_weight": "HIGH",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertEqual(result["action_results"]["a1"]["numeric_result"], "failure")
        self.assertIn("动作约束未通过", result["action_results"]["a1"]["scene_note"])

    def test_action_constraint_actor_capable_blocks(self):
        """actor_capable: false 时动作应被拒绝"""
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "铁门",
                "action_type": "skill",
                "intended_action": "徒手打碎铁门",
                "is_risk": False,
                "action_constraints": {
                    "target_exists": True,
                    "target_reachable": True,
                    "environment_supports": True,
                    "actor_capable": False,
                    "reason": "徒手无法打碎铁门，需要合适工具"
                },
                "narrative_weight": "HIGH",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertEqual(result["action_results"]["a1"]["numeric_result"], "failure")
        self.assertIn("动作约束未通过", result["action_results"]["a1"]["scene_note"])

    def test_action_all_constraints_pass_succeeds(self):
        """动作约束全部通过时应正常执行"""
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "石头",
                "action_type": "skill",
                "intended_action": "捡起石头",
                "is_risk": False,
                "action_constraints": {
                    "target_exists": True,
                    "target_reachable": True,
                    "environment_supports": True,
                    "actor_capable": True,
                },
                "temporary_items": {
                    "石头": {
                        "tags": ["投掷"],
                        "persistence": "ephemeral",
                        "constraints": {
                            "scene_plausible": True,
                            "obtainable": True,
                            "ownership_clear": True,
                            "prerequisites_met": True,
                            "safe_to_use": True,
                            "world_compatible": True,
                        }
                    }
                },
                "narrative_weight": "LOW",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        self.assertEqual(result["action_results"]["a1"]["numeric_result"], "success")

    def test_all_actions_constraint_failed_returns_flag(self):
        """所有子动作都因约束失败时，应返回 all_actions_constraint_failed=True"""
        resolver = ComplexEncounterResolver()
        graph = self.make_graph()
        actions = [
            {
                "action_id": "a1",
                "actor": "柯酥卤",
                "target": "手雷",
                "action_type": "skill",
                "intended_action": "捡起手雷",
                "is_risk": False,
                "temporary_items": {
                    "手雷": {
                        "tags": ["爆炸物"],
                        "persistence": "ephemeral",
                        "constraints": {
                            "scene_plausible": False,
                            "obtainable": False,
                            "ownership_clear": True,
                            "prerequisites_met": True,
                            "safe_to_use": True,
                            "world_compatible": False,
                            "reason": "武侠世界不存在手雷"
                        }
                    }
                },
                "narrative_weight": "LOW",
            },
            {
                "action_id": "a2",
                "actor": "柯酥卤",
                "target": "令狐冲",
                "action_type": "combat",
                "intended_action": "扔向令狐冲",
                "depends_on": ["a1"],
                "required_items": {"手雷": 1},
                "consumed_items": {"手雷": 1},
                "narrative_weight": "HIGH",
            },
        ]

        result = resolver.resolve(actions, graph, "柯酥卤", "武侠世界")

        # a1 应因约束失败
        self.assertEqual(result["action_results"]["a1"]["numeric_result"], "failure")
        self.assertTrue(result["action_results"]["a1"].get("constraint_violation"))
        # a2 应被跳过
        self.assertTrue(result["action_results"]["a2"].get("skipped_by_cascade"))
        # 所有执行的子动作都因约束失败
        self.assertTrue(result.get("all_actions_constraint_failed"))


if __name__ == "__main__":
    unittest.main()
