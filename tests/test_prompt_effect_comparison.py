# -*- coding: utf-8 -*-
"""
test_prompt_effect_comparison.py — Prompt 精简效果实际测试

用相同的测试输入，对比原版和精简版的输出质量
"""

import sys
import os
sys.path.insert(0, 'd:\\game\\AI')

# 加载 API 密钥
_api_key = None
_secrets_path = '.streamlit/secrets.toml'
if os.path.exists(_secrets_path):
    with open(_secrets_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                key, value = line.split('=', 1)
                if key.strip() in ('DEEPSEEK_API_KEY', 'USER_API_KEY'):
                    _api_key = value.strip().strip('"').strip("'")
                    os.environ['DEEPSEEK_API_KEY'] = _api_key

# Mock Streamlit
class MockSessionState:
    def __init__(self):
        self._data = {"user_api_key": _api_key, "minor_npcs": {}, "environment_assets": {}, "creative_mode": False, "current_user": "test_user"}
    def get(self, key, default=None): return self._data.get(key, default)
    def __getitem__(self, key): return self._data[key]
    def __setitem__(self, key, value): self._data[key] = value
    def __contains__(self, key): return key in self._data
    def __iter__(self): return iter(self._data)
    def keys(self): return self._data.keys()

class MockSt:
    session_state = MockSessionState()
    secrets = dict(DEEPSEEK_API_KEY=_api_key, SUPABASE_URL="https://placeholder.supabase.co", SUPABASE_KEY="placeholder-key")
    @staticmethod
    def cache_resource(func): return func
    @staticmethod
    def cache_data(func): return func

sys.modules['streamlit'] = MockSt()

from openai import OpenAI
from sandbox_config import MODEL_FLASH

# 精简版 Prompt
_SIMPLIFIED_PROMPT = """你是跑团意图解析引擎。基于玩家行为和实体标签，提取意图并判定风险。
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


def call_llm(prompt: str, user_input: str) -> dict:
    """调用 LLM 获取意图解析结果"""
    client = OpenAI(api_key=_api_key, base_url="https://api.deepseek.com")
    
    response = client.chat.completions.create(
        model=MODEL_FLASH,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_input},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    
    import json
    return json.loads(response.choices[0].message.content)


def test_case(user_input: str, scene_context: str, entity_glossary: str):
    """测试单个用例，对比原版和精简版"""
    from sandbox_intent_engine import build_intent_parse_prompt
    
    original_prompt = build_intent_parse_prompt(
        pc_name="方拓",
        inventory_snapshot="长剑, 火把",
        entity_glossary=entity_glossary,
        recent_context=scene_context,
    )
    
    simplified_prompt = _SIMPLIFIED_PROMPT.format(
        pc_name="方拓",
        inventory_snapshot="长剑, 火把",
        entity_glossary=entity_glossary,
        recent_context=scene_context,
    )
    
    print(f"\n{'='*70}")
    print(f"测试输入: {user_input}")
    print(f"{'='*70}")
    
    # 原版
    print(f"\n[原版 Prompt: {len(original_prompt)} 字符]")
    try:
        orig_result = call_llm(original_prompt, user_input)
        print(f"✅ 原版解析成功")
        print(f"   intended_action: {orig_result.get('intended_action')}")
        print(f"   action_category: {orig_result.get('action_category')}")
        print(f"   detected_ability: {orig_result.get('detected_ability')}")
        print(f"   is_risk: {orig_result.get('is_risk')}")
    except Exception as e:
        print(f"❌ 原版解析失败: {e}")
        orig_result = None
    
    # 精简版
    print(f"\n[精简版 Prompt: {len(simplified_prompt)} 字符]")
    try:
        simp_result = call_llm(simplified_prompt, user_input)
        print(f"✅ 精简版解析成功")
        print(f"   intended_action: {simp_result.get('intended_action')}")
        print(f"   action_category: {simp_result.get('action_category')}")
        print(f"   detected_ability: {simp_result.get('detected_ability')}")
        print(f"   is_risk: {simp_result.get('is_risk')}")
    except Exception as e:
        print(f"❌ 精简版解析失败: {e}")
        simp_result = None
    
    # 对比
    if orig_result and simp_result:
        print(f"\n[对比结果]")
        matches = []
        for key in ['action_category', 'is_risk', 'detected_ability']:
            orig_val = orig_result.get(key)
            simp_val = simp_result.get(key)
            match = orig_val == simp_val
            matches.append(match)
            status = "✅" if match else "⚠️"
            print(f"   {status} {key}: 原版={orig_val}, 精简版={simp_val}")
        
        if all(matches):
            print(f"   ✅ 核心字段完全一致")
        else:
            print(f"   ⚠️ 存在差异，需人工复核")
    
    return orig_result, simp_result


def main():
    print("=" * 70)
    print("Prompt 精简效果对比测试")
    print("=" * 70)
    print(f"API Key: {'*'*20}{_api_key[-4:]}")
    
    test_cases = [
        {
            "user_input": "山贼使用快刀劈向我",
            "scene_context": "山贼挡住了去路",
            "entity_glossary": "山贼[敌人] 能力:快刀,铁布衫",
        },
        {
            "user_input": "我拔出长剑，使用基础剑法向山贼刺去",
            "scene_context": "山贼挡住了去路，手持山贼刀",
            "entity_glossary": "山贼[敌人] 能力:快刀,铁布衫",
        },
        {
            "user_input": "山贼使出了他的绝招",
            "scene_context": "山贼冷笑一声",
            "entity_glossary": "山贼[敌人] 能力:快刀,铁布衫",
        },
    ]
    
    results = []
    for tc in test_cases:
        orig, simp = test_case(**tc)
        results.append((orig, simp))
    
    print(f"\n{'='*70}")
    print("测试完成")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
