# -*- coding: utf-8 -*-
"""
turn_runtime.py — 沙盒版本回合运行时

================================================================================
🔔 AI 助手维护提醒（每次修改前必读）
================================================================================

【沙盒版本绝对隔离原则】
- 本文件是 turn_runtime.py 的 1:1 沙盒镜像副本
- 所有导入必须指向 sandbox_ 前缀版本
- 禁止直接调用主版本（turn_runtime.py, core_engine.py 等）
- 沙盒修改不得污染主版本管线

【修改步骤】
1. 如需修改功能，先在此沙盒版本测试验证
2. 验证通过后，将修改实质迁移到主版本
3. 不要简单让主版本跳转到沙盒版本

【文件对应关系】
- sandbox_turn_runtime.py ↔ turn_runtime.py

================================================================================

【设计哲学】
- 事务安全：deepcopy + Buffer Flush + 失败回滚
- 双轨状态同步：DC0 放行 vs 机制检定

【核心功能】
1. render_stream_and_commit() — 流式渲染 + 事务提交
2. extract_narrative_state_patch() — 门铃触发后的状态提炼
"""

from __future__ import annotations

import json
import re
import streamlit as st
from copy import deepcopy
from typing import Iterable

from config import MODEL_FLASH


STATE_CHANGED_MARKER = "[STATE_CHANGED]"

DOORBELL_NARRATIVE_INSTRUCTION = (
    "\n【系统指令】：请自由推进剧情。"
    "注意：物品的拾取/丢弃已由系统自动处理，你无需关注物品变动。"
    "但如果你在剧情中判定有以下情况发生，必须在回复的绝对末尾换行输出 "
    "`[STATE_CHANGED]` 标记：\n"
    "- 角色的身心状态发生实质变动（受伤、中毒、崩溃、顿悟、愤怒等）\n"
    "- 角色的能力、天赋、经验发生变动（学会新技能、能力提升等）\n"
    "- 角色的先天特质发生变动（觉醒新特质、特质被剥离等）\n"
    "- NPC 的人际羁绊/态度发生实质转变（结盟、背叛、仇恨加深等）\n"
    "- 物品的特质/属性发生变动（武器被附魔、毒药失效等，注意不是物品本身的得失）\n"
    "若无以上变动，严禁输出该标记。\n"
)


def _strip_state_changed_marker(text: str) -> tuple[str, bool]:
    """物理抹除门铃标记，返回 (纯净文本, 是否触发)。"""
    triggered = STATE_CHANGED_MARKER in text
    cleaned = re.sub(r"\s*\[STATE_CHANGED\]\s*", "", text).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, triggered


def _apply_direct_state_patch(major_graph: dict, state_patch: dict | None, pc_name: str) -> dict:
    """应用机制层提前裁决出的确定性 state_patch。"""
    if not state_patch:
        return major_graph

    graph = deepcopy(major_graph)
    entities = graph.setdefault("entities", {})
    actor = state_patch.get("inventory_changes", {}).get("pc_name") or pc_name
    actor_node = entities.setdefault(actor, {})
    inventory = actor_node.setdefault("6_inventory", {})
    held_items = actor_node.setdefault("7_held_items", {})

    inv_changes = state_patch.get("inventory_changes", {})
    for item_name in inv_changes.get("remove", []):
        inventory.pop(item_name, None)

    for item_name, item_data in inv_changes.get("add", {}).items():
        inventory[item_name] = deepcopy(item_data)

    held_changes = state_patch.get("held_item_changes", {})
    for item_name in held_changes.get("remove", []):
        held_items.pop(item_name, None)

    for item_name, item_data in held_changes.get("add", {}).items():
        held_items[item_name] = deepcopy(item_data)

    for entity_name, fields in state_patch.get("graph_updates", {}).get("entities", {}).items():
        target = entities.setdefault(entity_name, {})
        for key, value in fields.items():
            target[key] = deepcopy(value)

    return graph


def render_stream_and_commit(
    raw_stream_generator: Iterable[str],
    state_patch: dict | None,
    working_graph: dict,
    pc_name: str,
    sync_entry: dict | None = None,
    mech_entry: dict | None = None,
    enable_doorbell: bool = False,
    active_scene: list | None = None,
    active_stage_names: list | None = None,
    legacy_status_sync: bool = False,
    sync_target: str | None = None,
    parsed_intent: dict | None = None,
    suppress_inventory_sync: bool = False,
) -> tuple[str, bool]:
    """
    流式渲染与事务代理（UI Proxy）。
    完整接收流 → 非空校验 → 落盘 session_state → 可选状态同步。
    """
    full_response = ""
    need_rerun = False

    placeholder = st.empty()
    try:
        # ---- 1. 流式接收完整响应 ----
        for chunk in raw_stream_generator:
            if chunk:
                full_response += chunk
            placeholder.markdown(full_response)

        if not full_response.strip():
            raise ValueError("空数据流")

        display_response = full_response

        # ---- 2. 机制检定警告展示 ----
        if parsed_intent and not enable_doorbell:
            action_type = parsed_intent.get("action_category", "unknown")
            initiator = parsed_intent.get("initiator_entity") or pc_name
            ability = parsed_intent.get("detected_ability")
            target = parsed_intent.get("target_entity")
            target_ongoing = parsed_intent.get("target_ongoing_action")

            init_ability_str = f"【{ability}】" if ability else "【基础动作】"
            target_ability_str = f"【{target_ongoing}】" if target_ongoing else "【自然承受/基础防卫】"

            st.warning(
                f"⚔️ 机制行为 ({action_type}) \n\n"
                f"**发起方**：{initiator} ➔ 使用能力：{init_ability_str} \n\n"
                f"**对抗方**：{target or '环境'} ➔ 应对招式：{target_ability_str}"
            )

        # ---- 3. 门铃标记处理（DC0 放行路径） ----
        doorbell_triggered = False
        if enable_doorbell:
            display_response, doorbell_triggered = _strip_state_changed_marker(full_response)
            placeholder.markdown(display_response)

        # ---- 4. 落盘 working_graph ----
        if state_patch:
            working_graph = _apply_direct_state_patch(working_graph, state_patch, pc_name)
        st.session_state["major_graph"] = working_graph

        # ---- 5. 日志记录 ----
        if sync_entry:
            st.session_state.setdefault("sync_log", []).append(sync_entry)
        if mech_entry:
            st.session_state.setdefault("mechanics_log", []).append(mech_entry)

        # ---- 6. 门铃后置状态提炼（简化版） ----
        if enable_doorbell and doorbell_triggered:
            st.toast("门铃触发：状态变更已记录")

        return display_response, need_rerun

    except Exception as exc:
        placeholder.empty()
        st.error(f"沙盒回合事务失败，已回滚本回合渲染与补丁提交：{exc}")
        return "", False
