# -*- coding: utf-8 -*-
"""
turn_engine.py — 回合总控引擎

【设计哲学】
- LLM 是世界的造物主，Python 是书记员和算盘。
- 意图解析由 LLM 自由语义理解（intent_engine）
- 数值检定使用旧系统的多乘区公式（通过 rules/adjudication_utils 模块化调用）
- 状态同步使用门铃机制（LLM 自由创作后，Python 事后提炼）
- 事务安全：deepcopy + Buffer Flush + 失败回滚

【核心流程】
1. 预扫描 → NPC 提前初始化六维
2. intent_engine → LLM 语义理解 + 物品流转 + 风险判断
3. Python 确定性校验 → 展示校验结果
4. is_risk=false → DC0 放行 + 门铃指令
5. is_risk=true → rules/adjudication_utils.run_standard_adjudication() → 多乘区检定
6. core_engine.generate_chat_stream() → LLM 自由创作
7. render_stream_and_commit() → 流式渲染 + 事务提交
"""

from __future__ import annotations

import json
import random
import re
import streamlit as st
from copy import deepcopy
from config import MODEL_FLASH


def _same_entity_name(a, b):
    """实体名精确规范化比较：去空格、大小写不敏感。"""
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def _ensure_pc_default_capabilities(working_graph, pc_name):
    """确保主角至少拥有默认基础能力，避免被 NPC 初始化逻辑误补全。"""
    entities = working_graph.setdefault("entities", {})
    pc = entities.setdefault(pc_name, {
        "desc": "世界的变数",
        "tags": ["玩家"],
        "1_relational_facts": {},
        "2_dynamic_status": {
            "physical": {"desc": "健康", "multiplier": 1.0},
            "mental": {"desc": "平静", "multiplier": 1.0},
        },
        "4_experience_factors": {"general_combat": 1.0, "specific_match": {}},
        "5_traits": [],
        "6_inventory": {},
    })
    pc.setdefault("tags", [])
    if "玩家" not in pc["tags"]:
        pc["tags"].append("玩家")
    caps = pc.setdefault("3_capabilities", {})
    caps.setdefault("基础行动", {
        "base_power": 10,
        "mastery_level": 1.0,
        "domains": ["通用", "徒手", "本能"],
        "features": ["无需训练的本能动作"],
    })
    caps.setdefault("本能闪避", {
        "base_power": 12,
        "mastery_level": 1.0,
        "domains": ["防御", "身法", "本能"],
        "features": ["下意识的躲闪反应"],
    })
    return working_graph


def _run_precheck_and_validation(user_input, active_scene, working_graph, real_pc_name, secondary_match=None):
    """
    执行意图解析 + Python 确定性校验。
    返回 (intent_result, parsed_intent, bypass_dc0, working_graph, validation_results, validation_injection)
    
    secondary_match: 二次判断的能力匹配结果 {NPC名: 能力名}
    """
    from intent_engine import parse_and_adjudicate_intent

    # ---- 1. LLM 语义意图解析 + 物品自动流转 ----
    minor_npcs = st.session_state.get("minor_npcs", {})
    env_assets = st.session_state.get("environment_assets", {})

    intent_result = parse_and_adjudicate_intent(
        user_input,
        active_scene,
        working_graph,
        minor_npcs,
        env_assets,
        pc_name=real_pc_name,
    )

    working_graph = intent_result.get("major_graph", working_graph)
    parsed_intent = intent_result.get("parsed_intent", {})
    bypass_dc0 = bool(intent_result.get("bypass_mechanics"))

    # ---- 1.3 应用二次判断结果 ----
    # 如果意图解析没有识别到能力，但二次判断有结果，使用二次判断
    if not parsed_intent.get("detected_ability") and secondary_match:
        initiator = parsed_intent.get("initiator_entity")
        if initiator and initiator in secondary_match:
            parsed_intent["detected_ability"] = secondary_match[initiator]
            parsed_intent["_secondary_matched"] = True

    # ---- 1.5 Python 确定性校验（外置大脑）----
    creative_mode = st.session_state.get("creative_mode", False)
    pc_inventory = working_graph.get("entities", {}).get(real_pc_name, {}).get("6_inventory", {})
    pc_capabilities = working_graph.get("entities", {}).get(real_pc_name, {}).get("3_capabilities", {})

    validation_results = []
    validation_injection = ""

    # 校验 lost_items
    lost_items = parsed_intent.get("lost_items", [])
    valid_lost = []
    invalid_lost = []
    for item in lost_items:
        if item in pc_inventory:
            valid_lost.append(item)
            validation_results.append(("✓", f"「{item}」", "已从背包移除"))
        else:
            invalid_lost.append(item)
            if not creative_mode:
                validation_results.append(("✗", f"「{item}」", "背包中不存在"))
            else:
                validation_results.append(("⚠", f"「{item}」", "创造模式：允许移除不存在的物品"))

    if invalid_lost and not creative_mode:
        parsed_intent["lost_items"] = valid_lost
        validation_injection += f"\n【系统校验】：玩家背包中不存在「{', '.join(invalid_lost)}」。请在叙事中自然反映：玩家试图使用这些物品但找不到。其余动作正常执行。\n"

    # 校验 obtained_items（创造模式下跳过）
    obtained_items = parsed_intent.get("obtained_items", [])
    if obtained_items and not creative_mode:
        absurd_items = []
        absurd_keywords = ["一座山", "整个城市", "整个世界", "所有", "无限", "全部"]
        for item in obtained_items:
            for kw in absurd_keywords:
                if kw in item:
                    absurd_items.append(item)
                    validation_results.append(("✗", f"「{item}」", "超出物理合理性"))
                    break
        if absurd_items:
            parsed_intent["obtained_items"] = [i for i in obtained_items if i not in absurd_items]
            validation_injection += f"\n【系统校验】：以下物品超出物理合理性：「{', '.join(absurd_items)}」，无法获得。请在叙事中反映这一限制。\n"

    # 校验能力使用（非创造模式下）
    detected_ability = parsed_intent.get("detected_ability")
    ability_invalid = False
    if detected_ability and detected_ability not in ["None", "null", "NULL"] and not creative_mode and not bypass_dc0:
        # 确定发起方是谁，检查发起方的能力列表
        initiator_name = parsed_intent.get("initiator_entity") or real_pc_name
        initiator_caps = working_graph.get("entities", {}).get(initiator_name, {}).get("3_capabilities", {})

        if detected_ability not in initiator_caps:
            validation_results.append(("✗", f"能力「{detected_ability}」", f"{initiator_name}未掌握此能力"))
            validation_injection += f"\n【系统校验】：{initiator_name}未掌握能力「{detected_ability}」。请在叙事中反映：角色试图使用不熟悉的能力，效果受限或失败。\n"
            ability_invalid = True
            parsed_intent["detected_ability"] = None
            parsed_intent["_ability_invalid"] = True

    return intent_result, parsed_intent, bypass_dc0, working_graph, validation_results, validation_injection


def execute_sandbox_turn(
    user_input: str,
    active_scene: list,
    context_text: str = "",
) -> tuple[str, bool]:
    """
    沙盒并网总路由：意图解析 → 校验展示 → 机制分流 → 叙事流式生成 → 延迟提交。
    返回 (display_response, need_rerun)
    """
    from turn_runtime import (
        DOORBELL_NARRATIVE_INSTRUCTION,
        render_stream_and_commit,
    )
    from core_engine import (
        generate_chat_stream,
        init_npc_combat_stats,
        get_current_world_anchor_text,
        get_user_client,
    )
    from rules.adjudication_utils import run_standard_adjudication

    # ---- 0. deepcopy 保护原始图谱 ----
    working_graph = deepcopy(st.session_state.get("major_graph", {"entities": {}, "relations": []}))
    real_pc_name = st.session_state.get("pc_name", "主角")
    working_graph = _ensure_pc_default_capabilities(working_graph, real_pc_name)

    # ---- 0.5 预扫描：从用户输入中提取可能的实体名，提前初始化六维 ----
    anchor_text_pre = get_current_world_anchor_text(
        st.session_state.get("world_category", "异能"),
        st.session_state.world_tier
    )
    pre_scan_prompt = f"""从以下玩家输入中，提取所有提到的人名/角色名（不包括玩家自己）。
注意：玩家名是"{real_pc_name}"，此名在任何变体下都不应被提取。
只输出 JSON 数组，如 ["张三"] 或 []。禁止输出其它文字。
玩家输入：{user_input}"""
    try:
        pre_client = get_user_client()
        if pre_client:
            pre_resp = pre_client.chat.completions.create(
                model=MODEL_FLASH,
                messages=[{"role": "system", "content": pre_scan_prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            pre_raw = pre_resp.choices[0].message.content.strip()
            pre_match = re.search(r'\[.*?\]', pre_raw, re.DOTALL)
            if pre_match:
                pre_names = json.loads(pre_match.group(0))
                for name in pre_names:
                    name = str(name).strip()
                    # 精确过滤主角名（大小写不敏感、去空格）
                    if not name or _same_entity_name(name, real_pc_name) or name in ["环境", "None", "null"]:
                        continue
                    if name not in working_graph.get("entities", {}) or not working_graph["entities"].get(name, {}).get("3_capabilities"):
                            with st.spinner(f"检测到新角色【{name}】，正在初始化六维数据..."):
                                working_graph = init_npc_combat_stats(
                                    name, active_scene, working_graph, anchor_text_pre
                                )
    except Exception:
        pass

    # ---- 0.8 二次判断：预扫描后重新匹配能力 ----
    # 如果意图解析阶段没有识别到能力，用 FLASH 从 NPC 能力中匹配
    # 注意：这里只是预匹配，真正的意图解析在下一步
    _secondary_ability_match = {}
    try:
        pre_client = get_user_client()
        if pre_client:
            # 收集所有 NPC（非玩家）的能力
            npc_caps = {}
            for e_name, e_data in working_graph.get("entities", {}).items():
                if _same_entity_name(e_name, real_pc_name):
                    continue  # 跳过玩家自己
                caps = e_data.get("3_capabilities", {})
                if caps:
                    npc_caps[e_name] = list(caps.keys())
            
            if npc_caps:
                secondary_prompt = f"""从以下玩家输入中，判断每个 NPC 使用了什么能力。
NPC 及其能力列表：{json.dumps(npc_caps, ensure_ascii=False)}
玩家输入：{user_input}

只输出 JSON 对象，格式如 {{"NPC名": "能力名"}}。如果无法判断，输出 {{}}。
禁止输出其它文字。"""
                sec_resp = pre_client.chat.completions.create(
                    model=MODEL_FLASH,
                    messages=[{"role": "system", "content": secondary_prompt}],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                sec_raw = sec_resp.choices[0].message.content.strip()
                _secondary_ability_match = json.loads(sec_raw)
    except Exception:
        pass

    # ---- 1. 意图解析 + Python 确定性校验 ----
    intent_result, parsed_intent, bypass_dc0, working_graph, validation_results, validation_injection = \
        _run_precheck_and_validation(user_input, active_scene, working_graph, real_pc_name, _secondary_ability_match)

    # ---- 1.6 展示校验结果（在流式渲染之前）----
    if validation_results:
        with st.expander("📋 系统校验结果", expanded=True):
            for status, item, msg in validation_results:
                if status == "✓":
                    st.success(f"{status} {item} — {msg}")
                elif status == "✗":
                    st.error(f"{status} {item} — {msg}")
                elif status == "⚠":
                    st.warning(f"{status} {item} — {msg}")

    # ---- 2. 分流：DC0 放行 vs 机制检定 ----
    enriched_context = context_text or ""
    system_injection = ""
    sync_target = real_pc_name

    # 门铃指令注入 + 校验注入
    enriched_context += DOORBELL_NARRATIVE_INSTRUCTION
    if validation_injection:
        enriched_context += validation_injection

    # 创造模式：注入额外提示词让 LLM 更顺从玩家
    creative_mode = st.session_state.get("creative_mode", False)
    if creative_mode:
        enriched_context += (
            "\n【创造模式已激活】：当前处于创造模式，请最大化满足玩家的想象力和创造力。"
            "不要以物理法则或逻辑限制为由拒绝玩家的行为，尽可能让玩家的奇思妙想在叙事中成真。\n"
        )

    if bypass_dc0:
        injection = intent_result.get("narrative_injection", "")
        if injection:
            enriched_context += injection
    else:
        # ---- 3. 机制检定：桥接旧系统多乘区公式 ----
        action_type = parsed_intent.get("action_category", "combat")
        initiator = parsed_intent.get("initiator_entity") or real_pc_name
        ability = parsed_intent.get("detected_ability")
        target = parsed_intent.get("target_entity")
        target_ongoing = parsed_intent.get("target_ongoing_action")
        init_assets = parsed_intent.get("initiator_matched_assets", [])
        tgt_assets = parsed_intent.get("target_matched_assets", [])

        anchor_text = get_current_world_anchor_text(
            st.session_state.get("world_category", "异能"),
            st.session_state.world_tier
        )

        if _same_entity_name(initiator, real_pc_name):
            working_graph = _ensure_pc_default_capabilities(working_graph, real_pc_name)
        elif initiator not in working_graph.get("entities", {}) or not working_graph["entities"].get(initiator, {}).get("3_capabilities"):
            with st.spinner(f"检测到新角色【{initiator}】，正在初始化六维数据..."):
                working_graph = init_npc_combat_stats(
                    initiator, active_scene, working_graph, anchor_text
                )
        if target and target not in ["环境", "None", "null"]:
            if _same_entity_name(target, real_pc_name):
                working_graph = _ensure_pc_default_capabilities(working_graph, real_pc_name)
            elif target not in working_graph.get("entities", {}) or not working_graph["entities"].get(target, {}).get("3_capabilities"):
                with st.spinner(f"检测到新角色【{target}】，正在初始化六维数据..."):
                    working_graph = init_npc_combat_stats(
                        target, active_scene, working_graph, anchor_text
                    )

        system_injection = run_standard_adjudication(
            action_type=action_type,
            initiator_assets=init_assets,
            target_assets=tgt_assets,
            world_anchor_text=anchor_text,
            ability_name=ability,
            initiator_name=initiator,
            target_name=target,
            target_ongoing_action=target_ongoing,
            major_graph=working_graph,
            is_social=(action_type == "social"),
            ability_invalid=parsed_intent.get("_ability_invalid", False),
        )

        enriched_context += system_injection
        sync_target = target if (target and target != "None") else initiator

    # ---- 4. LLM 自由创作（流式）----
    # 将校验注入作为独立参数传递，确保不被长上下文淹没
    raw_stream = generate_chat_stream(
        enriched_context, active_scene,
        override_tail=validation_injection if validation_injection else None,
    )

    # ---- 5. 组装日志 ----
    sync_entry = None
    changes_dict = {}
    if intent_result.get("inventory_self_healed"):
        changes_dict["自愈新增"] = intent_result["inventory_self_healed"]
    if intent_result.get("inventory_lost"):
        changes_dict["行为销毁"] = intent_result["inventory_lost"]
    if changes_dict:
        sync_entry = {
            "scene": st.session_state.get("scene_index", 1),
            "target": real_pc_name,
            "changes": changes_dict,
        }

    mech_entry = None
    if not bypass_dc0:
        mech_entry = {
            "scene": st.session_state.get("scene_index", 1),
            "action": parsed_intent.get("intended_action", "unknown"),
            "target": f"{parsed_intent.get('initiator_entity', real_pc_name)} -> {parsed_intent.get('target_entity', '环境')}",
            "log": system_injection,
            "raw_intent": parsed_intent,
        }

    # ---- 6. 流式渲染 + 事务提交 ----
    return render_stream_and_commit(
        raw_stream,
        state_patch=None,
        working_graph=working_graph,
        pc_name=real_pc_name,
        sync_entry=sync_entry,
        mech_entry=mech_entry,
        enable_doorbell=True,
        active_scene=active_scene,
        active_stage_names=st.session_state.get("active_stage", []),
        legacy_status_sync=not bypass_dc0,
        sync_target=sync_target if not bypass_dc0 else None,
        parsed_intent=parsed_intent if not bypass_dc0 else None,
    )
