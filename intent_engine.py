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
                "5_traits": [], "6_inventory": {},
            }
        if "6_inventory" not in self.entities[self.pc_name]:
            self.entities[self.pc_name]["6_inventory"] = {}
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
def build_intent_parse_prompt(pc_name: str, inventory_snapshot: str, entity_glossary: str, recent_context: str) -> str:
    return f"""你是一个跑团系统的【广义意图解析与裁判引擎】。你需要基于玩家的行为和已知实体标签，进行高泛化性的意图提取与风险判定。
你必须且仅输出以下 JSON 结构，禁止输出其它文字：

{{
  "intended_action": "高度抽象的行为标签字符串，如 use_tool, search_item, transform_resources, social_persuade, melee_attack, cast_spell",
  "action_category": "combat / social / stealth / skill / none（必须精确选择其一，这决定了检定使用哪套规则体系）",
  "target_entities": ["本次行为互动、对抗或影响的 NPC、人物或场景设施名称。若无则为空数组[]"],
  "obtained_items": ["仅填入玩家实际获取、可携带的轻量级实体。【语境转化原则】：若是自然景观或环境碎片（如石头、树枝）被玩家明确拾取作为临时道具/武器，必须将其视作资产填入此列表。若只是作为背景互动，严禁填入。若无则为空数组[]"],
  "lost_items": ["仅当玩家明确丢弃、消耗、失去某具体物品时填写。注意：你必须如实记录玩家声明的操作，不要因为背包清单中没有该物品就不填。背包校验由后续系统负责，你的职责是如实提取玩家意图。若无则为空数组[]"],
  "world_state_change": "物理世界预期改变的客观描述（一句话）",
  "is_risk": true或false,
  "initiator_entity": "发起动作的实体名（通常是{pc_name}，若是被动应对则填威胁源名称）",
  "detected_ability": "发起方使用的具体能力、招式或技能名（如无则填null）",
  "target_entity": "动作承受方/对抗方实体名（如无特定目标则填null）",
  "target_ongoing_action": "对抗方/承受方的应对招式或特征（如无则填null）",
  "initiator_matched_assets": ["发起方在本次动作中实际动用的能力、特质、物品的原名称（必须与已知实体面板中的名称一字不差）"],
  "target_matched_assets": ["对抗方在本次动作中实际关联的能力、特质、物品的原名称"]
}}

【action_category 判定规则】
- 攻击、搏斗、施展武技 → combat
- 欺骗、说服、威胁、谈判、交涉 → social
- 偷窃、潜行、隐匿、侦察 → stealth
- 使用工具、开锁、攀爬、跳跃、施法、治疗等技巧性动作 → skill
- 纯对话、观察、移动等无机制行为 → none

【is_risk 语义泛化判定规则（你是唯一的裁判）】
- 结合【已知实体名录】的标签进行判断。
- 若目标带有敌对或致命标签：任何互动（含搭话、靠近）均有风险，is_risk 必须为 true。
- 若目标带有[重要NPC]或安全标签：礼貌对话、打招呼、远距离观察为安全 (false)；但欺骗、偷窃、攻击行为极度高危 (true)。
- 纯观察、翻找无主的普通环境为安全 (false)。

【双端实体识别协议】
- 主动行为：{pc_name}主动对某物发难。{pc_name}是发起方。
- 被动应对：{pc_name}被动应对突发灾难/天灾/攻击。此时【威胁源】才是发起方，{pc_name}是对抗方。
- 绝对严禁把"掩体"、"大树"、"墙壁"等躲避媒介误识别为对抗方实体！

【资产扫描匹配协议】
- 必须精确提取面板中所列出的原名称，严禁凭空编造、缩写或改写。
- 若无匹配资产，对应数组保持为空列表 []。

【硬性约束】
- 【代词消解约束】：当玩家输入包含"他/她/它/那个家伙"等代词时，必须结合【前情】将代词消解还原为真实的规范名称，并记入 target_entities。

【当前玩家】{pc_name}
【玩家背包现有物品】{inventory_snapshot}
【已知实体名录（供判定风险参考）】
{entity_glossary}

【前情（最近对话）】
{recent_context}
"""

def _extract_json_object(raw: str) -> dict:
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match: return json.loads(match.group(0))
        raise

def _normalize_parsed_intent(raw: dict) -> dict:
    return {
        "intended_action": str(raw.get("intended_action", "unknown")).strip(),
        "action_category": str(raw.get("action_category", "none")).strip(),
        "target_entities": [str(e).strip() for e in (raw.get("target_entities") or []) if e and str(e).strip()],
        "obtained_items": [str(i).strip() for i in (raw.get("obtained_items") or []) if i and str(i).strip()],
        "lost_items": [str(i).strip() for i in (raw.get("lost_items") or []) if i and str(i).strip()],
        "world_state_change": str(raw.get("world_state_change", "")).strip(),
        "is_risk": bool(raw.get("is_risk", True)),
        # 桥接旧系统检定引擎的完整字段
        "initiator_entity": str(raw.get("initiator_entity", "主角")).strip() or None,
        "detected_ability": str(raw.get("detected_ability", "")).strip() or None,
        "target_entity": str(raw.get("target_entity", "")).strip() or None,
        "target_ongoing_action": str(raw.get("target_ongoing_action", "")).strip() or None,
        "initiator_matched_assets": [str(a).strip() for a in (raw.get("initiator_matched_assets") or []) if a and str(a).strip()],
        "target_matched_assets": [str(a).strip() for a in (raw.get("target_matched_assets") or []) if a and str(a).strip()],
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
        fallback = {"intended_action": "unknown", "target_entities": [], "world_state_change": user_input, "is_risk": True, "_error": "未配置 API Key"}
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
        fallback = {"intended_action": "unknown", "target_entities": [], "world_state_change": user_input, "is_risk": True, "_error": str(exc)}
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

    # 2. 纯净背包双向流转（绝对信任大模型的 obtained 与 lost 提取）
    healed_items = []
    for item_name in parsed.get("obtained_items", []):
        if graph.put_inventory_item(item_name):
            healed_items.append(item_name)

    lost_items = []
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