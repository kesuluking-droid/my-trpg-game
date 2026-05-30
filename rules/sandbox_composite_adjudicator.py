# -*- coding: utf-8 -*-
"""
rules/sandbox_composite_adjudicator.py — 复合流水线裁判（实验性隔离模组）

【架构约束】
- 不修改 rules/ 下其它主干文件。
- CompositeAdjudicator.execute 为纯函数：不触碰 session_state，仅返回 state_patch。
- 叙事流式输出遵循 Buffer Flush：先完整缓冲，事务提交成功后再一次性抛出。

【对齐现有结构】
- 玩家背包：major_graph["entities"][pc_name]["6_inventory"]
- 图谱实体：major_graph["entities"]
"""

from __future__ import annotations

import json
import traceback
from copy import deepcopy
from typing import Any, Generator, Iterable

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
NUMERIC_SUCCESS = "SUCCESS"
NUMERIC_FAILURE = "FAILURE"
NUMERIC_CRITICAL_FAILURE = "CRITICAL_FAILURE"

WEIGHT_CRITICAL = "CRITICAL"
WEIGHT_HIGH = "HIGH"
WEIGHT_MEDIUM = "MEDIUM"
WEIGHT_LOW = "LOW"
PRESERVE_WEIGHTS = {WEIGHT_CRITICAL, WEIGHT_HIGH}
TRUNCATE_WEIGHTS = {WEIGHT_MEDIUM, WEIGHT_LOW}

NARRATIVE_STYLE_GUIDE = {
    "tone_clamp": "MATCH_HISTORICAL_CHAT_STYLE",
    "pacing": "COMPACT",
}

BACKGROUND_NOISE_ENTRY = {
    "background_noise": "其余参与者的微观动作未能显著改变战局，被混战掩盖",
}

CASCADE_SKIP_SCENE = (
    "前置动作遭遇灾难性失败，连锁反应被强行熔断；"
    "后续企图在混乱中瓦解，现场只留下未能执行的残影与惩罚性后果。"
)


def empty_state_patch() -> dict[str, dict]:
    return {"inventory_changes": {}, "graph_updates": {}}


# ---------------------------------------------------------------------------
# 步骤 1：纯函数复合裁判
# ---------------------------------------------------------------------------
class CompositeAdjudicator:
    """
    多原子动作复合裁判。execute 不修改外部状态，仅累积并返回 state_patch。
    """

    def execute(
        self,
        atomic_actions: list[dict],
        inventory_snapshot: dict,
        major_graph_snapshot: dict,
        pc_name: str = "主角",
        **kwargs: Any,
    ) -> dict[str, Any]:
        virtual_inventory = deepcopy(inventory_snapshot or {})
        state_patch = empty_state_patch()
        state_patch["inventory_changes"]["pc_name"] = pc_name
        state_patch["inventory_changes"].setdefault("add", {})
        state_patch["inventory_changes"].setdefault("remove", [])
        state_patch["graph_updates"].setdefault("entities", {})

        micro_contributions: list[dict] = []
        action_results: dict[str, dict] = {}
        cascade_tripped = False

        for index, action in enumerate(atomic_actions or []):
            action_id = str(action.get("action_id", f"action_{index}"))
            depends_on = action.get("depends_on")

            if depends_on and action_results.get(depends_on, {}).get("numeric_result") == NUMERIC_CRITICAL_FAILURE:
                cascade_tripped = True
                micro_contributions.append({
                    "action_id": action_id,
                    "intended_action": action.get("intended_action", "unknown"),
                    "numeric_result": NUMERIC_FAILURE,
                    "narrative_weight": action.get("narrative_weight", WEIGHT_LOW),
                    "scene_note": CASCADE_SKIP_SCENE,
                    "skipped_by_cascade": True,
                })
                continue

            if cascade_tripped and depends_on:
                micro_contributions.append({
                    "action_id": action_id,
                    "intended_action": action.get("intended_action", "unknown"),
                    "numeric_result": NUMERIC_FAILURE,
                    "narrative_weight": action.get("narrative_weight", WEIGHT_LOW),
                    "scene_note": CASCADE_SKIP_SCENE,
                    "skipped_by_cascade": True,
                })
                continue

            cost_items = action.get("cost_items") or {}
            consume_ok, consume_note = self._consume_virtual_items(virtual_inventory, cost_items)
            if not consume_ok:
                result_entry = {
                    "action_id": action_id,
                    "intended_action": action.get("intended_action", "unknown"),
                    "numeric_result": NUMERIC_FAILURE,
                    "narrative_weight": action.get("narrative_weight", WEIGHT_MEDIUM),
                    "scene_note": consume_note,
                    "inventory_insufficient": True,
                }
                action_results[action_id] = result_entry
                micro_contributions.append(result_entry)
                continue

            numeric_result = self._resolve_numeric_result(action)
            scene_note = action.get("scene_note") or action.get("world_state_change") or ""

            if numeric_result == NUMERIC_CRITICAL_FAILURE:
                cascade_tripped = True
                scene_note = f"{scene_note} | {CASCADE_SKIP_SCENE}".strip(" |")

            if numeric_result == NUMERIC_SUCCESS:
                reward_items = action.get("reward_items") or {}
                for item_name, item_data in reward_items.items():
                    if item_name not in virtual_inventory:
                        virtual_inventory[item_name] = deepcopy(item_data)
                        state_patch["inventory_changes"]["add"][item_name] = deepcopy(item_data)

            if cost_items:
                for item_name, qty in cost_items.items():
                    if int(qty or 0) > 0 and item_name in inventory_snapshot:
                        if item_name not in state_patch["inventory_changes"]["remove"]:
                            state_patch["inventory_changes"]["remove"].append(item_name)

            if numeric_result in {NUMERIC_SUCCESS, NUMERIC_FAILURE}:
                graph_delta = action.get("graph_entity_delta")
                if isinstance(graph_delta, dict) and graph_delta.get("entity_name"):
                    entity_name = graph_delta["entity_name"]
                    state_patch["graph_updates"]["entities"][entity_name] = deepcopy(
                        graph_delta.get("fields", {})
                    )

            result_entry = {
                "action_id": action_id,
                "intended_action": action.get("intended_action", "unknown"),
                "numeric_result": numeric_result,
                "narrative_weight": action.get("narrative_weight", WEIGHT_MEDIUM),
                "scene_note": scene_note,
                "affected_assets": action.get("affected_assets", []),
            }
            action_results[action_id] = result_entry
            micro_contributions.append(result_entry)

        sliced_contributions = slice_micro_contributions(micro_contributions)
        narrative_payload = build_narrative_payload(sliced_contributions)

        return {
            "state_patch": state_patch,
            "micro_contributions": sliced_contributions,
            "narrative_payload": narrative_payload,
            "action_results": action_results,
            "virtual_inventory_final": virtual_inventory,
        }

    @staticmethod
    def _consume_virtual_items(virtual_inventory: dict, cost_items: dict) -> tuple[bool, str]:
        if not cost_items:
            return True, ""

        for item_name, qty in cost_items.items():
            qty = int(qty) if qty else 0
            if qty <= 0:
                continue
            available = 1 if item_name in virtual_inventory else 0
            if available < qty:
                return False, f"虚拟资产不足：{item_name} 需求 {qty}，可用 {available}"
            del virtual_inventory[item_name]

        return True, ""

    @staticmethod
    def _resolve_numeric_result(action: dict) -> str:
        explicit = action.get("numeric_result")
        if explicit in {NUMERIC_SUCCESS, NUMERIC_FAILURE, NUMERIC_CRITICAL_FAILURE}:
            return explicit

        risk_flag = action.get("is_risk", False)
        dice_roll = int(action.get("dice_roll", 10))
        dc = int(action.get("dc", 10))

        if dice_roll == 1:
            return NUMERIC_CRITICAL_FAILURE
        if dice_roll >= dc:
            return NUMERIC_SUCCESS
        if risk_flag and dice_roll <= dc // 2:
            return NUMERIC_CRITICAL_FAILURE
        return NUMERIC_FAILURE


# ---------------------------------------------------------------------------
# 步骤 3：微观贡献切片与叙事载荷
# ---------------------------------------------------------------------------
def slice_micro_contributions(micro_contributions: list[dict]) -> list[dict]:
    preserved: list[dict] = []
    truncatable: list[dict] = []

    for entry in micro_contributions:
        weight = str(entry.get("narrative_weight", WEIGHT_MEDIUM)).upper()
        if weight in PRESERVE_WEIGHTS:
            preserved.append(entry)
        elif weight in TRUNCATE_WEIGHTS:
            truncatable.append(entry)
        else:
            truncatable.append(entry)

    kept_medium_low = truncatable[:2]
    discarded_count = max(0, len(truncatable) - 2)

    result = preserved + kept_medium_low
    if discarded_count > 0:
        result.append(deepcopy(BACKGROUND_NOISE_ENTRY))
    return result


def build_narrative_payload(micro_contributions: list[dict]) -> dict[str, Any]:
    return {
        "micro_contributions": micro_contributions,
        "narrative_style_guide": deepcopy(NARRATIVE_STYLE_GUIDE),
        "narrative_constraints": (
            "严禁在叙事文本中显式写出伤害数字、HP、DC、掷骰点数或公式。"
            "以感官描写与因果映射替代数值播报；文风须贴合历史对话语气，节奏紧凑。"
        ),
    }


def format_narrative_payload_for_context(narrative_payload: dict) -> str:
    payload_json = json.dumps(narrative_payload, ensure_ascii=False, indent=2)
    return (
        "\n\n【复合裁判微观叙事载荷 | SANDBOX】\n"
        f"{payload_json}\n"
        "【执行协议】：以上微观贡献为已裁决事实，请据此编织叙事；"
        "绝对禁止向玩家暴露任何数值、骰点或检定公式。\n"
    )


# ---------------------------------------------------------------------------
# 步骤 4：延迟回写与 Buffer Flush 流式协议
# ---------------------------------------------------------------------------
def commit_state_patch(state_patch: dict | None, major_graph: dict, pc_name: str) -> dict:
    """
    两阶段事务最终提交：将 state_patch 落盘至 major_graph（就地变异）。
    返回更新后的 major_graph。
    """
    if not state_patch:
        return major_graph

    entities = major_graph.setdefault("entities", {})
    entity = entities.setdefault(pc_name, {})
    inventory = entity.setdefault("6_inventory", {})

    inv_changes = state_patch.get("inventory_changes", {})
    for item_name in inv_changes.get("remove", []):
        inventory.pop(item_name, None)

    for item_name, item_data in inv_changes.get("add", {}).items():
        inventory[item_name] = deepcopy(item_data)

    graph_updates = state_patch.get("graph_updates", {})
    for entity_name, fields in graph_updates.get("entities", {}).items():
        target = entities.setdefault(entity_name, {})
        for key, value in fields.items():
            target[key] = deepcopy(value)

    return major_graph


def clear_buffer_and_log_error(error: Exception) -> str:
    traceback.print_exc()
    print(f"[sandbox_composite] Buffer Flush 事务回滚 | 错误: {error}")
    return (
        f"\n\n[系统警告：叙事生成或状态提交失败 ({type(error).__name__})。"
        "本次回合未写入任何图谱/背包变更，请重试。]"
    )


def _collect_stream_chunks(stream: Iterable[str]) -> str:
    buffer = ""
    for chunk in stream:
        if chunk:
            buffer += chunk
    return buffer


def buffered_stream_narrative_with_commit(
    context_text: str,
    active_scene: list,
    state_patch: dict | None,
    major_graph: dict,
    pc_name: str = "主角",
) -> Generator[str, None, None]:
    """
    纯净流式缓存协议：
    1. 内部完整收集流式 chunk 至 buffer（不向调用方逐片泄露）
    2. 生成 100% 成功后 commit_state_patch
    3. 事务成功后才 yield 完整 buffer（单次 flush）
    """
    from core_engine import generate_chat_stream

    buffer = ""
    try:
        buffer = _collect_stream_chunks(generate_chat_stream(context_text, active_scene))
        commit_state_patch(state_patch, major_graph, pc_name)
        yield buffer
    except Exception as exc:
        buffer = ""
        yield clear_buffer_and_log_error(exc)


def run_composite_adjudication_turn(
    atomic_actions: list[dict],
    major_graph: dict,
    pc_name: str,
    context_text: str,
    active_scene: list,
) -> Generator[str, None, None]:
    """
    调度主循环入口：复合裁判 → 叙事载荷注入 → 缓冲流式生成 → 延迟回写。
    """
    entities = major_graph.get("entities", {})
    pc_entity = entities.get(pc_name, {})
    inventory_snapshot = deepcopy(pc_entity.get("6_inventory", {}))

    adjudicator = CompositeAdjudicator()
    adjudication = adjudicator.execute(
        atomic_actions,
        inventory_snapshot,
        deepcopy(major_graph),
        pc_name=pc_name,
    )

    enriched_context = context_text + format_narrative_payload_for_context(
        adjudication["narrative_payload"]
    )

    yield from buffered_stream_narrative_with_commit(
        enriched_context,
        active_scene,
        adjudication["state_patch"],
        major_graph,
        pc_name,
    )


def atomic_actions_from_intent(parsed_intent: dict, dice_roll: int = 12, dc: int = 10) -> list[dict]:
    """
    将 sandbox_intent_parser 的解析结果转为原子动作列表（供沙盒联调）。
  """
    if not parsed_intent:
        return []

    return [{
        "action_id": "intent_primary",
        "intended_action": parsed_intent.get("intended_action", "unknown"),
        "affected_assets": parsed_intent.get("affected_assets", []),
        "world_state_change": parsed_intent.get("world_state_change", ""),
        "scene_note": parsed_intent.get("world_state_change", ""),
        "is_risk": parsed_intent.get("is_risk", False),
        "narrative_weight": WEIGHT_HIGH if parsed_intent.get("is_risk") else WEIGHT_MEDIUM,
        "dice_roll": dice_roll,
        "dc": dc,
        "cost_items": parsed_intent.get("cost_items", {}),
        "reward_items": parsed_intent.get("reward_items", {}),
        "depends_on": None,
    }]


# ---------------------------------------------------------------------------
# 干跑
# ---------------------------------------------------------------------------
def _dry_run():
    mock_graph = {
        "entities": {
            "主角": {
                "6_inventory": {"火把": {"tags": ["道具"], "multiplier": 1.0}},
                "tags": ["玩家"],
            }
        },
        "relations": [],
    }

    actions = [
        {
            "action_id": "a0",
            "intended_action": "use_tool",
            "cost_items": {"火把": 1},
            "narrative_weight": WEIGHT_CRITICAL,
            "numeric_result": NUMERIC_CRITICAL_FAILURE,
            "scene_note": "火把脱手坠入深渊。",
        },
        {
            "action_id": "a1",
            "intended_action": "search_item",
            "depends_on": "a0",
            "narrative_weight": WEIGHT_HIGH,
            "scene_note": "试图摸索岩壁。",
        },
        {
            "action_id": "a2",
            "intended_action": "observe",
            "narrative_weight": WEIGHT_LOW,
            "scene_note": "观察微粒",
        },
        {
            "action_id": "a3",
            "intended_action": "observe",
            "narrative_weight": WEIGHT_LOW,
            "scene_note": "观察尘土",
        },
        {
            "action_id": "a4",
            "intended_action": "observe",
            "narrative_weight": WEIGHT_LOW,
            "scene_note": "观察风声",
        },
    ]

    adj = CompositeAdjudicator()
    result = adj.execute(actions, mock_graph["entities"]["主角"]["6_inventory"], mock_graph, "主角")
    print("=== sandbox_composite_adjudicator 干跑 ===")
    print("state_patch:", json.dumps(result["state_patch"], ensure_ascii=False, indent=2))
    print("切片后微观贡献数:", len(result["micro_contributions"]))
    print("含 background_noise:", any("background_noise" in c for c in result["micro_contributions"]))
    print("narrative_style_guide:", result["narrative_payload"]["narrative_style_guide"])


if __name__ == "__main__":
    _dry_run()
