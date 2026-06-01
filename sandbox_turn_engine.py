# -*- coding: utf-8 -*-
"""
sandbox_turn_engine.py — 沙盒版本回合总控引擎

================================================================================
🔔 AI 助手维护提醒（每次修改前必读）
================================================================================

【沙盒版本绝对隔离原则】
- 本文件是 turn_engine.py 的 1:1 沙盒镜像副本
- 所有导入必须指向 sandbox_ 前缀版本
- 禁止直接调用主版本（turn_engine.py, core_engine.py 等）
- 沙盒修改不得污染主版本管线

【修改步骤】
1. 如需修改功能，先在此沙盒版本测试验证
2. 验证通过后，将修改实质迁移到主版本
3. 不要简单让主版本跳转到沙盒版本

【文件对应关系】
- sandbox_turn_engine.py ↔ turn_engine.py
- sandbox_core_engine.py ↔ core_engine.py  
- sandbox_intent_engine.py ↔ intent_engine.py
- sandbox_turn_runtime.py ↔ turn_runtime.py
- sandbox_memory_manager.py ↔ memory_manager.py
- sandbox_rules/ ↔ rules/

================================================================================

【设计哲学】
- LLM 是世界的造物主，Python 是书记员和算盘。
- 意图解析由 LLM 自由语义理解（sandbox_intent_engine）
- 数值检定使用多乘区公式（通过 sandbox_rules/adjudication_utils）
- 状态同步使用门铃机制（LLM 自由创作后，Python 事后提炼）
- 事务安全：deepcopy + Buffer Flush + 失败回滚

【核心流程】
1. 预扫描 → NPC 提前初始化六维
2. sandbox_intent_engine → LLM 语义理解 + 物品流转 + 风险判断
3. Python 确定性校验 → 展示校验结果
4. is_risk=false → DC0 放行 + 门铃指令
5. is_risk=true → sandbox_rules/adjudication_utils → 多乘区检定
6. sandbox_core_engine.generate_chat_stream() → LLM 自由创作
7. sandbox_turn_runtime.render_stream_and_commit() → 流式渲染 + 事务提交
"""

from __future__ import annotations

import json
import random
import re
import streamlit as st
from copy import deepcopy
from sandbox_config import MODEL_FLASH


def _same_entity_name(a, b):
    """实体名精确规范化比较：去空格、大小写不敏感。"""
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def _find_entity_annotation(name, entity_annotations):
    """根据 LLM 输出的本体分类寻找实体注释；不使用关键词黑白名单。"""
    token = str(name or "").strip()
    if not token or not isinstance(entity_annotations, list):
        return None
    for annotation in entity_annotations:
        if not isinstance(annotation, dict):
            continue
        ann_name = str(annotation.get("name", "")).strip()
        canonical_name = str(annotation.get("canonical_name", "")).strip()
        if (ann_name and _same_entity_name(ann_name, token)) or (canonical_name and _same_entity_name(canonical_name, token)):
            return annotation
    return None


def _canonical_entity_name(name, entity_annotations):
    annotation = _find_entity_annotation(name, entity_annotations)
    if not annotation:
        return str(name or "").strip()
    return str(annotation.get("canonical_name") or annotation.get("name") or name).strip()


def _should_initialize_entity_as_npc(name, entity_annotations):
    """只依据结构化本体分类决定是否初始化 NPC；未知实体默认不污染核心图谱。"""
    token = str(name or "").strip()
    if not token or token in {"环境", "None", "null"}:
        return False
    annotation = _find_entity_annotation(token, entity_annotations)
    if not annotation:
        return False
    return bool(annotation.get("should_initialize_npc") is True and annotation.get("entity_type") == "character")


def _collect_blocked_targets(parsed_obj: dict) -> set[str]:
    """从 action_constraints 中收集 target_exists: false 的实体名"""
    blocked = set()
    for action in (parsed_obj.get("action_sequence", []) if isinstance(parsed_obj, dict) else []):
        ac = action.get("action_constraints") if isinstance(action, dict) else None
        if isinstance(ac, dict) and ac.get("target_exists") is False:
            blocked.add(str(action.get("target", "")).strip())
    return blocked


def _is_target_blocked(name: str, entity_annotations: list, blocked_targets: set[str]) -> bool:
    """检查实体是否被 action_constraints 标记为不存在"""
    if name in blocked_targets:
        return True
    canonical = str(_find_entity_annotation(name, entity_annotations).get("canonical_name", name) if _find_entity_annotation(name, entity_annotations) else name).strip()
    return canonical in blocked_targets


def _is_entity_mentioned_in_scene(entity_name: str, active_scene) -> bool:
    """检查实体名是否在当前叙事文本中实际出现（防 LLM 幻觉初始化）"""
    if not active_scene:
        return False
    if isinstance(active_scene, list):
        scene_text = "".join(str(item) for item in active_scene)
    else:
        scene_text = str(active_scene)
    return entity_name in scene_text


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
        "7_held_items": {},
    })
    pc.setdefault("6_inventory", {})
    pc.setdefault("7_held_items", {})
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
    from sandbox_intent_engine import parse_and_adjudicate_intent

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
    pc_held = working_graph.get("entities", {}).get(real_pc_name, {}).get("7_held_items", {})
    for item in lost_items:
        if item in pc_inventory:
            valid_lost.append(item)
            validation_results.append(("✓", f"「{item}」", "已从背包移除"))
        elif item in pc_held:
            valid_lost.append(item)
            validation_results.append(("✓", f"「{item}」", "已从手持物移除"))
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
    from sandbox_turn_runtime import (
        DOORBELL_NARRATIVE_INSTRUCTION,
        render_stream_and_commit,
    )
    from sandbox_core_engine import (
        generate_chat_stream,
        init_npc_combat_stats,
        get_current_world_anchor_text,
        get_user_client,
    )
    from sandbox_rules.adjudication_utils import run_standard_adjudication

    # ---- 0. deepcopy 保护原始图谱 ----
    working_graph = deepcopy(st.session_state.get("major_graph", {"entities": {}, "relations": []}))
    real_pc_name = st.session_state.get("pc_name", "主角")
    working_graph = _ensure_pc_default_capabilities(working_graph, real_pc_name)

    # ---- 0.5 预扫描：结构化实体本体分类，提前初始化真正的角色 ----
    anchor_text_pre = get_current_world_anchor_text(
        st.session_state.get("world_category", "异能"),
        st.session_state.world_tier
    )
    pre_scan_prompt = f"""从以下玩家输入中，提取可能需要进入长期角色图谱的实体，并进行本体分类。
注意：玩家名是"{real_pc_name}"，此名在任何变体下都不应被提取。
请输出 JSON 对象，格式：
{{
  "entity_annotations": [
    {{
      "name": "实体名",
      "entity_type": "character/object/location_feature/environment/concept/unknown",
      "role_in_action": "actor/opponent/target/tool/temporary_tool/obstacle/terrain/hazard/loot/context/unknown",
      "persistence": "persistent/scene_bound/ephemeral/unknown",
      "should_initialize_npc": true或false,
      "reason": "一句话说明"
    }}
  ]
}}

只有具备自主意志、行动能力、可作为对抗者/交互角色长期存在的实体，才允许 should_initialize_npc=true。
场景结构、临时道具、可拾取物、环境现象、抽象概念即使被动作影响，也不得初始化为 NPC。
禁止输出其它文字。
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
            pre_obj = json.loads(pre_raw)
            pre_annotations = pre_obj.get("entity_annotations", []) if isinstance(pre_obj, dict) else []
            blocked_targets = _collect_blocked_targets(pre_obj)
            for annotation in pre_annotations:
                if not isinstance(annotation, dict):
                    continue
                name = str(annotation.get("name", "")).strip()
                if _same_entity_name(name, real_pc_name) or not _should_initialize_entity_as_npc(name, pre_annotations):
                        continue
                if _is_target_blocked(name, pre_annotations, blocked_targets):
                    continue
                if not _is_entity_mentioned_in_scene(name, active_scene):
                    continue
                name = _canonical_entity_name(name, pre_annotations)
                if name not in working_graph.get("entities", {}) or not working_graph["entities"].get(name, {}).get("3_capabilities"):
                    with st.spinner(f"检测到新角色【{name}】，正在初始化六维数据..."):
                        working_graph = init_npc_combat_stats(
                            name, active_scene, working_graph, anchor_text_pre
                        )
    except Exception:
        pass

    # ---- 0.8 二次判断：预扫描后重新匹配能力 ----
    _secondary_ability_match = {}
    try:
        pre_client = get_user_client()
        if pre_client:
            npc_caps = {}
            for e_name, e_data in working_graph.get("entities", {}).items():
                if _same_entity_name(e_name, real_pc_name):
                    continue
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
    complex_state_patch = None
    complex_result = None

    enriched_context += DOORBELL_NARRATIVE_INSTRUCTION
    if validation_injection:
        enriched_context += validation_injection

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
        # ---- 3. 机制检定：桥接多乘区公式 ----
        action_type = parsed_intent.get("action_category", "combat")
        initiator = parsed_intent.get("initiator_entity") or real_pc_name
        ability = parsed_intent.get("detected_ability")
        target = parsed_intent.get("target_entity")
        target_ongoing = parsed_intent.get("target_ongoing_action")
        init_assets = parsed_intent.get("initiator_matched_assets", [])
        tgt_assets = parsed_intent.get("target_matched_assets", [])
        entity_annotations = parsed_intent.get("entity_annotations", [])
        initiator = _canonical_entity_name(initiator, entity_annotations)
        target = _canonical_entity_name(target, entity_annotations)

        anchor_text = get_current_world_anchor_text(
            st.session_state.get("world_category", "异能"),
            st.session_state.world_tier
        )

        blocked_targets = _collect_blocked_targets(parsed_intent)

        if _same_entity_name(initiator, real_pc_name):
            working_graph = _ensure_pc_default_capabilities(working_graph, real_pc_name)
        elif _should_initialize_entity_as_npc(initiator, entity_annotations) and (initiator not in working_graph.get("entities", {}) or not working_graph["entities"].get(initiator, {}).get("3_capabilities")):
            if not _is_target_blocked(initiator, entity_annotations, blocked_targets):
                if not _is_entity_mentioned_in_scene(initiator, active_scene):
                    pass
                else:
                    with st.spinner(f"检测到新角色【{initiator}】，正在初始化六维数据..."):
                        working_graph = init_npc_combat_stats(
                            initiator, active_scene, working_graph, anchor_text
                        )
        if target and _should_initialize_entity_as_npc(target, entity_annotations):
            if _same_entity_name(target, real_pc_name):
                working_graph = _ensure_pc_default_capabilities(working_graph, real_pc_name)
            elif target not in working_graph.get("entities", {}) or not working_graph["entities"].get(target, {}).get("3_capabilities"):
                if not _is_target_blocked(target, entity_annotations, blocked_targets):
                    if not _is_entity_mentioned_in_scene(target, active_scene):
                        pass
                    else:
                        with st.spinner(f"检测到新角色【{target}】，正在初始化六维数据..."):
                            working_graph = init_npc_combat_stats(
                                target, active_scene, working_graph, anchor_text
                            )

        action_sequence = parsed_intent.get("action_sequence") or []
        if action_sequence:
            for action in action_sequence:
                actor_name = action.get("actor") or real_pc_name
                target_name = action.get("target")
                for entity_name in [actor_name, target_name]:
                    entity_name = _canonical_entity_name(entity_name, entity_annotations)
                    if _same_entity_name(entity_name, real_pc_name):
                        working_graph = _ensure_pc_default_capabilities(working_graph, real_pc_name)
                    elif _should_initialize_entity_as_npc(entity_name, entity_annotations) and (entity_name not in working_graph.get("entities", {}) or not working_graph["entities"].get(entity_name, {}).get("3_capabilities")):
                        if not _is_target_blocked(entity_name, entity_annotations, blocked_targets):
                            if not _is_entity_mentioned_in_scene(entity_name, active_scene):
                                pass
                            else:
                                with st.spinner(f"检测到复合动作角色【{entity_name}】，正在初始化六维数据..."):
                                    working_graph = init_npc_combat_stats(entity_name, active_scene, working_graph, anchor_text)

            from sandbox_rules.complex_encounter import ComplexEncounterResolver
            complex_result = ComplexEncounterResolver().resolve(
                action_sequence,
                working_graph,
                real_pc_name,
                anchor_text,
                active_scene=active_scene,
                entity_annotations=parsed_intent.get("entity_annotations"),
            )
            system_injection = complex_result.get("system_injection", "")
            complex_state_patch = complex_result.get("state_patch")

            # 回溯清理
            for annotation in entity_annotations:
                if not isinstance(annotation, dict):
                    continue
                if annotation.get("should_initialize_npc") is False:
                    name = str(annotation.get("name", "")).strip()
                    canonical = str(annotation.get("canonical_name", name)).strip()
                    for n in [name, canonical]:
                        if n and n in working_graph.get("entities", {}):
                            del working_graph["entities"][n]

            # 检查是否所有子动作都因约束失败
            all_failed = complex_result.get("all_actions_constraint_failed")
            if all_failed and not creative_mode:
                action_results = complex_result.get("action_results", {})
                reasons = []
                for aid, ares in action_results.items():
                    if ares.get("constraint_violation"):
                        scene_note = ares.get("scene_note", "")
                        if scene_note:
                            reasons.append(scene_note)
                reason_text = "\n".join(f"- {r}" for r in reasons) if reasons else "世界法则拒绝"
                st.error(f"**天意拒绝了你，请调整你的行动。**\n\n{reason_text}\n\n如果执意想要行动，请开启**上帝模式**。**")
                return

            enriched_context += system_injection
            enriched_context += "\n【复合动作叙事载荷】\n"
            enriched_context += json.dumps(complex_result.get("narrative_payload", {}), ensure_ascii=False, indent=2)
            enriched_context += "\n"
        else:
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

        if not action_sequence:
            enriched_context += system_injection
        sync_target = target if (target and target != "None") else initiator

    # ---- 4. LLM 自由创作（流式）----
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
        action_title = parsed_intent.get("intended_action") or parsed_intent.get("action_label") or "unknown"
        mech_entry = {
            "scene": st.session_state.get("scene_index", 1),
            "action": action_title,
            "target": f"{parsed_intent.get('initiator_entity', real_pc_name)} -> {parsed_intent.get('target_entity', '环境')}",
            "log": system_injection,
            "raw_intent": parsed_intent,
        }
        if complex_result:
            mech_entry["complex_action_results"] = complex_result.get("action_results", {})
            mech_entry["complex_debug_log"] = complex_result.get("debug_log", [])
        if complex_state_patch:
            mech_entry["held_item_changes"] = complex_state_patch.get("held_item_changes", {})
            mech_entry["inventory_changes"] = complex_state_patch.get("inventory_changes", {})

    # ---- 6. 流式渲染 + 事务提交 ----
    return render_stream_and_commit(
        raw_stream,
        state_patch=complex_state_patch,
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
        suppress_inventory_sync=bool(complex_state_patch),
    )
