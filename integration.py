# -*- coding: utf-8 -*-
"""
integration.py — 沙盒集成层（隔离防腐层）

【设计哲学】
- LLM 是世界的造物主，Python 是书记员和算盘。
- 本模块仅提供"事务安全"和"状态同步"基础设施，不干预 LLM 创作自由。
- deepcopy 保护原始图谱，Buffer Flush 确保流式完整后才落盘。

【核心功能】
1. render_stream_and_commit() — 流式渲染 + 事务代理（UI Proxy）
2. extract_narrative_state_patch() — 门铃触发后的影子同步提炼器
3. _apply_extracted_state_patch() — 状态补丁落盘

【双轨状态同步】
- DC0 放行路径：[STATE_CHANGED] 门铃标记 → 事后提炼
- 机制检定路径：<STATUS_UPDATE: 名字> 旧系统标记 → sync_dynamic_status()
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
    "若无以上变动，严禁输出该标记。该标记是系统内部控制符，除精确输出 `[STATE_CHANGED]` 外，严禁输出“状态变动”“状态更新”“图谱同步”等解释性文字。\n"
)


def _strip_state_changed_marker(text: str) -> tuple[str, bool]:
    """物理抹除门铃标记，返回 (纯净文本, 是否触发)。"""
    triggered = STATE_CHANGED_MARKER in text
    cleaned = re.sub(r"\s*\[STATE_CHANGED\]\s*", "", text).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, triggered


def _strip_hidden_control_text(text: str) -> str:
    """只移除明确的机器协议控制符，不基于自然语言黑名单删除叙事。"""
    cleaned = re.sub(r"\s*\[STATE_CHANGED\]\s*", "", text or "")
    cleaned = re.sub(r"\s*<STATUS_UPDATE:\s*.+?>\s*", "", cleaned)
    cleaned = re.sub(r"\s*\[SUGGESTION:\s*.+?\]\s*", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

def _extract_suggestions(text: str) -> list[tuple[str, str]]:
    """从模型输出中提取 [SUGGESTION: 简述|完整建议] 标记，返回 [(summary, full_text), ...]。"""
    matches = re.findall(r"\[SUGGESTION:\s*(.+?)\]", text or "")
    results = []
    for m in matches:
        parts = m.split("|", 1)
        if len(parts) == 2:
            results.append((parts[0].strip(), parts[1].strip()))
        else:
            results.append((m.strip()[:15], m.strip()))
    # 限制2-4条建议
    if len(results) < 2:
        return results
    return results[:4]


def append_narrative_length_instruction(context_text: str) -> str:
    """给叙事生成上下文追加简洁输出约束，避免回复过长。"""
    marker = "【叙事长度约束】"
    if marker in (context_text or ""):
        return context_text
    return (context_text or "") + "\n【叙事长度约束】：本次正式叙事请尽量凝练，原则上不超过500字；只写玩家能看到的故事结果，不输出系统提示、状态变动说明或内部标记。\n"


def _collect_entities_to_check(
    rendered_text: str,
    graph: dict,
    active_scene: list,
    pc_name: str,
    active_stage_names: list | None = None,
) -> list[str]:
    active_stage_names = active_stage_names or []
    recent_context = "\n".join(
        f"{m.get('role', 'user')}: {m.get('content', '')}" for m in active_scene[-3:]
    ) if active_scene else ""
    full_radar_text = f"{rendered_text}\n{recent_context}"

    entities_to_check = [pc_name]
    for name in graph.get("entities", {}).keys():
        if name == pc_name:
            continue
        if (name in full_radar_text) or (name in active_stage_names):
            if name not in entities_to_check:
                entities_to_check.append(name)
    return entities_to_check


def _build_graph_snapshot(graph: dict, entity_names: list[str]) -> str:
    lines = []
    entities = graph.get("entities", {})
    for name in entity_names:
        node = entities.get(name)
        if not node:
            lines.append(f"- {name}: (未入核心图谱)")
            continue
        caps = ", ".join(node.get("3_capabilities", {}).keys()) or "无"
        traits = ", ".join(
            t.get("name", "") for t in node.get("5_traits", []) if isinstance(t, dict)
        ) or "无"
        inv = ", ".join(node.get("6_inventory", {}).keys()) or "无"
        status = node.get("2_dynamic_status", {})
        phys = status.get("physical", {}).get("desc", "正常")
        ment = status.get("mental", {}).get("desc", "正常")
        lines.append(
            f"- {name} | 身心:{phys}/{ment} | 能力:[{caps}] | 特质:[{traits}] | 背包:[{inv}]"
        )
    return "\n".join(lines) if lines else "(无)"


def _apply_extracted_state_patch(major_graph: dict, result: dict, pc_name: str) -> dict:
    """将 FLASH 提炼 JSON 落盘至 major_graph.entities。"""
    entities = major_graph.setdefault("entities", {})

    for raw_entity, data in (result or {}).items():
        if not isinstance(data, dict):
            continue
        entity = raw_entity if raw_entity != "主角" else pc_name
        if entity not in entities:
            continue
        entity_node = entities[entity]

        status_data = data.get("2_dynamic_status", {})
        if status_data:
            if "2_dynamic_status" not in entity_node:
                entity_node["2_dynamic_status"] = {
                    "physical": {"desc": "正常", "multiplier": 1.0},
                    "mental": {"desc": "正常", "multiplier": 1.0},
                }
            if "physical" in status_data:
                entity_node["2_dynamic_status"]["physical"] = status_data["physical"]
            if "mental" in status_data:
                entity_node["2_dynamic_status"]["mental"] = status_data["mental"]

        for removed in data.get("removed_assets", []):
            cat = removed.get("category")
            name = removed.get("name")
            if not cat or not name:
                continue
            incoming_rem_tags = removed.get("target_domains", removed.get("tags", []))
            if isinstance(incoming_rem_tags, str):
                incoming_rem_tags = [incoming_rem_tags]
            elif not isinstance(incoming_rem_tags, list):
                incoming_rem_tags = []

            if cat in entity_node and isinstance(entity_node[cat], dict) and name in entity_node[cat]:
                if incoming_rem_tags:
                    tag_key = (
                        "domains" if cat == "3_capabilities"
                        else ("tags" if cat == "6_inventory" else "target_domains")
                    )
                    if tag_key in entity_node[cat][name] and isinstance(entity_node[cat][name][tag_key], list):
                        entity_node[cat][name][tag_key] = [
                            tag for tag in entity_node[cat][name][tag_key] if tag not in incoming_rem_tags
                        ]
                else:
                    del entity_node[cat][name]
            elif cat == "5_traits" and isinstance(entity_node.get(cat), list):
                existing_trait = next(
                    (t for t in entity_node["5_traits"] if isinstance(t, dict) and t.get("name") == name),
                    None,
                )
                if existing_trait:
                    if incoming_rem_tags:
                        if "target_domains" in existing_trait and isinstance(existing_trait["target_domains"], list):
                            existing_trait["target_domains"] = [
                                tag for tag in existing_trait["target_domains"] if tag not in incoming_rem_tags
                            ]
                    else:
                        entity_node["5_traits"].remove(existing_trait)

        for new_asset in data.get("new_assets", []):
            cat = new_asset.get("category")
            name = new_asset.get("name")
            if not cat or not name:
                continue
            if cat not in entity_node:
                entity_node[cat] = {} if cat != "5_traits" else []

            incoming_tags = new_asset.get("target_domains", new_asset.get("tags", []))
            if isinstance(incoming_tags, str):
                incoming_tags = [incoming_tags]
            elif not isinstance(incoming_tags, list):
                incoming_tags = []
            new_features = new_asset.get("features", [])
            if isinstance(new_features, str):
                new_features = [new_features]
            elif not isinstance(new_features, list):
                new_features = []

            if cat == "3_capabilities":
                if name in entity_node["3_capabilities"]:
                    current_mastery = entity_node["3_capabilities"][name].get("mastery_level", 1.0)
                    entity_node["3_capabilities"][name]["mastery_level"] = round(current_mastery + 0.1, 2)
                    entity_node["3_capabilities"][name].setdefault("domains", [])
                    for tag in incoming_tags:
                        if tag not in entity_node["3_capabilities"][name]["domains"]:
                            entity_node["3_capabilities"][name]["domains"].append(tag)
                    entity_node["3_capabilities"][name].setdefault("features", [])
                    for feat in new_features:
                        if feat not in entity_node["3_capabilities"][name]["features"]:
                            entity_node["3_capabilities"][name]["features"].append(feat)
                else:
                    entity_node[cat][name] = {
                        "domains": incoming_tags or ["通用"],
                        "base_power": max(1, int(new_asset.get("base_power", 20))),
                        "mastery_level": 1.0,
                        "features": new_features or ["剧情顿悟"],
                    }
            elif cat == "6_inventory":
                raw_mult = new_asset.get("multiplier", 1.0)
                safe_mult = max(0.1, min(float(raw_mult), 3.0))
                if name in entity_node["6_inventory"]:
                    old_mult = entity_node["6_inventory"][name].get("multiplier", 1.0)
                    entity_node["6_inventory"][name]["multiplier"] = round(max(old_mult + 0.05, safe_mult), 2)
                    entity_node["6_inventory"][name].setdefault("tags", [])
                    for tag in incoming_tags:
                        if tag not in entity_node["6_inventory"][name]["tags"]:
                            entity_node["6_inventory"][name]["tags"].append(tag)
                    entity_node["6_inventory"][name].setdefault("features", [])
                    for feat in new_features:
                        if feat not in entity_node["6_inventory"][name]["features"]:
                            entity_node["6_inventory"][name]["features"].append(feat)
                else:
                    entity_node["6_inventory"][name] = {
                        "tags": incoming_tags or ["通用"],
                        "multiplier": safe_mult,
                        "features": new_features or ["初始获得"],
                    }
            elif cat == "5_traits":
                raw_mult = new_asset.get("multiplier", 1.0)
                safe_mult = max(0.1, min(float(raw_mult), 3.0))
                existing_trait = next(
                    (t for t in entity_node["5_traits"] if isinstance(t, dict) and t.get("name") == name),
                    None,
                )
                if existing_trait:
                    old_mult = existing_trait.get("multiplier", 1.0)
                    existing_trait["multiplier"] = round(max(old_mult + 0.05, safe_mult), 2)
                    existing_trait.setdefault("target_domains", [])
                    for tag in incoming_tags:
                        if tag not in existing_trait["target_domains"]:
                            existing_trait["target_domains"].append(tag)
                    existing_trait.setdefault("features", [])
                    for feat in new_features:
                        if feat not in existing_trait["features"]:
                            existing_trait["features"].append(feat)
                else:
                    entity_node["5_traits"].append({
                        "name": name,
                        "target_domains": incoming_tags or ["通用"],
                        "multiplier": safe_mult,
                        "features": new_features or ["觉醒"],
                    })
            elif isinstance(entity_node.get(cat), dict):
                raw_mult = new_asset.get("multiplier", 1.0)
                entity_node[cat][name] = {
                    "target_domains": incoming_tags or ["通用"],
                    "multiplier": max(0.1, min(float(raw_mult), 3.0)),
                }

    return major_graph


def extract_narrative_state_patch(
    text: str,
    graph: dict,
    active_scene: list,
    pc_name: str,
    active_stage_names: list | None = None,
) -> tuple[dict, dict]:
    """
    门铃触发后的影子同步提炼器（MODEL_FLASH）。
    返回 (更新后的 graph, 原始提炼 JSON)。
    """
    from core_engine import get_user_client

    entities_to_check = _collect_entities_to_check(text, graph, active_scene, pc_name, active_stage_names)
    recent_context = "\n".join(
        f"{m.get('role', 'user')}: {m.get('content', '')}" for m in active_scene[-3:]
    ) if active_scene else "无"
    stage_info = ", ".join(active_stage_names) if active_stage_names else f"仅{pc_name}在场"
    graph_snapshot = _build_graph_snapshot(graph, entities_to_check)

    system_prompt = f"""你是一个TRPG状态同步与数值生成引擎。
请阅读动作结算文本，提取以下角色的状态变更与资产变动：{entities_to_check}。

【当前人物图谱快照】
{graph_snapshot}

【当前舞台时空坐标】
- 本幕在场核心角色名录: [{stage_info}]

【前情提要（最近3幕历史对话）】
{recent_context}

【核心任务与原子操作量化协议】
1. 状态重置 (2_dynamic_status)：
   必须依据文本严格量化乘区（绝佳/顿悟: 1.2-1.5；良好/专注: 1.05-1.15；正常: 1.0；疲惫/轻伤: 0.7-0.9；重伤/崩溃: 0.1-0.5）。
2. 资产新增/强化 (new_assets)：
   - 场景 A (无中生有)：角色获得了全新武器、特质、羁绊或武功。
   - 场景 B (旧物进化)：已有资产（名字必须与历史原名一字不差）获得了新标签（target_domains）或新词条（features）。
   ⚠️ 绝对红线：严禁将"观察/研究/装备/使用"背包里已有的物品误判为"获得新物品"。只有明确发生"拾取/购买/别人赠予"等资产净增量时才允许提取！
   ⚠️ 物品威力量化：新增物品（6_inventory）的 multiplier 必须反映其品质：
   普通杂物（石头、树枝）: 0.3-0.5；常见武器（铁剑、匕首）: 0.8-1.2；精良武器（附魔、名器）: 1.3-2.0；传说/神器（神剑、仙器）: 2.0-3.0。
   ⚠️ 能力获得严格判定：只有叙事中明确出现"领悟/学会/觉醒/掌握/传承/习得"等获得性关键词时，才允许在 3_capabilities 中新增能力。仅描述角色"使用/施展/做出"某个动作（如闪避、反击、出拳、跳跃），属于正常行为描述，绝对严禁将其误判为"获得新能力"！
3. 资产剥离/移除 (removed_assets)：
   - 场景 C (属性削弱/洗练)：指定 `name` 并在 `target_domains` 中填入特定标签。系统将仅精准剔除该资产内部的这些属性（例如：武器上的"毒"标签失效）。
   - 场景 D (整体彻底销毁)：指定 `name`，并将 `target_domains` 保持为空列表 `[]`。系统将把该资产（如：武器丢失、NPC彻底死亡、特质被剥离）从图谱中物理抹除。
4. 需要替换属性时，可以先新增新属性后移除旧属性，参照2、3.

【AI可执行全操作终极完全体 JSON 样例】
必须严格参照以下全谱系样例结构进行 JSON 输出（若某个角色没有任何变动，则对应的 `new_assets` 和 `removed_assets` 保持为空列表 `[]`）：
{{
    "{pc_name}": {{
        "2_dynamic_status": {{
            "physical": {{"desc": "左臂被利刃斩中，流血不止", "multiplier": 0.75}},
            "mental": {{"desc": "燃起复仇的熊熊怒火，神志高度专注", "multiplier": 1.25}}
        }},
        "new_assets": [
            {{
                "category": "3_capabilities",
                "name": "天刀绝意斩",
                "target_domains": ["刀法", "爆发", "斩杀"],
                "base_power": 85,
                "features": ["临战顿悟", "无视轻甲"]
            }},
            {{
                "category": "6_inventory",
                "name": "戒指",
                "target_domains": ["储物", "未解密"],
                "multiplier": 1.0,
                "features": ["古朴的铜戒"]
            }},
            {{
                "category": "6_inventory",
                "name": "神剑",
                "target_domains": ["神器", "斩击", "破甲"],
                "multiplier": 2.5,
                "features": ["剑身流转金光", "可斩断一切凡铁"]
            }}
        ],
        "removed_assets": [
            {{
                "category": "5_traits",
                "name": "文弱书生",
                "target_domains": []
            }}
        ]
    }},
    "敌对NPC姓名": {{
        "2_dynamic_status": {{
            "physical": {{"desc": "右腿骨折，行动力几近丧失", "multiplier": 0.40}},
            "mental": {{"desc": "陷入绝望，战意彻底崩溃", "multiplier": 0.30}}
        }},
        "new_assets": [],
        "removed_assets": [
            {{
                "category": "6_inventory",
                "name": "青钢长剑",
                "target_domains": []
            }}
        ]
    }}
}}

【最新动作结算文本】
{text}

请严格以上述 JSON 样例为标准，输出本次清算结果："""

    client = get_user_client()
    if not client:
        return graph, {}

    try:
        response = client.chat.completions.create(
            model=MODEL_FLASH,
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw_content = response.choices[0].message.content.strip()
        match = re.search(r"\{.*\}", raw_content, re.DOTALL)
        result = json.loads(match.group(0) if match else raw_content)
        updated_graph = _apply_extracted_state_patch(deepcopy(graph), result, pc_name)
        return updated_graph, result
    except Exception as exc:
        print(f"[sandbox_integration] 门铃后置提炼失败: {exc}")
        return graph, {}


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
) -> str:
    """
    流式渲染与事务代理（UI Proxy）。
    完整接收流 → 非空校验 → 落盘 session_state → 可选状态同步。

    ⚠️ 本函数不创建 st.chat_message，由外层 sandbox_app.py 的 chat_message 容器包裹。
    调用方必须确保在 st.chat_message("assistant") 内调用本函数。

    参数说明：
    - enable_doorbell: DC0 放行路径，启用 [STATE_CHANGED] 门铃机制
    - legacy_status_sync: 机制检定路径，启用旧系统 <STATUS_UPDATE> 同步
    - sync_target: 旧系统同步目标角色名
    - parsed_intent: 意图解析结果（用于 UI 展示）
    """
    full_response = ""
    need_rerun = False

    placeholder = st.empty()
    try:
        # ---- 1. 完整缓存模型响应，不在原始流中暴露内部控制符 ----
        for chunk in raw_stream_generator:
            if chunk:
                full_response += chunk

        if not full_response.strip():
            raise ValueError("空数据流")

        display_response = _strip_hidden_control_text(full_response)
        placeholder.markdown(display_response)

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
            display_response = _strip_hidden_control_text(display_response)
            placeholder.markdown(display_response)

        # ---- 4. 落盘 working_graph ----
        st.session_state["major_graph"] = working_graph

        # ---- 5. 日志记录 ----
        if sync_entry:
            st.session_state.setdefault("sync_log", []).append(sync_entry)
        if mech_entry:
            st.session_state.setdefault("mechanics_log", []).append(mech_entry)

        # ---- 6. 门铃后置状态提炼（DC0 放行路径） ----
        if enable_doorbell and doorbell_triggered:
            try:
                with st.spinner("门铃触发：正在提炼叙事状态变更..."):
                    patched_graph, patch_json = extract_narrative_state_patch(
                        display_response,
                        working_graph,
                        active_scene or [],
                        pc_name,
                        active_stage_names,
                    )
                if patch_json:
                    working_graph = patched_graph
                    st.session_state["major_graph"] = working_graph
                    st.session_state.setdefault("sync_log", []).append({
                        "scene": st.session_state.get("scene_index", 1),
                        "target": pc_name,
                        "source": "doorbell_state_extract",
                        "changes": patch_json,
                    })
                    st.toast("门铃后置状态已同步至图谱")
                    need_rerun = True
            except Exception as patch_exc:
                st.warning(f"门铃后置提炼落盘失败，叙事文本已保留：{patch_exc}")

        # ---- 7. 旧系统 STATUS_UPDATE 同步（机制检定路径） ----
        if legacy_status_sync and display_response:
            status_match = re.search(r'<STATUS_UPDATE:\s*(.+?)>', full_response)
            if status_match:
                legacy_sync_target = status_match.group(1).strip()
                # 从文本中物理抹除标记
                display_response = re.sub(r'<STATUS_UPDATE:\s*(.+?)>', '', display_response).strip()
                placeholder.markdown(display_response)

                perceived_text = f"【玩家声明动作】：{st.session_state.get('_last_user_input', '')}\n【剧情演变结果】：{display_response}"
                if perceived_text.strip() and len(display_response.strip()) > 2:
                    with st.spinner("系统感知到剧情突变，动态图谱落盘中..."):
                        from core_engine import sandbox_sync_dynamic_status
                        st.session_state.major_graph, raw_json = sandbox_sync_dynamic_status(
                            perceived_text,
                            legacy_sync_target or sync_target or pc_name,
                            st.session_state.major_graph,
                            active_scene or [],
                            active_stage_names or [],
                            pc_name,
                        )
                        if raw_json:
                            st.session_state.setdefault("sync_log", []).append({
                                "scene": st.session_state.get("scene_index", 1),
                                "target": legacy_sync_target or sync_target or pc_name,
                                "changes": raw_json,
                            })
                    st.toast(f"角色 {legacy_sync_target or sync_target or pc_name} 身心状态已同步")
            else:
                # 机制检定但无 STATUS_UPDATE 标记：仍然尝试战后伤情同步
                if display_response and len(display_response.strip()) > 2:
                    with st.spinner("战后伤情与状态落盘中..."):
                        from core_engine import sandbox_sync_dynamic_status
                        st.session_state.major_graph, raw_json_combat = sandbox_sync_dynamic_status(
                            display_response,
                            sync_target or pc_name,
                            st.session_state.major_graph,
                            active_scene or [],
                            active_stage_names or [],
                            pc_name,
                        )
                        if raw_json_combat:
                            st.session_state.setdefault("sync_log", []).append({
                                "scene": st.session_state.get("scene_index", 1),
                                "target": sync_target or pc_name,
                                "changes": raw_json_combat,
                            })
                    st.toast("角色身心状态已根据战斗结果同步！")

        # ---- 8. 提取建议 ----
        suggestions = _extract_suggestions(full_response)

        return display_response, need_rerun, suggestions

    except Exception as exc:
        placeholder.empty()
        st.error(f"沙盒回合事务失败，已回滚本回合渲染与补丁提交：{exc}")
        return "", False, []
