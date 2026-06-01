# -*- coding: utf-8 -*-
"""
sandbox_rules/adjudication_utils.py — 沙盒版本检定工具函数

================================================================================
🔔 AI 助手维护提醒（每次修改前必读）
================================================================================

【沙盒版本绝对隔离原则】
- 本文件是 rules/adjudication_utils.py 的 1:1 沙盒镜像副本
- 所有导入必须指向 sandbox_ 前缀版本
- 禁止直接调用主版本（rules/ 等）
- 沙盒修改不得污染主版本管线

【修改步骤】
1. 如需修改功能，先在此沙盒版本测试验证
2. 验证通过后，将修改实质迁移到主版本
3. 不要简单让主版本跳转到沙盒版本

【文件对应关系】
- sandbox_rules/adjudication_utils.py ↔ rules/adjudication_utils.py

================================================================================
"""

import json
import random

from sandbox_config import MODEL_FLASH


ACTION_DOMAIN_MAP = {
    "combat": "战斗",
    "skill": "技能",
    "stealth": "潜行",
    "social": "社交",
}

# ---------------------------------------------------------------------------
# Prompt 模板（模块级常量）
# ---------------------------------------------------------------------------
_DYNAMIC_BASE_TEMPLATE = """你是一个 TRPG 的动态数值裁决引擎。

【当前宇宙法则与威力比例尺】
{world_anchor_text}

【任务协议】
当前正在评估 {role_type}：{entity_name or '环境'}
使用的动作/应对特征：{specific_action or '环境默认作用'}

请严格对照上方的【威力比例尺】，推断其在当前世界法则下合理的 dynamic_base (基数)。
必须返回纯 JSON 格式：
{{
    "dynamic_name": "提炼的具体动作或灾难/环境特征名",
    "dynamic_base": 25
}}"""


def _get_user_client():
    from sandbox_core_engine import get_user_client

    return get_user_client()


def safe_clamp_multiplier(raw) -> float:
    """对 LLM 输出的乘数做边界校验：类型检查 + 范围限制 0.3~3.0"""
    if not isinstance(raw, (int, float)):
        return 1.0
    return max(0.3, min(float(raw), 3.0))


def _scan_item_buffs(item_name, item_data, action_domains, matched_assets):
    """从单个物品/手持物中提取乘数，优先 contextual_multiplier"""
    if not isinstance(item_data, dict):
        return None
    tags = item_data.get("tags", item_data.get("target_domains", []))
    if item_name not in matched_assets and not set(tags).intersection(set(action_domains)):
        return None
    mult = safe_clamp_multiplier(
        item_data.get("contextual_multiplier", item_data.get("multiplier", 1.0))
    )
    return mult


def calculate_conditional_buffs(entity_data, action_domains, opp_name, is_social, matched_assets):
    total_mult = 1.0
    activated = []

    # 扫描背包物品
    for item_name, item_data in entity_data.get("6_inventory", {}).items():
        mult = _scan_item_buffs(item_name, item_data, action_domains, matched_assets)
        if mult is not None:
            total_mult *= mult
            activated.append(f"{item_name}(x{mult})")

    # 扫描手持物
    for item_name, item_data in entity_data.get("7_held_items", {}).items():
        mult = _scan_item_buffs(item_name, item_data, action_domains, matched_assets)
        if mult is not None:
            total_mult *= mult
            activated.append(f"{item_name}(x{mult})")

    for trait in entity_data.get("5_traits", []):
        t_name = trait.get("name", "")
        domains = trait.get("target_domains", [])
        if t_name in matched_assets or set(domains).intersection(set(action_domains)):
            mult = trait.get("multiplier", 1.0)
            total_mult *= mult
            activated.append(f"{t_name}(x{mult})")

    if is_social and opp_name:
        rel = entity_data.get("1_relational_facts", {}).get(opp_name)
        if isinstance(rel, dict):
            domains = rel.get("target_domains", [])
            if not domains or set(domains).intersection(set(action_domains)) or "社交" in action_domains:
                mult = rel.get("multiplier", 1.0)
                total_mult *= mult
                activated.append(f"羁绊(x{mult})")

    return total_mult, activated


def call_llm_for_dynamic_base(entity_name, specific_action, is_defense, world_anchor_text):
    role_type = "防御方 (判定目标抗打击度或破解难度/DC)" if is_defense else "发起方 (判定其侵袭烈度 or 出力 Base)"
    client = _get_user_client()
    if not client:
        return entity_name or "环境", 15

    system_prompt = _DYNAMIC_BASE_TEMPLATE.format(
        world_anchor_text=world_anchor_text,
        role_type=role_type,
        entity_name=entity_name or '环境',
        specific_action=specific_action or '环境默认作用',
    )

    try:
        response = client.chat.completions.create(
            model=MODEL_FLASH,
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        return result.get("dynamic_name", entity_name or "环境"), result.get("dynamic_base", 15)
    except Exception:
        return entity_name or "环境", 15


def build_action_domains(action_type, is_defense=False):
    domains = [action_type, "通用"]
    if action_type in ACTION_DOMAIN_MAP:
        domains.append(ACTION_DOMAIN_MAP[action_type])
    if is_defense:
        domains.extend(["防御", "身法", "护体"])
    return domains


def get_entity_combat_stats(
    entity_name,
    specific_ability,
    is_defense,
    opp_name,
    matched_assets,
    action_type,
    major_graph,
    world_anchor_text,
    is_social=False,
):
    if not entity_name or entity_name not in major_graph.get("entities", {}) or entity_name == "环境":
        dyn_name, dyn_base = call_llm_for_dynamic_base(entity_name, specific_ability, is_defense, world_anchor_text)
        d20 = random.randint(1, 20)
        return {
            "name": dyn_name,
            "ability": specific_ability or "环境作用",
            "base": dyn_base,
            "mastery": 1.0,
            "phys": 1.0,
            "ment": 1.0,
            "exp": 1.0,
            "cond": 1.0,
            "buffs": ["(动态裁决)"],
            "d20": d20,
            "final": dyn_base + d20,
        }

    entity = major_graph["entities"][entity_name]
    caps = entity.get("3_capabilities", {})
    status = entity.get("2_dynamic_status", {})
    exp = entity.get("4_experience_factors", {})

    used_ability = "基础行动"
    base_power, mastery = 10, 1.0
    domains = build_action_domains(action_type, is_defense)

    if caps:
        matched_key = None
        # 1. 精确匹配：matched_assets 中的物品名
        for key in caps.keys():
            if key in matched_assets:
                matched_key = key
                break

        # 2. 字符串包含匹配（简单兜底）
        if not matched_key and specific_ability and not is_defense:
            for key in caps.keys():
                if key in specific_ability or specific_ability in key:
                    matched_key = key
                    break

        # 3. 对抗方：优先匹配防御类能力
        if not matched_key and is_defense:
            for key, value in caps.items():
                if any(domain in value.get("domains", []) for domain in ["防御", "身法", "护体"]):
                    matched_key = key
                    break

        # 4. 对抗方兜底：使用最强能力
        if not matched_key and is_defense:
            best_ability = max(caps.items(), key=lambda item: item[1].get("base_power", 10) * item[1].get("mastery_level", 1.0))
            matched_key = best_ability[0]
        elif not matched_key and not is_defense and specific_ability:
            used_ability = specific_ability
            base_power = 25

        if matched_key:
            used_ability = matched_key
            base_power = caps[matched_key].get("base_power", 10)
            mastery = caps[matched_key].get("mastery_level", 1.0)
            domains.extend(caps[matched_key].get("domains", []))
    elif specific_ability:
        used_ability = specific_ability
        if not is_defense:
            base_power = 25

    phys_mult = status.get("physical", {}).get("multiplier", 1.0)
    ment_mult = status.get("mental", {}).get("multiplier", 1.0)

    general_exp = exp.get("general_combat", 1.0)
    specific_exp = exp.get("specific_match", {}).get(used_ability, 1.0)
    exp_mult = general_exp * specific_exp

    cond_mult, buffs = calculate_conditional_buffs(entity, domains, opp_name, is_social, matched_assets)

    if general_exp != 1.0:
        buffs.append(f"通用经验(x{general_exp})")
    if specific_exp != 1.0:
        buffs.append(f"{used_ability}专精经验(x{specific_exp})")
    d20 = random.randint(1, 20)

    return {
        "name": entity_name,
        "ability": used_ability,
        "base": base_power,
        "mastery": mastery,
        "phys": phys_mult,
        "ment": ment_mult,
        "exp": exp_mult,
        "cond": cond_mult,
        "buffs": buffs,
        "d20": d20,
        "final": (base_power * mastery * phys_mult * ment_mult * exp_mult * cond_mult) + d20,
    }


def resolve_delta_tier(delta):
    if delta >= 15:
        return "发起方效果本次对抗中完全碾压了抵抗方效果"
    if delta >= 0:
        return "发起方效果本次对抗中成功胜过了抵抗方效果"
    if delta >= -10:
        return "发起方和抵抗方的效果本次对抗中相持不下"
    return "抵抗方效果本次对抗中完全碾压了发起方效果"


def format_buffs(buffs):
    return f" * {' * '.join(buffs)}" if buffs else ""


def build_system_injection(action_type, initiator_stats, target_stats, delta, tier):
    init_ability = initiator_stats["ability"] if "(动态裁决)" not in initiator_stats["buffs"] else "天灾/环境特征"
    tgt_ability = target_stats["ability"] if "(动态裁决)" not in target_stats["buffs"] else "阻碍/掩体特征"

    injection = f"\n【机制检定】{action_type.upper()}\n"

    if "(动态裁决)" in initiator_stats["buffs"]:
        injection += f"[发起方] {initiator_stats['name']} ➔ 能力/特征: 【{init_ability}】\n"
        injection += (
            f"         公式: (环境/天灾基数 {initiator_stats['base']}) + D20({initiator_stats['d20']}) "
            f"= 出力 {initiator_stats['final']:.1f}\n"
        )
    else:
        injection += f"[发起方] {initiator_stats['name']} ➔ 能力/特征: 【{init_ability}】\n"
        injection += (
            f"         公式: ({initiator_stats['base'] * initiator_stats['mastery']:.1f} * "
            f"体{initiator_stats['phys']} * 心{initiator_stats['ment']} * "
            f"状态特质{initiator_stats['cond']:.2f}{format_buffs(initiator_stats['buffs'])}) + "
            f"D20({initiator_stats['d20']}) = 出力 {initiator_stats['final']:.1f}\n"
        )

    if "(动态裁决)" in target_stats["buffs"]:
        injection += f"[对抗方] {target_stats['name'] or '环境'} ➔ 应对/阻碍: 【{tgt_ability}】\n"
        injection += (
            f"         公式: (环境/机关基数 {target_stats['base']}) + D20({target_stats['d20']}) "
            f"= 抵抗 {target_stats['final']:.1f}\n"
        )
    else:
        injection += f"[对抗方] {target_stats['name'] or '环境'} ➔ 应对/阻碍: 【{tgt_ability}】\n"
        injection += (
            f"         公式: ({target_stats['base'] * target_stats['mastery']:.1f} * "
            f"体{target_stats['phys']} * 心{target_stats['ment']} * "
            f"状态特质{target_stats['cond']:.2f}{format_buffs(target_stats['buffs'])}) + "
            f"D20({target_stats['d20']}) = 抵抗 {target_stats['final']:.1f}\n"
        )

    injection += f"【裁决结果】{tier} (Δ: {delta:.1f})\n"
    injection += "指令: 严格服从裁决。合理映射上述优劣势乘区与运气对撞过程，禁止显式暴露任何数字。"
    return injection


def run_standard_adjudication(
    action_type,
    initiator_assets,
    target_assets,
    world_anchor_text,
    ability_name,
    initiator_name,
    target_name,
    target_ongoing_action,
    major_graph,
    is_social=False,
    ability_invalid=False,  # 新增：能力无效标志
):
    initiator_stats = get_entity_combat_stats(
        initiator_name,
        ability_name,
        is_defense=False,
        opp_name=target_name,
        matched_assets=initiator_assets,
        action_type=action_type,
        major_graph=major_graph,
        world_anchor_text=world_anchor_text,
        is_social=is_social,
    )
    target_stats = get_entity_combat_stats(
        target_name,
        target_ongoing_action,
        is_defense=True,
        opp_name=initiator_name,
        matched_assets=target_assets,
        action_type=action_type,
        major_graph=major_graph,
        world_anchor_text=world_anchor_text,
        is_social=is_social,
    )

    # 能力无效惩罚：发起方效果减半
    if ability_invalid:
        initiator_stats["final"] = int(initiator_stats["final"] * 0.5)
        initiator_stats["buffs"].append("能力无效(x0.5)")

    delta = initiator_stats["final"] - target_stats["final"]
    tier = resolve_delta_tier(delta)
    return build_system_injection(action_type, initiator_stats, target_stats, delta, tier)
