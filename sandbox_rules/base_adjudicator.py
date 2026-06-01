# -*- coding: utf-8 -*-
"""
sandbox_rules/base_adjudicator.py — 沙盒版本规则引擎基类

================================================================================
🔔 AI 助手维护提醒（每次修改前必读）
================================================================================

【沙盒版本绝对隔离原则】
- 本文件是 rules/base_adjudicator.py 的 1:1 沙盒镜像副本
- 所有导入必须指向 sandbox_ 前缀版本
- 禁止直接调用主版本（rules/ 等）
- 沙盒修改不得污染主版本管线

【修改步骤】
1. 如需修改功能，先在此沙盒版本测试验证
2. 验证通过后，将修改实质迁移到主版本
3. 不要简单让主版本跳转到沙盒版本

【文件对应关系】
- sandbox_rules/base_adjudicator.py ↔ rules/base_adjudicator.py

================================================================================
"""

from abc import ABC, abstractmethod


class BaseAdjudicator(ABC):
    """机制检定策略基类。"""

    action_type: str = "none"

    @abstractmethod
    def execute(self, initiator_assets, target_assets, world_tier, **kwargs) -> str:
        """
        执行机制检定并返回注入 GM 的系统文本。

        Parameters
        ----------
        initiator_assets : list
            发起方匹配资产名称列表。
        target_assets : list
            对抗方匹配资产名称列表。
        world_tier : str
            当前世界观威力锚定文本（world anchor text）。
        **kwargs
            ability_name, initiator_name, target_name, target_ongoing_action,
            major_graph, gm_memory 等上下文参数。
        """
        raise NotImplementedError
