import unittest
from rules.adjudication_utils import calculate_conditional_buffs, safe_clamp_multiplier


class TestCalculateConditionalBuffs(unittest.TestCase):
    """测试 calculate_conditional_buffs 能否扫描 7_held_items"""

    def make_entity(self, inventory=None, held_items=None, traits=None):
        entity = {
            "6_inventory": inventory or {},
            "7_held_items": held_items or {},
            "5_traits": traits or [],
            "1_relational_facts": {},
        }
        return entity

    # ── 测试 1: 背包物品仍正常生效 ──
    def test_inventory_item_with_matching_tag_applies_multiplier(self):
        entity = self.make_entity(inventory={
            "长刀": {"tags": ["战斗", "武器", "刀"], "multiplier": 1.6}
        })
        mult, buffs = calculate_conditional_buffs(
            entity, ["战斗", "通用"], "山贼", False, []
        )
        self.assertIn("长刀(x1.6)", buffs)
        self.assertAlmostEqual(mult, 1.6)

    # ── 测试 2: 手持物能被扫描到 ──
    def test_held_item_with_matching_tag_applies_multiplier(self):
        entity = self.make_entity(held_items={
            "火把": {"tags": ["战斗", "燃烧", "威慑", "临时武器"], "multiplier": 1.3}
        })
        mult, buffs = calculate_conditional_buffs(
            entity, ["战斗", "通用"], "山贼", False, []
        )
        self.assertIn("火把(x1.3)", buffs)
        self.assertAlmostEqual(mult, 1.3)

    # ── 测试 3: 手持物优先使用 contextual_multiplier ──
    def test_held_item_contextual_multiplier_overrides_default(self):
        entity = self.make_entity(held_items={
            "火把": {
                "tags": ["战斗", "燃烧", "威慑"],
                "multiplier": 1.0,
                "contextual_multiplier": 1.4
            }
        })
        mult, buffs = calculate_conditional_buffs(
            entity, ["战斗", "通用"], "山贼", False, []
        )
        self.assertIn("火把(x1.4)", buffs)
        self.assertAlmostEqual(mult, 1.4)

    # ── 测试 4: 背包和手持物同时存在时都生效 ──
    def test_both_inventory_and_held_items_contribute(self):
        entity = self.make_entity(
            inventory={"护腕": {"tags": ["战斗", "防御"], "multiplier": 1.1}},
            held_items={"火把": {"tags": ["战斗", "燃烧", "威慑"], "multiplier": 1.3}}
        )
        mult, buffs = calculate_conditional_buffs(
            entity, ["战斗", "通用"], "山贼", False, []
        )
        self.assertAlmostEqual(mult, 1.1 * 1.3)

    # ── 测试 5: matched_assets 能匹配手持物 ──
    def test_matched_assets_matches_held_item(self):
        entity = self.make_entity(held_items={
            "火把": {"tags": ["照明"], "multiplier": 1.3}
        })
        mult, buffs = calculate_conditional_buffs(
            entity, ["通用"], "山贼", False, ["火把"]
        )
        self.assertIn("火把(x1.3)", buffs)


class TestSafeClampMultiplier(unittest.TestCase):
    """测试 contextual_multiplier 的边界校验"""

    def test_normal_value_passes_through(self):
        self.assertAlmostEqual(safe_clamp_multiplier(1.3), 1.3)

    def test_clamps_high_values_to_3(self):
        self.assertAlmostEqual(safe_clamp_multiplier(999), 3.0)
        self.assertAlmostEqual(safe_clamp_multiplier(5.0), 3.0)

    def test_clamps_low_values_to_0_3(self):
        self.assertAlmostEqual(safe_clamp_multiplier(-5), 0.3)
        self.assertAlmostEqual(safe_clamp_multiplier(0), 0.3)

    def test_string_falls_back_to_1(self):
        self.assertAlmostEqual(safe_clamp_multiplier("很强"), 1.0)

    def test_none_falls_back_to_1(self):
        self.assertAlmostEqual(safe_clamp_multiplier(None), 1.0)

    def test_int_converts_to_float(self):
        self.assertAlmostEqual(safe_clamp_multiplier(2), 2.0)


if __name__ == "__main__":
    unittest.main()
