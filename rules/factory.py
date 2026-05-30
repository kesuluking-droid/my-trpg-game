from rules.base_adjudicator import BaseAdjudicator
from rules.classic_combat import ClassicCombatAdjudicator
from rules.skill_check import SkillCheckAdjudicator
from rules.social_check import SocialCheckAdjudicator
from rules.stealth_check import StealthCheckAdjudicator


class AdjudicatorFactory:
    """根据 action_type 动态分发机制检定策略。"""

    _registry = {
        "combat": ClassicCombatAdjudicator,
        "skill": SkillCheckAdjudicator,
        "social": SocialCheckAdjudicator,
        "stealth": StealthCheckAdjudicator,
    }

    @classmethod
    def create(cls, action_type: str) -> BaseAdjudicator:
        adjudicator_cls = cls._registry.get(action_type, ClassicCombatAdjudicator)
        return adjudicator_cls()
