
from rules.adjudication_utils import run_standard_adjudication
from rules.base_adjudicator import BaseAdjudicator


class ClassicCombatAdjudicator(BaseAdjudicator):
    """战斗对抗裁决：双端 D20 出力对撞，侧重攻防能力与战斗经验乘区。"""

    action_type = "combat"

    def execute(self, initiator_assets, target_assets, world_tier, **kwargs):
        return run_standard_adjudication(
            action_type=self.action_type,
            initiator_assets=initiator_assets,
            target_assets=target_assets,
            world_anchor_text=world_tier,
            ability_name=kwargs.get("ability_name"),
            initiator_name=kwargs.get("initiator_name"),
            target_name=kwargs.get("target_name"),
            target_ongoing_action=kwargs.get("target_ongoing_action"),
            major_graph=kwargs.get("major_graph"),
            is_social=False,
        )
