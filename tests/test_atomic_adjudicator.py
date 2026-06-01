import unittest

from rules.atomic_adjudicator import (
    AtomicActionRequest,
    AtomicActionResult,
    get_atomic_adjudicator,
    map_tier_to_numeric_result,
    map_delta_to_numeric_result,
    parse_delta_from_injection,
    parse_tier_from_injection,
)


class AtomicAdjudicatorTest(unittest.TestCase):
    def test_parse_tier_and_numeric_result_from_standard_injection(self):
        injection = "【裁决结果】发起方效果本次对抗中成功胜过了抵抗方效果 (Δ: 7.0)"

        tier = parse_tier_from_injection(injection)

        self.assertEqual(tier, "发起方效果本次对抗中成功胜过了抵抗方效果")
        self.assertEqual(map_tier_to_numeric_result(tier), "success")

    def test_delta_mapping_overrides_ambiguous_chinese_text(self):
        injection = "【裁决结果】抵抗方效果本次对抗中完全碾压了发起方效果 (Δ: -16.0)"

        delta = parse_delta_from_injection(injection)

        self.assertEqual(delta, -16.0)
        self.assertEqual(map_delta_to_numeric_result(delta), "failure")

    def test_get_atomic_adjudicator_defaults_to_standard_backend(self):
        adjudicator = get_atomic_adjudicator()

        self.assertEqual(adjudicator.backend_id, "standard_v1")

    def test_custom_backend_can_use_same_request_result_contract(self):
        request = AtomicActionRequest(
            action_id="a1",
            action_type="combat",
            initiator_name="柯酥卤",
            target_name="山贼",
            ability_name=None,
            target_ongoing_action=None,
            initiator_assets=[],
            target_assets=[],
            world_anchor_text="武侠世界",
            major_graph={"entities": {}},
        )

        result = AtomicActionResult(
            action_id=request.action_id,
            numeric_result="success",
            tier="自定义成功",
            system_injection="自定义裁判注入",
            backend_id="custom_v1",
            debug={"request_action": request.action_type},
        )

        self.assertEqual(result.action_id, "a1")
        self.assertEqual(result.backend_id, "custom_v1")
        self.assertEqual(result.debug["request_action"], "combat")


if __name__ == "__main__":
    unittest.main()
