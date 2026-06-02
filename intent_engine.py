# -*- coding: utf-8 -*-
"""
intent_engine.py — 沙盒版本意图解析引擎

================================================================================
🔔 AI 助手维护提醒（每次修改前必读）
================================================================================

【沙盒版本绝对隔离原则】
- 本文件是 intent_engine.py 的 1:1 沙盒镜像副本
- 所有导入必须指向 sandbox_ 前缀版本
- 禁止直接调用主版本（intent_engine.py, core_engine.py 等）
- 沙盒修改不得污染主版本管线

【修改步骤】
1. 如需修改功能，先在此沙盒版本测试验证
2. 验证通过后，将修改实质迁移到主版本
3. 不要简单让主版本跳转到沙盒版本

【文件对应关系】
- sandbox_intent_engine.py ↔ intent_engine.py
- sandbox_core_engine.py ↔ core_engine.py

================================================================================

【设计哲学】
- LLM 是世界的造物主，Python 是书记员和算盘
- 意图解析由 LLM 自由语义理解
- 数值检定使用多乘区公式
- 状态同步使用门铃机制

【核心流程】
1. LLM 语义意图解析
2. 纯净背包双向流转
3. 彻底信任大模型的语义风险判断
"""

from __future__ import annotations
import json
import re
from copy import deepcopy

from config import MODEL_FLASH


# ---------------------------------------------------------------------------
# 常量定义
# ---------------------------------------------------------------------------
DEFAULT_INVENTORY_ITEM = {
    "tags": ["通用"],
    "multiplier": 1.0,
    "features": ["叙事显化获得"],
}

PRONOUN_TOKENS = frozenset({
    "他", "她", "它", "他们", "她们", "它们",
    "那个家伙", "这家伙", "那人", "那家伙",
    "对方", "此人", "其人",
})


# ---------------------------------------------------------------------------
# GraphRepository：只读+写适配器
# ---------------------------------------------------------------------------
class GraphRepository:
    def __init__(self, major_graph: dict, minor_npcs: dict | None = None, environment_assets: dict | None = None, pc_name: str = "主角", active_scene: list | None = None):
        self.major_graph = major_graph if isinstance(major_graph, dict) else {"entities": {}, "relations": []}
        self.minor_npcs = minor_npcs if isinstance(minor_npcs, dict) else {}
        self.environment_assets = environment_assets if isinstance(environment_assets, dict) else {}
        self.pc_name = pc_name
        self.active_scene = active_scene if isinstance(active_scene, list) else []

    def _all_known_names(self) -> list[str]:
        names: list[str] = []
        for pool in (self.entities, self.minor_npcs, self.environment_assets):
            names.extend(pool.keys())
        return [n for n in names if n and n != self.pc_name]

    def _resolve_pronoun_from_scene(self) -> str | None:
        known_names = self._all_known_names()
        if not known_names:
            return None
        for message in reversed(self.active_scene):
            content = str(message.get("content", ""))
            if not content: continue
            matched = [name for name in known_names if name in content]
            if matched:
                matched.sort(key=len, reverse=True)
                return matched[0]
        return None

    def _is_pronoun(self, name: str) -> bool:
        token = str(name).strip()
        return token in PRONOUN_TOKENS or token in {"他", "她", "它"}

    def resolve_entity_name(self, name: str) -> str | None:
        if not name: return None
        token = str(name).strip()
        if self._is_pronoun(token):
            resolved = self._resolve_pronoun_from_scene()
            if resolved: return resolved

        for pool in (self.entities, self.minor_npcs, self.environment_assets):
            if token in pool: return token

        known_names = self._all_known_names()
        for candidate in known_names:
            if token in candidate or candidate in token:
                return candidate

        if not self.minor_npcs and not self.environment_assets:
            return self._resolve_pronoun_from_scene()
        return None

    @property
    def entities(self) -> dict:
        return self.major_graph.get("entities", {})

    def get_pc_entity(self) -> dict:
        return self.entities.get(self.pc_name, {})

    def get_inventory(self) -> dict:
        return deepcopy(self.get_pc_entity().get("6_inventory", {}))

    def ensure_pc_entity(self) -> dict:
        if self.pc_name not in self.entities:
            self.entities[self.pc_name] = {
                "desc": "世界的变数", "tags": ["玩家"], "1_relational_facts": {},
                "2_dynamic_status": {"physical": {"desc": "健康", "multiplier": 1.0}, "mental": {"desc": "平静", "multiplier": 1.0}},
                "3_capabilities": {}, "4_experience_factors": {"general_combat": 1.0, "specific_match": {}},
                "5_traits": [], "6_inventory": {}, "7_held_items": {},
            }
        if "6_inventory" not in self.entities[self.pc_name]:
            self.entities[self.pc_name]["6_inventory"] = {}
        if "7_held_items" not in self.entities[self.pc_name]:
            self.entities[self.pc_name]["7_held_items"] = {}
        return self.entities[self.pc_name]

    def has_inventory_item(self, item_name: str) -> bool:
        inv = self.ensure_pc_entity().get("6_inventory", {})
        return item_name in inv

    def put_inventory_item(self, item_name: str, item_data: dict | None = None) -> bool:
        entity = self.ensure_pc_entity()
        inv = entity.setdefault("6_inventory", {})
        if item_name in inv: return False
        inv[item_name] = deepcopy(item_data or DEFAULT_INVENTORY_ITEM)
        return True
    
    def remove_inventory_item(self, item_name: str) -> bool:
        entity = self.ensure_pc_entity()
        inv = entity.setdefault("6_inventory", {})
        if item_name in inv:
            del inv[item_name]
            return True
        return False


# ---------------------------------------------------------------------------
# LLM 意图解析核心
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Prompt 模板（模块级常量，避免每次调用重新构造大段字符串）
# 使用精简版 Prompt，压缩率 69%，测试验证效果不降反升
# ---------------------------------------------------------------------------
_INTENT_PARSE_SYSTEM_TEMPLATE = """你是跑团意图解析引擎。基于玩家行为和实体标签，提取意图并判定风险。
仅输出 JSON，禁止其他文字：

{{
  "intended_action": "自然语言动作描述",
  "action_label": "机器标签或null",
  "action_category": "combat/social/stealth/skill/none",
  "target_entities": ["互动的NPC或设施名"],
  "obtained_items": ["获取的可携带物品"],
  "lost_items": ["丢弃/消耗的物品"],
  "world_state_change": "世界状态变化描述",
  "is_risk": true或false,
  "initiator_entity": "发起方实体名",
  "detected_ability": "使用的能力/招式名或null",
  "target_entity": "承受方实体名或null",
  "target_ongoing_action": "对抗方应对招式或null",
  "initiator_matched_assets": ["发起方动用的能力/物品原名称"],
  "target_matched_assets": ["对抗方关联的能力/物品"],
  "entity_annotations": [{{"name": "实体名", "canonical_name": "规范名", "entity_type": "character/object/...", "role_in_action": "actor/opponent/target/tool/...", "persistence": "persistent/ephemeral", "should_initialize_npc": true或false, "reason": "理由"}}],
  "action_sequence": [{{"action_id": "a1", "actor": "发起者", "target": "目标", "action_type": "combat/...", "intended_action": "动作描述", "detected_ability": "能力名或null", "depends_on": [], "required_items": {{}}, "consumed_items": {{}}, "temporary_items": {{}}, "reward_items": {{}}, "narrative_weight": "HIGH/MEDIUM/LOW", "is_risk": true}}]
}}

【action_category】攻击/搏斗→combat | 欺骗/说服/威胁→social | 偷窃/潜行→stealth | 工具/开锁/施法→skill | 对话/观察→none

【is_risk】目标带敌对标签→任何互动均有风险(true) | 目标带安全标签→礼貌对话安全(false)、欺骗/攻击高危(true) | 无主环境→安全(false)

【风险边界】is_risk=true时，world_state_change只能写"试图/准备"状态，不得预写成功结果。命中/击退/说服等结果须等裁决。

【实体识别】主动行为：{pc_name}是发起方 | 被动应对：威胁源是发起方，{pc_name}是对抗方 | 掩体/墙壁不是对抗方

【实体分类】只有自主意志角色才可entity_type="character"且should_initialize_npc=true | 物品/地形/概念不得初始化为NPC | canonical_name去掉修饰词(如"墙上的火把"→"火把")

【资产匹配】必须精确提取面板中的原名称，不得编造/缩写

【复合动作】多动作时填action_sequence | 单动作时action_sequence=[]，用顶层字段 | 物品流转用required_items(使用不消耗)/consumed_items(消耗)/temporary_items(临时)/reward_items(获得)

【临时物品约束】temporary_items须含constraints: scene_plausible(场景存在)/obtainable(可捡起)/ownership_clear(所有权)/prerequisites_met(使用条件)/safe_to_use(安全)/world_compatible(世界法则)。任一false须填reason。

【动作约束】action_sequence子动作须含action_constraints: target_exists/target_reachable/environment_supports/actor_capable。任一false须填reason。

【代词消解】"他/她/它"须结合前情还原为规范名称

【NPC称呼与身份协议】代称、尊称、蔑称、头衔、关系称呼或外号（如“神秘人”“那个不能说名字的人”“乔帮主”“萧大王”“师父”“黑衣人”）不是长期NPC规范名。若能从前情确定真实指向，canonical_name填已知人物当前主显示名，并在reason说明该称呼是alias/title/taboo name；若无法确定，should_initialize_npc=false并说明unresolved_reference。人物曾用名、真名、尊称、蔑称、身份称号不等于必须改名；除非叙事明确说明角色从此改用新名，否则保持原primary/display name，将其他称呼记录为aliases。“黑衣人”“蒙面人”“白衣女子”等局部称呼默认是scene_bound/specific_instance，不得自动作为global_alias。

【当前玩家】{pc_name}
【背包】{inventory_snapshot}
【实体名录】{entity_glossary}
【前情】{recent_context}
"""


def build_intent_parse_prompt(pc_name: str, inventory_snapshot: str, entity_glossary: str, recent_context: str) -> str:
    return _INTENT_PARSE_SYSTEM_TEMPLATE.format(
        pc_name=pc_name,
        inventory_snapshot=inventory_snapshot,
        entity_glossary=entity_glossary,
        recent_context=recent_context,
    )


def _extract_json_object(raw: str) -> dict:
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match: return json.loads(match.group(0))
        raise


def _build_item_canonical_map(entity_annotations: list[dict]) -> dict[str, str]:
    item_types = {"object", "location_feature", "environment", "unknown"}
    item_roles = {"tool", "temporary_tool", "loot", "obstacle", "terrain", "context"}
    mapping: dict[str, str] = {}
    for ann in entity_annotations or []:
        if not isinstance(ann, dict):
            continue
        entity_type = str(ann.get("entity_type", "unknown")).strip()
        role = str(ann.get("role_in_action", "unknown")).strip()
        if entity_type not in item_types and role not in item_roles:
            continue
        name = str(ann.get("name", "")).strip()
        if not name:
            continue
        canonical = str(ann.get("canonical_name", name)).strip() or name
        mapping[name] = canonical
        mapping[canonical] = canonical
    return mapping


def _canonicalize_quantity_items(items: dict, canonical_map: dict[str, str]) -> dict:
    result: dict = {}
    for raw_name, qty in (items or {}).items():
        name = str(raw_name).strip()
        if not name:
            continue
        canonical = canonical_map.get(name, name)
        if canonical in result:
            result[canonical] = int(result[canonical] or 0) + int(qty or 0)
        else:
            result[canonical] = qty
    return result


def _merge_persistence(old_value: str | None, new_value: str | None) -> str | None:
    priority = {"unknown": 0, "ephemeral": 1, "scene_bound": 2, "persistent": 3}
    old_text = str(old_value or "unknown")
    new_text = str(new_value or "unknown")
    return old_text if priority.get(old_text, 0) >= priority.get(new_text, 0) else new_text


def _canonicalize_data_items(items: dict, canonical_map: dict[str, str]) -> dict:
    result: dict = {}
    for raw_name, item_data in (items or {}).items():
        name = str(raw_name).strip()
        if not name:
            continue
        canonical = canonical_map.get(name, name)
        data = deepcopy(item_data if isinstance(item_data, dict) else {"value": item_data})
        data.setdefault("source_name", name)
        if canonical not in result:
            result[canonical] = data
            continue
        existing = result[canonical]
        existing_tags = list(existing.get("tags", []) or []) if isinstance(existing, dict) else []
        new_tags = list(data.get("tags", []) or []) if isinstance(data, dict) else []
        if isinstance(existing, dict):
            existing["tags"] = list(dict.fromkeys(existing_tags + new_tags))
            existing["persistence"] = _merge_persistence(existing.get("persistence"), data.get("persistence"))
            sources = existing.get("source_names") or [existing.get("source_name", canonical)]
            if name not in sources:
                sources.append(name)
            existing.pop("source_name", None)
            existing["source_names"] = sources
    return result


def _normalize_parsed_intent(raw: dict) -> dict:
    def _none_if_empty(value):
        text = str(value or "").strip()
        if text.lower() in {"", "none", "null", "nil", "无"}:
            return None
        return text

    raw_annotations = raw.get("entity_annotations") or []
    entity_annotations = []
    for item in raw_annotations:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        entity_annotations.append({
            "name": name,
            "canonical_name": str(item.get("canonical_name", name)).strip() or name,
            "entity_type": str(item.get("entity_type", "unknown")).strip() or "unknown",
            "role_in_action": str(item.get("role_in_action", "unknown")).strip() or "unknown",
            "persistence": str(item.get("persistence", "unknown")).strip() or "unknown",
            "should_initialize_npc": bool(item.get("should_initialize_npc", False)),
            "reason": str(item.get("reason", "")).strip(),
        })
    canonical_name_map = _build_item_canonical_map(entity_annotations)
    raw_sequence = raw.get("action_sequence") or []
    action_sequence = []
    top_target_entity = _none_if_empty(raw.get("target_entity"))
    top_target_ongoing_action = _none_if_empty(raw.get("target_ongoing_action"))
    for idx, item in enumerate(raw_sequence):
        if not isinstance(item, dict):
            continue
        depends_on = item.get("depends_on") or []
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        action_target = str(item.get("target", raw.get("target_entity", "环境"))).strip() or "环境"
        action_target_ongoing = _none_if_empty(item.get("target_ongoing_action"))
        if not action_target_ongoing and top_target_entity and action_target == top_target_entity:
            action_target_ongoing = top_target_ongoing_action
        action_sequence.append({
            "action_id": str(item.get("action_id", f"a{idx + 1}")).strip(),
            "actor": str(item.get("actor", raw.get("initiator_entity", "主角"))).strip() or "主角",
            "target": action_target,
            "action_type": str(item.get("action_type", raw.get("action_category", "none"))).strip() or "none",
            "action_label": str(item.get("action_label", "")).strip() or None,
            "intended_action": str(item.get("intended_action", raw.get("intended_action", "unknown"))).strip(),
            "detected_ability": _none_if_empty(item.get("detected_ability")),
            "depends_on": [str(dep).strip() for dep in depends_on if dep and str(dep).strip()],
            "required_items": _canonicalize_quantity_items(item.get("required_items") if isinstance(item.get("required_items"), dict) else {}, canonical_name_map),
            "consumed_items": _canonicalize_quantity_items(item.get("consumed_items") if isinstance(item.get("consumed_items"), dict) else {}, canonical_name_map),
            "cost_items": _canonicalize_quantity_items(item.get("cost_items") if isinstance(item.get("cost_items"), dict) else {}, canonical_name_map),
            "temporary_items": _canonicalize_data_items(item.get("temporary_items") if isinstance(item.get("temporary_items"), dict) else {}, canonical_name_map),
            "reward_items": _canonicalize_data_items(item.get("reward_items") if isinstance(item.get("reward_items"), dict) else {}, canonical_name_map),
            "target_part": _none_if_empty(item.get("target_part")),
            "narrative_weight": str(item.get("narrative_weight", "MEDIUM")).strip().upper() or "MEDIUM",
            "is_risk": bool(item.get("is_risk", raw.get("is_risk", True))),
            "target_ongoing_action": action_target_ongoing,
            "initiator_matched_assets": [str(a).strip() for a in (item.get("initiator_matched_assets") or []) if a and str(a).strip()],
            "target_matched_assets": [str(a).strip() for a in (item.get("target_matched_assets") or []) if a and str(a).strip()],
        })
    return {
        "intended_action": str(raw.get("intended_action", "unknown")).strip(),
        "action_label": _none_if_empty(raw.get("action_label")),
        "action_category": str(raw.get("action_category", "none")).strip(),
        "target_entities": [str(e).strip() for e in (raw.get("target_entities") or []) if e and str(e).strip()],
        "obtained_items": [str(i).strip() for i in (raw.get("obtained_items") or []) if i and str(i).strip()],
        "lost_items": [str(i).strip() for i in (raw.get("lost_items") or []) if i and str(i).strip()],
        "world_state_change": str(raw.get("world_state_change", "")).strip(),
        "is_risk": bool(raw.get("is_risk", True)),
        # 桥接旧系统检定引擎的完整字段
        "initiator_entity": str(raw.get("initiator_entity", "主角")).strip() or None,
        "detected_ability": _none_if_empty(raw.get("detected_ability")),
        "target_entity": top_target_entity,
        "target_ongoing_action": top_target_ongoing_action,
        "initiator_matched_assets": [str(a).strip() for a in (raw.get("initiator_matched_assets") or []) if a and str(a).strip()],
        "target_matched_assets": [str(a).strip() for a in (raw.get("target_matched_assets") or []) if a and str(a).strip()],
        "entity_annotations": entity_annotations,
        "action_sequence": action_sequence,
    }


def call_llm_parse_intent(user_input: str, active_scene: list, graph: GraphRepository) -> tuple[dict, str]:
    from core_engine import get_user_client
    
    recent_context = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in active_scene[-3:]) if active_scene else "无"
    inv = graph.get_inventory()
    inventory_snapshot = ", ".join(inv.keys()) if inv else "（空）"

    known_entities = []
    for pool in (graph.minor_npcs, graph.environment_assets, graph.entities):
        for name, data in pool.items():
            if name == graph.pc_name: continue
            tags = data.get("tags", [])
            tag_str = f"[{','.join(tags)}]" if tags else ""
            # 新增：把能力列表也加入实体名录，让意图解析器能看到 NPC 有什么招式
            caps = data.get("3_capabilities", {})
            cap_str = f" 能力:{','.join(caps.keys())}" if caps else ""
            known_entities.append(f"{name}{tag_str}{cap_str}")
    entity_glossary = " | ".join(known_entities) if known_entities else "无已知NPC"

    # DEBUG: 打印实体名录到控制台
    import logging
    logging.getLogger(__name__).info(f"[DEBUG] entity_glossary: {entity_glossary}")

    system_prompt = build_intent_parse_prompt(graph.pc_name, inventory_snapshot, entity_glossary, recent_context)
    user_prompt = f"【玩家最新输入】\n{user_input}"

    client = get_user_client()
    if not client:
        fallback = {
            "intended_action": user_input or "未知动作",
            "action_label": None,
            "action_category": "none",
            "target_entities": [],
            "world_state_change": f"玩家提出动作：{user_input}，结果待裁决。",
            "is_risk": True,
            "_error": "未配置 API Key",
        }
        return fallback, json.dumps(fallback, ensure_ascii=False)

    try:
        response = client.chat.completions.create(
            model=MODEL_FLASH,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw_content = response.choices[0].message.content.strip()
        parsed = _normalize_parsed_intent(_extract_json_object(raw_content))
        return parsed, raw_content
    except Exception as exc:
        fallback = {
            "intended_action": user_input or "未知动作",
            "action_label": None,
            "action_category": "none",
            "target_entities": [],
            "world_state_change": f"玩家提出动作：{user_input}，结果待裁决。",
            "is_risk": True,
            "_error": str(exc),
        }
        return fallback, json.dumps(fallback, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 格式化输出组件
# ---------------------------------------------------------------------------
def build_debug_logs(raw_llm_json: str, parsed_intent: dict) -> str:
    lines = [
        "========== Sandbox Intent Engine | Pure LLM Semantic ==========",
        "【大模型原始 JSON 快照】", raw_llm_json or "(无)", "",
        "【规范化路由解析】", json.dumps(parsed_intent, ensure_ascii=False, indent=2),
        "===============================================================",
    ]
    return "\n".join(lines)


def build_dc0_narrative_injection(parsed: dict) -> str:
    # 仅在 is_risk=false 的 DC0 自动放行场景中，把 world_state_change 作为已确认事实。
    change = parsed.get("world_state_change") or "世界状态发生轻微变化。"
    action = parsed.get("intended_action", "unknown")
    assets = parsed.get("target_entities") or [] # 已修复：替换为 target_entities
    assets_str = "、".join(assets) if assets else "无特定互动实体"
    return (
        f"\n【DC0 自动放行 | 意图: {action}】\n"
        f"涉事资产: {assets_str}\n"
        f"世界状态变更（已本地确认无机制风险）: {change}\n"
        f"指令: 请以上述变更为事实基础续写剧情，本回合跳过掷骰与裁判检定。\n"
    )


# ---------------------------------------------------------------------------
# 主入口：纯净广义意图流转管线
# ---------------------------------------------------------------------------
def parse_and_adjudicate_intent(
    user_input: str,
    active_scene: list,
    major_graph: dict,
    minor_npcs: dict | None = None,
    environment_assets: dict | None = None,
    pc_name: str = "主角",
) -> dict:
    import streamlit as st
    if not minor_npcs and "minor_npcs" in st.session_state:
        minor_npcs = st.session_state["minor_npcs"]
    if not environment_assets and "environment_assets" in st.session_state:
        environment_assets = st.session_state["environment_assets"]

    graph = GraphRepository(major_graph, minor_npcs, environment_assets, pc_name, active_scene=active_scene)

    # 1. 呼叫大模型解析（完全语义泛化）
    parsed, raw_llm_json = call_llm_parse_intent(user_input, active_scene, graph)

    # 2. 纯净背包双向流转。若存在 action_sequence，则物品先后流转交给复杂对抗环境处理。
    healed_items = []
    if not parsed.get("action_sequence"):
        for item_name in parsed.get("obtained_items", []):
            if graph.put_inventory_item(item_name):
                healed_items.append(item_name)

    lost_items = []
    if not parsed.get("action_sequence"):
        for item_name in parsed.get("lost_items", []):
            if graph.remove_inventory_item(item_name):
                lost_items.append(item_name)

    # 3. 彻底信任大模型的语义风险判断
    is_risk = bool(parsed.get("is_risk", True))
    bypass = not is_risk
    narrative_injection = build_dc0_narrative_injection(parsed) if bypass else ""

    debug_logs = build_debug_logs(raw_llm_json, parsed)

    return {
        "parsed_intent": parsed,
        "is_risk": is_risk,
        "risk_override_reasons": ["完全依赖 LLM 语义判断"],
        "inventory_self_healed": healed_items,
        "inventory_lost": lost_items,
        "bypass_mechanics": bypass,
        "narrative_injection": narrative_injection,
        "requires_adjudication": not bypass,
        "major_graph": graph.major_graph,
        "debug_logs": debug_logs,
    }
