
from rules.adjudication_utils import run_standard_adjudication
from rules.base_adjudicator import BaseAdjudicator


class SkillCheckAdjudicator(BaseAdjudicator):
    """技能检定裁决：非战斗类能力对抗，按技能领域匹配资产与专精经验。"""

    action_type = "skill"

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
