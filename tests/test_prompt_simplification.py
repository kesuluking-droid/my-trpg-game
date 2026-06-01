# -*- coding: utf-8 -*-
"""
test_prompt_simplification.py — Prompt 精简效果对比测试

对比原版 Prompt 与精简版 Prompt 的效果差异
"""

import sys
sys.path.insert(0, 'd:\\game\\AI')

from sandbox_intent_engine import build_intent_parse_prompt

# 精简版 Prompt 模板
_INTENT_PARSE_SYSTEM_TEMPLATE_SIMPLIFIED = """你是跑团意图解析引擎。基于玩家行为和实体标签，提取意图并判定风险。
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

【当前玩家】{pc_name}
【背包】{inventory_snapshot}
【实体名录】{entity_glossary}
【前情】{recent_context}
"""


def build_intent_parse_prompt_simplified(pc_name: str, inventory_snapshot: str, entity_glossary: str, recent_context: str) -> str:
    return _INTENT_PARSE_SYSTEM_TEMPLATE_SIMPLIFIED.format(
        pc_name=pc_name,
        inventory_snapshot=inventory_snapshot,
        entity_glossary=entity_glossary,
        recent_context=recent_context,
    )


def compare_prompts():
    """对比两个版本的 Prompt 长度"""
    test_args = {
        "pc_name": "方拓",
        "inventory_snapshot": "长剑, 火把",
        "entity_glossary": "山贼[敌人] 能力:快刀,铁布衫 | 黑衣人[刺客] 能力:偷袭,毒镖",
        "recent_context": "山贼挡住了去路",
    }
    
    original = build_intent_parse_prompt(**test_args)
    simplified = build_intent_parse_prompt_simplified(**test_args)
    
    print("=" * 70)
    print("Prompt 长度对比")
    print("=" * 70)
    print(f"原版: {len(original)} 字符, {len(original.split(chr(10)))} 行")
    print(f"精简版: {len(simplified)} 字符, {len(simplified.split(chr(10)))} 行")
    print(f"压缩率: {(1 - len(simplified)/len(original))*100:.1f}%")
    print()
    
    # 关键内容检查
    print("=" * 70)
    print("关键内容保留检查")
    print("=" * 70)
    
    key_contents = [
        "detected_ability",
        "action_category",
        "is_risk",
        "world_state_change",
        "entity_annotations",
        "action_sequence",
        "temporary_items",
        "constraints",
        "canonical_name",
    ]
    
    for key in key_contents:
        in_orig = key in original
        in_simp = key in simplified
        status = "✅" if in_simp else "❌"
        print(f"{status} {key}: 原版{'有' if in_orig else '无'}, 精简版{'有' if in_simp else '无'}")
    
    return original, simplified


if __name__ == "__main__":
    compare_prompts()
