# -*- coding: utf-8 -*-
"""
sandbox_core_engine.py — 沙盒桥接引擎

【设计哲学】
- LLM 是世界的造物主，Python 是书记员和算盘。
- 意图解析由 LLM 自由语义理解（sandbox_intent_parser）
- 数值检定使用旧系统的多乘区公式（通过 rules/adjudication_utils 模块化调用）
- 状态同步使用门铃机制（LLM 自由创作后，Python 事后提炼）
- 事务安全：deepcopy + Buffer Flush + 失败回滚

【核心流程】
1. 预扫描 → NPC 提前初始化六维
2. sandbox_intent_parser → LLM 语义理解 + 物品流转 + 风险判断
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
import time
import streamlit as st
from copy import deepcopy
from openai import OpenAI
from supabase import create_client, Client
from config import MODEL_FLASH, MODEL_PRO, API_BASE_URL, DEBUG_MODE


@st.cache_resource
def get_sandbox_supabase_client() -> Client:
    """沙盒版 Supabase 客户端。"""
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


try:
    sandbox_db_client = get_sandbox_supabase_client()
except Exception:
    sandbox_db_client = None


_cached_openai_client = None
_cached_api_key = None


def get_user_client():
    """沙盒版用户 OpenAI 客户端，key 不变时复用连接实例。"""
    global _cached_openai_client, _cached_api_key
    key = st.session_state.get("user_api_key", "")
    if not key or not key.startswith("sk-"):
        return None
    if key == _cached_api_key and _cached_openai_client is not None:
        return _cached_openai_client
    _cached_openai_client = OpenAI(api_key=key, base_url=API_BASE_URL)
    _cached_api_key = key
    return _cached_openai_client


def get_current_world_anchor_text(category, setting_name):
    """沙盒版世界法则锚点读取；失败时返回兜底文本。"""
    try:
        if sandbox_db_client is None:
            raise RuntimeError("sandbox_db_client unavailable")
        res = sandbox_db_client.table("world_anchors_pool").select("anchor_data").eq("category", category).eq("setting_name", setting_name).execute()
        if res.data:
            anchor = res.data[0]["anchor_data"]
            return f"【当前世界法则】\n{chr(10).join(anchor.values())}"
    except Exception:
        pass
    return "【当前世界法则未初始化，按常规标准执行判定】"


def _get_auth_db():
    """获取沙盒认证/配置用数据库客户端。"""
    return sandbox_db_client


def _auth_table():
    """用户认证表名。保持和旧 UI 约定兼容。"""
    return "users_auth"


def login_user(username, password):
    """沙盒版 UI 登录接口；对齐原仓库 users_auth 实现。"""
    username = str(username or "").strip()
    password = str(password or "").strip()
    db = _get_auth_db()
    if not db:
        return False, "登录验证失败，请检查数据库连接。"
    try:
        res = db.table(_auth_table()).select("*").eq("username", username).execute()
        if res.data and res.data[0]["password"] == password:
            return True, "登录成功"
        return False, "用户名或密码错误"
    except Exception:
        return False, "登录验证失败，请检查数据库连接。"


def register_user(username, password, security_question, security_answer):
    """沙盒版 UI 注册接口；对齐原仓库 users_auth 实现。"""
    username = str(username or "").strip()
    password = str(password or "").strip()
    security_question = str(security_question or "").strip()
    security_answer = str(security_answer or "").strip()
    if not security_question or not security_answer:
        return False, "所有字段均不能为空。"
    if not username or not password:
        return False, "所有字段均不能为空。"
    db = _get_auth_db()
    if not db:
        return False, "数据库连接不可用，请检查 Supabase 配置。"
    try:
        db.table(_auth_table()).insert({
            "username": username,
            "password": password,
            "security_question": security_question,
            "security_answer": security_answer,
        }).execute()
        return True, "注册成功！"
    except Exception as e:
        if "duplicate key" in str(e):
            return False, "该用户名已被注册，请更换。"
        return False, f"注册失败: {str(e)}"


def get_security_question(username):
    """读取用户密保问题。"""
    username = str(username or "").strip()
    if not username:
        return None
    db = _get_auth_db()
    if not db:
        return None
    try:
        res = db.table(_auth_table()).select("security_question").eq("username", username).execute()
        if res.data:
            return res.data[0].get("security_question")
    except Exception:
        return None
    return None


def retrieve_password(username, security_answer):
    """通过密保答案找回密码。"""
    username = str(username or "").strip()
    security_answer = str(security_answer or "").strip()
    db = _get_auth_db()
    if not db:
        return False, "数据查询失败。"
    try:
        res = db.table(_auth_table()).select("password,security_answer").eq("username", username).execute()
        if res.data and res.data[0]["security_answer"] == security_answer:
            return True, res.data[0]["password"]
        return False, "密保答案错误。"
    except Exception:
        return False, "数据查询失败。"


def modify_password(username, old_password, new_password):
    """修改密码。"""
    ok, msg = login_user(username, old_password)
    if not ok:
        return False, "旧密码错误。"
    db = _get_auth_db()
    if not db:
        return False, "修改失败: 数据库连接不可用。"
    try:
        db.table(_auth_table()).update({"password": str(new_password or "").strip()}).eq("username", str(username or "").strip()).execute()
        return True, "密码修改成功。"
    except Exception as e:
        return False, f"修改失败: {str(e)}"


def rename_user_session(old_file, new_session_name):
    """重命名当前用户的云端存档。"""
    import memory_manager as memory_manager
    username = st.session_state.get("current_user")
    if not username:
        return False, "请先登录。"
    old_file = str(old_file or "").strip()
    new_name = str(new_session_name or "").strip()
    if not old_file or not new_name:
        return False, "旧存档名和新存档名不能为空。"
    new_file = new_name if new_name.endswith(".json") else f"{new_name}.json"
    db = memory_manager._get_db()
    if not db:
        return False, "数据库连接不可用。"
    try:
        db.table("user_sessions").update({"file_name": new_file}).eq("username", username).eq("file_name", old_file).execute()
        return True, new_file
    except Exception as e:
        return False, f"重命名失败：{e}"


def delete_user_session(file_name):
    """删除当前用户的云端存档。"""
    import memory_manager as memory_manager
    username = st.session_state.get("current_user")
    if not username:
        return False, "请先登录。"
    if not file_name:
        return False, "存档名不能为空。"
    db = memory_manager._get_db()
    if not db:
        return False, "数据库连接不可用。"
    try:
        db.table("user_sessions").delete().eq("username", username).eq("file_name", file_name).execute()
        return True, "删除成功。"
    except Exception as e:
        return False, f"删除失败：{e}"


def sync_world_anchor_and_scale(category, new_setting_name, major_graph):
    """重载世界观锚点；第一阶段保持图谱结构不强制缩放。"""
    try:
        anchor_text = get_current_world_anchor_text(category, new_setting_name)
        return True, {"anchor_text": anchor_text}, major_graph, "世界法则已重载。"
    except Exception as e:
        return False, {}, major_graph, f"世界重塑失败：{e}"


def build_context(memory, active_stage, *args, **kwargs):
    """构建沙盒 PRO 叙事上下文，兼容 UI 旧调用与完整调用。"""
    if len(args) >= 4 and isinstance(args[1], dict):
        # UI 旧调用: build_context(memory, active_stage, user_input, major_graph, minor_npcs, director_directive)
        user_input = args[0]
        major_graph = args[1]
        director_directive = args[3] if len(args) > 3 else ""
        current_location = st.session_state.get("current_location", "未知区域")
        pc_name = st.session_state.get("pc_name", "主角")
        gm_memory = st.session_state.get("gm_memory", "")
        world_tier = st.session_state.get("world_tier", "未知世界层级")
    else:
        major_graph = args[0] if len(args) > 0 else kwargs.get("major_graph", {})
        director_directive = args[2] if len(args) > 2 else kwargs.get("director_directive", "")
        current_location = args[3] if len(args) > 3 else kwargs.get("current_location", "未知区域")
        pc_name = args[4] if len(args) > 4 else kwargs.get("pc_name", "主角")
        gm_memory = args[5] if len(args) > 5 else kwargs.get("gm_memory", "")
        world_tier = args[6] if len(args) > 6 else kwargs.get("world_tier", "未知世界层级")
        user_input = kwargs.get("user_input", "")
    pc_data = major_graph.get("entities", {}).get(pc_name, {}) if isinstance(major_graph, dict) else {}
    stage_text = "、".join(active_stage or []) if active_stage else "无"
    gm_text = "\n".join(gm_memory) if isinstance(gm_memory, list) else str(gm_memory or "")
    return f"""你是一个遵循世界状态的TRPG叙事GM。
【世界层级】{world_tier}
【当前位置】{current_location}
【当前玩家】{pc_name}
【玩家本轮输入】{user_input or '无'}
【玩家数据】{json.dumps(pc_data, ensure_ascii=False)}
【在场实体】{stage_text}
【长期记忆】{memory or '无'}
【GM记忆】{gm_text or '无'}
【导演指令】{director_directive or '无'}
【叙事要求】延续当前剧情，只输出自然叙事，不泄露检定数值。"""


def extract_memory_summary(active_scene, scene_index):
    """从当前幕提取轻量记忆摘要。"""
    text = "\n".join([str(m.get("content", "")) for m in (active_scene or [])[-6:]])
    if not text.strip():
        return {"summary": "", "current_location": st.session_state.get("current_location", "未知区域"), "current_tension": 0, "gm_memory": ""}
    return {"summary": f"第{scene_index}幕摘要：{text[-500:]}", "current_location": st.session_state.get("current_location", "未知区域"), "current_tension": 1, "gm_memory": ""}


def generate_ai_suggestions(active_scene, major_graph, pc_name, current_location=None, world_tier=None):
    """生成 UI 动作建议。"""
    return ["观察周围环境", "询问附近人物", "检查自身状态"]


def generate_chat_stream(context_text, active_scene, override_tail=None):
    """沙盒版 PRO 流式叙事生成器。"""
    if DEBUG_MODE:
        time.sleep(0.5)
        for word in list("【DEBUG模式-PRO】测试回复。"):
            yield word
            time.sleep(0.05)
        return

    runtime_messages = [{"role": "system", "content": context_text}]
    runtime_messages.extend(active_scene)

    tail_instruction = "【最高执行协议】：若本次回复推演导致任何角色身心状态、特质、重要物品发生重大非战斗性转变（身心状态如大喜大悲、心神不宁、顿悟洗心革面等，特质比如吃下宝物导致百毒不侵等、重要物品比如丢失、意外获得利器），必须在回复最末尾独立一行输出 `<STATUS_UPDATE: 角色名>`。若无重大转变，绝对不要输出此标记。"
    if override_tail:
        tail_instruction += f"\n{override_tail}"
    runtime_messages.append({"role": "system", "content": tail_instruction})

    client = get_user_client()
    if not client:
        yield "【系统提示】：请先在左侧边栏配置正确的 DeepSeek API Key。"
        return

    try:
        response = client.chat.completions.create(
            model=MODEL_PRO,
            messages=runtime_messages,
            stream=True,
        )
        try:
            for chunk in response:
                if chunk.choices and hasattr(chunk.choices[0].delta, "content") and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as stream_e:
            yield f"\n\n[系统警告：数据流在传输中途断开 ({type(stream_e).__name__})。这通常是由于 API 网络波动引起，当前文本已安全保留，您可以直接继续或重新点击发送。]"
    except Exception as e:
        yield f"\n\n[系统警告：API 连接建立失败 ({type(e).__name__})。错误详情: {str(e)}]"


_npc_stats_cache: dict = {}
_NPC_CACHE_MAX_SIZE = 100


def _generate_npc_cache_key(target_name: str, tags: list, world_anchor: str) -> str:
    """生成 NPC 缓存键。"""
    import hashlib
    tag_str = ",".join(sorted(tags)) if tags else ""
    anchor_prefix = world_anchor[:50] if world_anchor else ""
    combined = f"{target_name}|{tag_str}|{anchor_prefix}"
    return hashlib.md5(combined.encode("utf-8")).hexdigest()[:16]


def init_npc_combat_stats(target_name, active_scene, major_graph, world_anchor_text):
    """沙盒版 NPC 六维初始化；带缓存，不依赖原始管线。"""
    if not target_name or target_name in ["环境", "None", "null"] or not isinstance(target_name, str):
        return major_graph
    if "entities" not in major_graph:
        major_graph["entities"] = {}

    is_new_npc = target_name not in major_graph["entities"]
    npc_data = major_graph["entities"].get(target_name, {})
    has_caps = bool(npc_data.get("3_capabilities"))
    if not is_new_npc and has_caps:
        return major_graph

    existing_tags = npc_data.get("tags", ["NPC"])
    is_player = (target_name in major_graph["entities"] and "玩家" in npc_data.get("tags", []))
    cache_key = _generate_npc_cache_key(target_name, existing_tags, world_anchor_text)
    if not is_player and cache_key in _npc_stats_cache:
        major_graph["entities"][target_name] = deepcopy(_npc_stats_cache[cache_key])
        return major_graph

    recent_context = "\n".join([f"{m['role']}: {m['content']}" for m in active_scene[-3:]]) if active_scene else "无"
    existing_desc = npc_data.get("desc", "暂无历史设定，属于剧情首次登场的全新人物。请根据上下文合理推断设定。")
    known_entities = list(major_graph.get("entities", {}).keys())
    known_entities_str = "、".join(known_entities) if known_entities else "无"
    is_player = (target_name in known_entities and "玩家" in major_graph["entities"].get(target_name, {}).get("tags", []))

    if is_player:
        capability_constraint = (
            "- 【严格约束 - 玩家主角】3_capabilities 中只允许填入近期剧情上下文中该角色**实际使用或被提及**的能力/招式。"
            "严禁凭空编造剧情中从未出现过的技能。如果上下文中没有描述任何具体招式，只填写一个「基础应对」作为兜底。"
        )
    else:
        capability_constraint = (
            "- 【NPC 自由揣测】根据该角色的身份、名望和世界观基调，合理推断其可能掌握的全部技能树。"
            "NPC 作为独立存在的个体，应当拥有与其身份匹配的完整能力配置。"
        )

    system_prompt = f"""你是一个 TRPG 的动态实体生成与资产补全引擎 (Game Master)。
【当前宇宙法则与威力比例尺】
{world_anchor_text}

【目标实体情报】
姓名：{target_name}
基础已知设定：{existing_desc}
基础身份标签：{existing_tags}

【已存在的角色】
{known_entities_str}

【近期剧情上下文】
{recent_context}

【任务协议】
请根据该角色在剧情和世界观中的实际生态位与名望，推导其合理的背景描述、身份标签、掌握功法/能力以及当前的身心状态。
- 能力基础物理威力 (base_power) 必须严格对照基准：市井凡人/流氓 (10-20)；熟练老手/精英 (50-70)；绝世高手/宗师 (90-120+)。熟练度 (mastery_level) 默认填 1.0。
- 如果目标与已存在角色（特别是玩家主角）有明确的关系（如兄弟、仇敌、主仆等），必须在 relational_facts 中记录。
{capability_constraint}

必须返回纯 JSON 格式，结构严格对齐系统底盘：
{{
    "desc": "基于剧情与知名度提炼的一段客观中立的NPC背景描述",
    "tags": ["NPC", "阵营或身份标签"],
    "relational_facts": {{"已知角色名": "与该角色的关系描述"}},
    "3_capabilities": {{
        "核心招式名": {{"domains": ["战斗", "技术类型"], "base_power": 105, "mastery_level": 1.0, "features": ["特性描写"]}}
    }},
    "2_dynamic_status": {{
        "physical": {{"desc": "正常", "multiplier": 1.0}},
        "mental": {{"desc": "平静", "multiplier": 1.0}}
    }}
}}"""

    client = get_user_client()
    if not client:
        return major_graph
    try:
        response = client.chat.completions.create(
            model=MODEL_FLASH,
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        if is_new_npc:
            major_graph["entities"][target_name] = {
                "desc": result.get("desc", "神秘莫测的人物"),
                "tags": result.get("tags", ["NPC"]),
                "1_relational_facts": result.get("relational_facts", {}),
                "2_dynamic_status": result.get("2_dynamic_status", {}),
                "3_capabilities": result.get("3_capabilities", {}),
                "4_experience_factors": {"general_combat": 1.0, "specific_match": {}},
                "5_traits": [],
                "6_inventory": {},
                "7_held_items": {},
            }
        else:
            if not major_graph["entities"][target_name].get("3_capabilities"):
                major_graph["entities"][target_name]["3_capabilities"] = result.get("3_capabilities", {})
            if not major_graph["entities"][target_name].get("2_dynamic_status"):
                major_graph["entities"][target_name]["2_dynamic_status"] = result.get("2_dynamic_status", {})
            if result.get("relational_facts"):
                major_graph["entities"][target_name].setdefault("1_relational_facts", {})
                major_graph["entities"][target_name]["1_relational_facts"].update(result["relational_facts"])
    except Exception:
        if is_new_npc:
            major_graph["entities"][target_name] = {
                "desc": "战局中突发介入的未知第三方实体",
                "tags": ["NPC"],
                "1_relational_facts": {},
                "2_dynamic_status": {"physical": {"desc": "正常", "multiplier": 1.0}, "mental": {"desc": "谨慎", "multiplier": 1.0}},
                "3_capabilities": {"基础应对": {"domains": ["通用"], "base_power": 15, "mastery_level": 1.0, "features": ["防卫本能"]}},
                "4_experience_factors": {"general_combat": 1.0, "specific_match": {}},
                "5_traits": [],
                "6_inventory": {},
                "7_held_items": {},
            }

    if not is_player and target_name in major_graph["entities"]:
        if len(_npc_stats_cache) >= _NPC_CACHE_MAX_SIZE:
            first_key = next(iter(_npc_stats_cache))
            del _npc_stats_cache[first_key]
        _npc_stats_cache[cache_key] = deepcopy(major_graph["entities"][target_name])
    return major_graph


def sandbox_sync_dynamic_status(rendered_text, target_name, major_graph, active_scene, active_stage_names=None, pc_name="主角", suppress_inventory_sync=False):
    """沙盒版战后影子同步算子，不依赖原始管线。"""
    if active_stage_names is None:
        active_stage_names = []

    recent_context = "\n".join([f"{m['role']}: {m['content']}" for m in active_scene[-3:]]) if active_scene else "无"
    stage_info = ", ".join(active_stage_names) if active_stage_names else "仅主角在场"
    entities_to_check = [pc_name]
    full_radar_text = f"{rendered_text}\n{recent_context}"

    for name in major_graph.get("entities", {}).keys():
        if name == pc_name:
            continue
        if (name in full_radar_text) or (name in active_stage_names) or (str(target_name) == name):
            if name not in entities_to_check:
                entities_to_check.append(name)

    if target_name and str(target_name) != "None" and target_name in major_graph.get("entities", {}):
        if target_name not in entities_to_check:
            entities_to_check.append(target_name)

    system_prompt = f"""你是一个TRPG状态同步与数值生成引擎。
请阅读动作结算文本，提取以下角色的状态变更与资产变动：{entities_to_check}。

【当前舞台时空坐标】
- 本幕在场核心角色名录: [{stage_info}]

【前情提要（最近3幕历史对话）】
{recent_context}

【核心任务与原子操作量化协议】
1. 状态重置 (2_dynamic_status)：必须依据文本严格量化乘区（绝佳/顿悟: 1.2-1.5；良好/专注: 1.05-1.15；正常: 1.0；疲惫/轻伤: 0.7-0.9；重伤/崩溃: 0.1-0.5）。
2. 资产新增/强化 (new_assets)：只有明确发生拾取、购买、赠予、顿悟、觉醒、旧物进化时才允许提取；严禁把观察/研究/装备/使用已有物品误判为获得新物品。
3. 资产剥离/移除 (removed_assets)：target_domains 为空表示整体移除；非空表示只移除这些标签/属性。

必须输出纯 JSON。若某角色没有变动，new_assets 与 removed_assets 保持空列表：
{{
    "主角": {{
        "2_dynamic_status": {{
            "physical": {{"desc": "正常", "multiplier": 1.0}},
            "mental": {{"desc": "正常", "multiplier": 1.0}}
        }},
        "new_assets": [],
        "removed_assets": []
    }}
}}

【最新动作结算文本】
{rendered_text}

请严格以上述 JSON 样例为标准，输出本次清算结果："""

    client = get_user_client()
    if not client:
        return major_graph, {}
    try:
        response = client.chat.completions.create(
            model=MODEL_FLASH,
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)

        for entity, data in result.items():
            if entity not in major_graph.get("entities", {}):
                continue
            entity_node = major_graph["entities"][entity]
            status_data = data.get("2_dynamic_status", {})
            if "2_dynamic_status" not in entity_node:
                entity_node["2_dynamic_status"] = {"physical": {"desc": "正常", "multiplier": 1.0}, "mental": {"desc": "正常", "multiplier": 1.0}}
            if "physical" in status_data:
                entity_node["2_dynamic_status"]["physical"] = status_data["physical"]
            if "mental" in status_data:
                entity_node["2_dynamic_status"]["mental"] = status_data["mental"]

            for removed in data.get("removed_assets", []):
                cat = removed.get("category")
                name = removed.get("name")
                if not cat or not name:
                    continue
                if suppress_inventory_sync and cat == "6_inventory":
                    continue
                incoming_rem_tags = removed.get("target_domains", removed.get("tags", []))
                if isinstance(incoming_rem_tags, str):
                    incoming_rem_tags = [incoming_rem_tags]
                elif not isinstance(incoming_rem_tags, list):
                    incoming_rem_tags = []
                if cat in entity_node and isinstance(entity_node[cat], dict) and name in entity_node[cat]:
                    if incoming_rem_tags:
                        tag_key = "domains" if cat == "3_capabilities" else ("tags" if cat == "6_inventory" else "target_domains")
                        if tag_key in entity_node[cat][name] and isinstance(entity_node[cat][name][tag_key], list):
                            entity_node[cat][name][tag_key] = [t for t in entity_node[cat][name][tag_key] if t not in incoming_rem_tags]
                    else:
                        entity_node[cat].pop(name, None)
                elif cat == "5_traits" and isinstance(entity_node.get(cat), list):
                    existing_trait = next((t for t in entity_node["5_traits"] if isinstance(t, dict) and t.get("name") == name), None)
                    if existing_trait:
                        if incoming_rem_tags and "target_domains" in existing_trait and isinstance(existing_trait["target_domains"], list):
                            existing_trait["target_domains"] = [t for t in existing_trait["target_domains"] if t not in incoming_rem_tags]
                        elif not incoming_rem_tags:
                            entity_node["5_traits"].remove(existing_trait)

            for new_asset in data.get("new_assets", []):
                cat = new_asset.get("category")
                name = new_asset.get("name")
                if not cat or not name:
                    continue
                if suppress_inventory_sync and cat == "6_inventory":
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
                        entity_node[cat][name] = {"domains": incoming_tags if incoming_tags else ["通用"], "base_power": max(1, int(new_asset.get("base_power", 20))), "mastery_level": 1.0, "features": new_features if new_features else ["剧情顿悟"]}
                elif cat == "6_inventory":
                    from item_instances import create_item_instance, sync_legacy_item_index
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
                        entity_node["6_inventory"][name] = {"tags": incoming_tags if incoming_tags else ["通用"], "multiplier": safe_mult, "features": new_features if new_features else ["初始获得"]}
                    if not entity_node["6_inventory"].get(name, {}).get("instance_id"):
                        instance_id = create_item_instance(
                            major_graph,
                            name,
                            {
                                "display_name": name,
                                "tags": incoming_tags if incoming_tags else ["通用"],
                                "multiplier": safe_mult,
                                "features": new_features if new_features else ["初始获得"],
                                "persistence": "persistent",
                            },
                            holder=entity,
                            container="inventory",
                            location="背包",
                            source="sandbox_sync_dynamic_status",
                        )
                        sync_legacy_item_index(major_graph, entity, instance_id, "6_inventory")
                elif cat == "5_traits":
                    raw_mult = new_asset.get("multiplier", 1.0)
                    safe_mult = max(0.1, min(float(raw_mult), 3.0))
                    existing_trait = next((t for t in entity_node["5_traits"] if isinstance(t, dict) and t.get("name") == name), None)
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
                        entity_node["5_traits"].append({"name": name, "target_domains": incoming_tags if incoming_tags else ["通用"], "multiplier": safe_mult, "features": new_features if new_features else ["觉醒"]})
                elif isinstance(entity_node[cat], dict):
                    raw_mult = new_asset.get("multiplier", 1.0)
                    entity_node[cat][name] = {"target_domains": incoming_tags if incoming_tags else ["通用"], "multiplier": max(0.1, min(float(raw_mult), 3.0))}
    except Exception:
        pass

    raw_sync_json = result if "result" in locals() else {}
    return major_graph, raw_sync_json

# ---------------------------------------------------------------------------
# Prompt 模板（模块级常量，避免每次调用重新构造）
# ---------------------------------------------------------------------------
_PRE_SCAN_TEMPLATE = """从以下玩家输入中，提取所有提到的人名/角色名（不包括玩家自己）。
注意：玩家名是"{pc_name}"，此名在任何变体下都不应被提取。
只输出 JSON 数组，如 ["张三"] 或 []。禁止输出其它文字。
玩家输入：{user_input}"""


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


def _run_precheck_and_validation(user_input, active_scene, working_graph, real_pc_name):
    """
    执行意图解析 + Python 确定性校验。
    返回 (intent_result, parsed_intent, bypass_dc0, working_graph, validation_results, validation_injection)
    """
    from intent_parser import parse_and_adjudicate_intent

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
    status_callback=None,
) -> tuple[str, bool]:
    """
    沙盒并网总路由：意图解析 → 校验展示 → 机制分流 → 叙事流式生成 → 延迟提交。
    返回 (display_response, need_rerun)
    """
    from integration import (
        DOORBELL_NARRATIVE_INSTRUCTION,
        render_stream_and_commit,
    )
    from rules.adjudication_utils import run_standard_adjudication
    from ui_feedback import safe_status

    safe_status(status_callback, "turn_start")

    # ---- 0. deepcopy 保护原始图谱 ----
    working_graph = deepcopy(st.session_state.get("major_graph", {"entities": {}, "relations": []}))
    real_pc_name = st.session_state.get("pc_name", "主角")
    working_graph = _ensure_pc_default_capabilities(working_graph, real_pc_name)

    # ---- 0.5 预扫描：从用户输入中提取可能的实体名，提前初始化六维 ----
    anchor_text_pre = get_current_world_anchor_text(
        st.session_state.get("world_category", "异能"),
        st.session_state.world_tier
    )
    pre_scan_prompt = _PRE_SCAN_TEMPLATE.format(pc_name=real_pc_name, user_input=user_input)
    try:
        safe_status(status_callback, "npc_check")
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
                        from npc_lifecycle import build_npc_evidence_context, create_pending_reference, resolve_npc_reference, should_initialize_npc
                        evidence_scene = list(active_scene or []) + [{"role": "user", "content": user_input}]
                        evidence = build_npc_evidence_context(name, working_graph, evidence_scene)
                        resolution = resolve_npc_reference(name, evidence, working_graph)
                        decision = should_initialize_npc(
                            name,
                            {"entity_type": "character", "should_initialize_npc": True},
                            resolution,
                        )
                        if not decision.get("allowed"):
                            if resolution.get("status") == "pending":
                                first_evidence = evidence.get("candidate_mentions", [{}])[0].get("text", "") if evidence.get("candidate_mentions") else ""
                                create_pending_reference(working_graph, name, first_evidence, decision.get("reason", "未通过 NPC 初始化 gate"))
                            continue
                        name = decision.get("graph_key", name)
                        safe_status(status_callback, "npc_check")
                        with st.spinner(f"正在为新登场的人物【{name}】勾勒轮廓..."):
                            working_graph = init_npc_combat_stats(
                                name, active_scene, working_graph, anchor_text_pre
                            )
    except Exception:
        pass

    # ---- 1. 意图解析 + Python 确定性校验 ----
    safe_status(status_callback, "intent_parse")
    intent_result, parsed_intent, bypass_dc0, working_graph, validation_results, validation_injection = \
        _run_precheck_and_validation(user_input, active_scene, working_graph, real_pc_name)

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
        safe_status(status_callback, "adjudication")
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
            safe_status(status_callback, "npc_check")
            with st.spinner(f"正在为新登场的人物【{initiator}】勾勒轮廓..."):
                working_graph = init_npc_combat_stats(
                    initiator, active_scene, working_graph, anchor_text
                )
        if target and target not in ["环境", "None", "null"]:
            if _same_entity_name(target, real_pc_name):
                working_graph = _ensure_pc_default_capabilities(working_graph, real_pc_name)
            elif target not in working_graph.get("entities", {}) or not working_graph["entities"].get(target, {}).get("3_capabilities"):
                safe_status(status_callback, "npc_check")
                with st.spinner(f"正在为新登场的人物【{target}】勾勒轮廓..."):
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
    safe_status(status_callback, "narration")
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
    safe_status(status_callback, "sync_state")
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
