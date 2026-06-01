# ============================================================
# 维护提醒
# ------------------------------------------------------------
# 本文件为沙盒版本 (sandbox_)，修改后需同步到主版本 (main/)
# 同步时请确保：
# 1. 功能逻辑完全一致
# 2. 仅移除 sandbox_ 前缀
# 3. 保持所有类型注解和文档字符串
# ============================================================

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sandbox_rules.adjudication_utils import run_standard_adjudication


@dataclass
class AtomicActionRequest:
    action_id: str
    action_type: str
    initiator_name: str
    target_name: str | None
    ability_name: str | None
    target_ongoing_action: str | None
    initiator_assets: list[str]
    target_assets: list[str]
    world_anchor_text: str
    major_graph: dict
    is_social: bool = False
    ability_invalid: bool = False
    backend_id: str = "standard_v1"


@dataclass
class AtomicActionResult:
    action_id: str
    numeric_result: str
    tier: str
    system_injection: str
    backend_id: str
    debug: dict[str, Any] = field(default_factory=dict)


def parse_tier_from_injection(system_injection: str) -> str:
    match = re.search(r"【裁决结果】(.+?)(?:\s*\(Δ:|\n|$)", system_injection or "")
    if not match:
        return "未知裁决结果"
    return match.group(1).strip()


def parse_delta_from_injection(system_injection: str) -> float | None:
    match = re.search(r"Δ:\s*([-+]?\d+(?:\.\d+)?)", system_injection or "")
    if not match:
        return None
    return float(match.group(1))


def map_delta_to_numeric_result(delta: float | None) -> str:
    if delta is None:
        return "failure"
    return "success" if delta >= 0 else "failure"


def map_tier_to_numeric_result(tier: str) -> str:
    text = tier or ""
    if "发起方" in text and ("完全碾压" in text or "成功胜过" in text):
        return "success"
    if "相持不下" in text:
        return "failure"
    if "抵抗方" in text and "完全碾压" in text:
        return "failure"
    return "failure"


class StandardAtomicAdjudicator:
    backend_id = "standard_v1"

    def resolve(self, request: AtomicActionRequest) -> AtomicActionResult:
        injection = run_standard_adjudication(
            action_type=request.action_type,
            initiator_assets=request.initiator_assets,
            target_assets=request.target_assets,
            world_anchor_text=request.world_anchor_text,
            ability_name=request.ability_name,
            initiator_name=request.initiator_name,
            target_name=request.target_name,
            target_ongoing_action=request.target_ongoing_action,
            major_graph=request.major_graph,
            is_social=request.is_social,
            ability_invalid=request.ability_invalid,
        )
        tier = parse_tier_from_injection(injection)
        delta = parse_delta_from_injection(injection)
        numeric_result = map_delta_to_numeric_result(delta)
        return AtomicActionResult(
            action_id=request.action_id,
            numeric_result=numeric_result,
            tier=tier,
            system_injection=injection,
            backend_id=self.backend_id,
            debug={"raw_injection": injection, "delta": delta},
        )


_REGISTRY = {
    "standard_v1": StandardAtomicAdjudicator,
}


def get_atomic_adjudicator(backend_id: str = "standard_v1"):
    adjudicator_cls = _REGISTRY.get(backend_id, StandardAtomicAdjudicator)
    return adjudicator_cls()
