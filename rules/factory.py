# -*- coding: utf-8 -*-
"""
sandbox_rules/factory.py — 沙盒版本规则引擎工厂

================================================================================
🔔 AI 助手维护提醒（每次修改前必读）
================================================================================

【沙盒版本绝对隔离原则】
- 本文件是 rules/factory.py 的 1:1 沙盒镜像副本
- 所有导入必须指向 sandbox_ 前缀版本
- 禁止直接调用主版本（rules/ 等）
- 沙盒修改不得污染主版本管线

【修改步骤】
1. 如需修改功能，先在此沙盒版本测试验证
2. 验证通过后，将修改实质迁移到主版本
3. 不要简单让主版本跳转到沙盒版本

【文件对应关系】
- sandbox_rules/factory.py ↔ rules/factory.py

================================================================================
"""

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
