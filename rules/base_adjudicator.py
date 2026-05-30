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
