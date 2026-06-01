# -*- coding: utf-8 -*-
"""
cli_test_runner.py — 通用 CLI 测试运行器

【用法】
    # 基本测试
    python cli_test_runner.py --input "我拔出长剑，使用基础剑法向山贼刺去"

    # 指定场景上下文
    python cli_test_runner.py --input "我拔出长剑..." --scene "一个山贼拦住了你的去路"

    # 指定玩家背包
    python cli_test_runner.py --input "我攻击..." --inventory "长剑,盾牌,火把"

    # 查看所有配置选项
    python cli_test_runner.py --help

    # 运行预设测试用例
    python cli_test_runner.py --preset ability_recognition
    python cli_test_runner.py --preset full_pipeline
    python cli_test_runner.py --preset combat_only

【设计原则】
- 所有输入端可配置
- 输出端固定返回：意图解析结果、裁决结果、PRO叙事、所有中间数据
- 预设测试用例可扩展
"""

import argparse
import json
import os
import re
import sys
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

# ============================================================================
# 0. API 密钥加载
# ============================================================================
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

if not _api_key:
    print("❌ 错误: 未找到 DEEPSEEK_API_KEY")
    sys.exit(1)

# ============================================================================
# 1. Streamlit Mock
# ============================================================================
class MockSessionState:
    def __init__(self):
        self._data = {
            "user_api_key": _api_key,
            "minor_npcs": {},
            "environment_assets": {},
            "creative_mode": False,
            "current_user": "test_user",
        }
    def get(self, key, default=None): return self._data.get(key, default)
    def __getitem__(self, key): return self._data[key]
    def __setitem__(self, key, value): self._data[key] = value
    def __contains__(self, key): return key in self._data
    def __iter__(self): return iter(self._data)
    def keys(self): return self._data.keys()

class MockSt:
    session_state = MockSessionState()
    secrets = dict(
        DEEPSEEK_API_KEY=_api_key,
        SUPABASE_URL="https://placeholder.supabase.co",
        SUPABASE_KEY="placeholder-key",
    )
    @staticmethod
    def cache_resource(func): return func
    @staticmethod
    def cache_data(func): return func

try:
    import streamlit as real_st
    if not hasattr(real_st, 'cache_resource'): real_st.cache_resource = MockSt.cache_resource
    if not hasattr(real_st, 'cache_data'): real_st.cache_data = MockSt.cache_data
    sys.modules['streamlit'] = real_st
except ImportError:
    sys.modules['streamlit'] = MockSt()

# ============================================================================
# 2. 核心模块导入
# ============================================================================
from sandbox_intent_parser import parse_and_adjudicate_intent
from sandbox_rules.factory import AdjudicatorFactory

# ============================================================================
# 3. 测试用例配置
# ============================================================================
@dataclass
class EntityStats:
    """实体（六维）数据配置"""
    # 能力: {能力名: base_power}
    capabilities: dict = field(default_factory=dict)
    # 背包: [物品名, ...]
    inventory: list = field(default_factory=list)
    # 初始手持: [物品名, ...]
    held_items: list = field(default_factory=list)
    # 物理状态: multiplier
    physical_mult: float = 1.0
    physical_desc: str = "健康"
    # 精神状态: multiplier
    mental_mult: float = 1.0
    mental_desc: str = "平静"
    # 特质: [(特质名, 效果描述), ...]
    traits: list = field(default_factory=list)
    # 通用战斗经验
    combat_exp: float = 1.0
    # 标签
    tags: list = field(default_factory=list)


@dataclass
class TestCase:
    """测试用例配置"""
    name: str
    # 玩家输入
    user_input: str
    # 场景上下文
    scene_context: str = "一个山贼拦住了你的去路，手持山贼刀，面目凶狠。"
    # 玩家名称
    pc_name: str = "方拓"
    # 玩家六维数据
    pc_stats: EntityStats = field(default_factory=EntityStats)
    # NPC列表: {NPC名: EntityStats}
    npcs: dict = field(default_factory=dict)
    # 关系: [(source, target, relation, strength), ...]
    relations: list = field(default_factory=list)
    # 世界设定
    world_anchor: str = "【威力比例尺】凡人极限约25，低阶武者30-50，中阶50-80，高阶80+"
    # 是否跳过裁决（仅意图解析）
    skip_adjudication: bool = False
    # 物品合法性检查列表
    expected_items: list = field(default_factory=list)


def build_test_graph(tc: TestCase) -> dict:
    """根据 TestCase 构建测试图谱"""
    entities = {}

    # 玩家
    pc = {
        "desc": "测试主角",
        "tags": ["玩家"] + tc.pc_stats.tags,
        "1_relational_facts": {},
        "2_dynamic_status": {
            "physical": {"desc": tc.pc_stats.physical_desc, "multiplier": tc.pc_stats.physical_mult},
            "mental": {"desc": tc.pc_stats.mental_desc, "multiplier": tc.pc_stats.mental_mult},
        },
        "3_capabilities": {},
        "4_experience_factors": {"general_combat": tc.pc_stats.combat_exp, "specific_match": {}},
        "5_traits": [{"name": t, "effect": e} for t, e in tc.pc_stats.traits] if tc.pc_stats.traits else [],
        "6_inventory": {},
        "7_held_items": {},
    }
    for name, power in tc.pc_stats.capabilities.items():
        pc["3_capabilities"][name] = {
            "base_power": power,
            "mastery_level": 1.0,
            "domains": ["通用"],
            "features": ["测试能力"],
        }
    for item in tc.pc_stats.inventory:
        pc["6_inventory"][item] = {"tags": ["通用"], "multiplier": 1.0, "features": ["测试物品"]}
    for item in tc.pc_stats.held_items:
        pc["7_held_items"][item] = {"tags": ["通用"], "multiplier": 1.0, "features": ["测试物品"]}
    entities[tc.pc_name] = pc

    # NPC们
    for npc_name, stats in tc.npcs.items():
        npc = {
            "desc": f"测试NPC",
            "tags": stats.tags or ["敌人"],
            "1_relational_facts": {},
            "2_dynamic_status": {
                "physical": {"desc": stats.physical_desc, "multiplier": stats.physical_mult},
                "mental": {"desc": stats.mental_desc, "multiplier": stats.mental_mult},
            },
            "3_capabilities": {},
            "4_experience_factors": {"general_combat": stats.combat_exp, "specific_match": {}},
            "5_traits": [{"name": t, "effect": e} for t, e in stats.traits] if stats.traits else [],
            "6_inventory": {},
            "7_held_items": {},
        }
        for name, power in stats.capabilities.items():
            npc["3_capabilities"][name] = {
                "base_power": power,
                "mastery_level": 1.0,
                "domains": ["战斗"],
                "features": ["测试能力"],
            }
        for item in stats.inventory:
            npc["6_inventory"][item] = {"tags": ["武器"], "multiplier": 1.0, "features": ["测试物品"]}
        entities[npc_name] = npc

    # 关系
    relations = [{"source": s, "target": t, "relation": r, "strength": w} for s, t, r, w in tc.relations]

    return {"entities": entities, "relations": relations}


# ============================================================================
# 4. 预设测试用例
# ============================================================================
PRESETS: dict[str, TestCase] = {}


def _register_preset(name: str, tc: TestCase):
    PRESETS[name] = tc


# 预设1: 能力识别测试
_register_preset("ability_recognition", TestCase(
    name="能力识别测试",
    user_input="山贼使用快刀劈向我",
    pc_stats=EntityStats(
        capabilities={"基础剑法": 15, "本能闪避": 12},
        inventory=["长剑", "火把"],
    ),
    npcs={"山贼": EntityStats(
        capabilities={"快刀": 14, "铁布衫": 10},
        inventory=["山贼刀"],
        tags=["敌人", "山贼"],
    )},
    expected_items=["快刀"],
))


# 预设2: 完整流程测试
_register_preset("full_pipeline", TestCase(
    name="完整流程测试",
    user_input="我拔出长剑，使用基础剑法向山贼刺去",
    pc_stats=EntityStats(
        capabilities={"基础剑法": 15, "本能闪避": 12},
        inventory=["长剑", "火把"],
    ),
    npcs={"山贼": EntityStats(
        capabilities={"快刀": 14, "铁布衫": 10},
        inventory=["山贼刀"],
        tags=["敌人", "山贼"],
        physical_mult=0.8,
        mental_mult=1.1,
    )},
    expected_items=["长剑", "基础剑法"],
))


# 预设3: 纯战斗裁决测试
_register_preset("combat_only", TestCase(
    name="纯战斗裁决测试",
    user_input="我用盾牌挡住山贼的攻击",
    pc_stats=EntityStats(
        capabilities={"本能闪避": 12},
        inventory=["长剑", "盾牌"],
    ),
    npcs={"山贼": EntityStats(
        capabilities={"快刀": 14},
        inventory=["山贼刀"],
        tags=["敌人"],
    )},
    expected_items=["盾牌"],
))


# 预设4: 社交对抗测试
_register_preset("social_check", TestCase(
    name="社交对抗测试",
    user_input="我对山贼说：我认识你们老大，放我过去",
    pc_stats=EntityStats(
        capabilities={"说服": 10},
        inventory=[],
    ),
    npcs={"山贼": EntityStats(
        capabilities={"威吓": 12},
        tags=["敌人", "山贼"],
    )},
    expected_items=[],
))


# 预设5: 物品获取测试
_register_preset("item_acquisition", TestCase(
    name="物品获取测试",
    user_input="我从山贼尸体上搜出一把匕首",
    pc_stats=EntityStats(
        capabilities={"搜刮": 8},
        inventory=["长剑"],
    ),
    npcs={"山贼": EntityStats(
        capabilities={},
        inventory=["山贼刀"],
        tags=["敌人", "已死亡"],
    )},
    expected_items=["山贼刀", "匕首"],
))


# 预设6: 模糊能力引用测试
_register_preset("fuzzy_ability", TestCase(
    name="模糊能力引用测试",
    user_input="山贼使出了他的绝招",
    pc_stats=EntityStats(
        capabilities={"本能闪避": 12},
        inventory=["长剑"],
    ),
    npcs={"山贼": EntityStats(
        capabilities={"快刀": 14, "铁布衫": 10},
        inventory=["山贼刀"],
        tags=["敌人"],
    )},
    expected_items=["快刀"],
))


# ============================================================================
# 5. 测试运行器
# ============================================================================
class TestRunner:
    def __init__(self, tc: TestCase):
        self.tc = tc
        self.graph = build_test_graph(tc)
        self.results: dict = {}

    def print_initial_state(self):
        """打印初始人物状态"""
        pc = self.graph["entities"].get(self.tc.pc_name, {})
        print(f"\n📊 初始人物状态:")
        print(f"   {'─'*60}")
        print(f"   玩家 [{self.tc.pc_name}]:")
        caps = pc.get("3_capabilities", {})
        print(f"      能力: {', '.join(caps.keys()) if caps else '无'}")
        inv = pc.get("6_inventory", {})
        print(f"      背包: {', '.join(inv.keys()) if inv else '空'}")
        held = pc.get("7_held_items", {})
        print(f"      手持: {', '.join(held.keys()) if held else '空'}")
        for npc_name in self.tc.npcs:
            npc = self.graph["entities"].get(npc_name, {})
            npc_caps = npc.get("3_capabilities", {})
            npc_inv = npc.get("6_inventory", {})
            print(f"   NPC [{npc_name}]:")
            print(f"      能力: {', '.join(npc_caps.keys()) if npc_caps else '无'}")
            print(f"      背包: {', '.join(npc_inv.keys()) if npc_inv else '空'}")
        print(f"   {'─'*60}")

    def validate_items(self):
        """验证物品合法性"""
        pc = self.graph["entities"].get(self.tc.pc_name, {})
        inventory = pc.get("6_inventory", {})
        capabilities = pc.get("3_capabilities", {})

        print(f"\n🔍 物品合法性验证:")
        valid = True
        for item in self.tc.expected_items:
            found = False
            location = ""
            if item in inventory:
                found = True
                location = "玩家背包"
            elif item in capabilities:
                found = True
                location = "玩家能力"
            elif item in pc.get("7_held_items", {}):
                found = True
                location = "玩家手持"
            else:
                # 检查 NPC 能力
                for npc_name, npc_data in self.graph["entities"].items():
                    if npc_name == self.tc.pc_name:
                        continue
                    if item in npc_data.get("3_capabilities", {}):
                        found = True
                        location = f"NPC({npc_name})能力"
                        break
                    if item in npc_data.get("6_inventory", {}):
                        found = True
                        location = f"NPC({npc_name})背包"
                        break

            if found:
                print(f"   ✅ '{item}' 存在于 {location}")
            else:
                print(f"   ❌ '{item}' 不存在于任何位置！")
                valid = False
        return valid

    def run_intent_parse(self):
        """步骤1: 意图解析"""
        print(f"\n[步骤1] 意图解析 (FLASH)...")

        active_scene = [
            {"role": "assistant", "content": self.tc.scene_context},
            {"role": "user", "content": self.tc.user_input},
        ]

        try:
            result = parse_and_adjudicate_intent(
                user_input=self.tc.user_input,
                active_scene=active_scene,
                major_graph=self.graph,
                minor_npcs={},
                environment_assets={},
                pc_name=self.tc.pc_name,
            )
            parsed = result.get("parsed_intent", {})
            self.graph = result.get("major_graph", self.graph)

            print(f"   ✅ 完成")
            print(f"   📊 意图解析结果:")
            print(f"      - intended_action: {parsed.get('intended_action')}")
            print(f"      - action_category: {parsed.get('action_category')}")
            print(f"      - detected_ability: {parsed.get('detected_ability')}")
            print(f"      - initiator_entity: {parsed.get('initiator_entity')}")
            print(f"      - target_entity: {parsed.get('target_entity')}")
            print(f"      - target_ongoing_action: {parsed.get('target_ongoing_action')}")
            print(f"      - is_risk: {parsed.get('is_risk')}")

            self.results["intent_parse"] = parsed
            return parsed
        except Exception as e:
            print(f"   ❌ 错误: {e}")
            import traceback
            traceback.print_exc()
            self.results["intent_parse_error"] = str(e)
            return None

    def run_adjudication(self, parsed: dict):
        """步骤2: 裁决"""
        if self.tc.skip_adjudication or not parsed:
            return None

        category = parsed.get("action_category", "")
        if category not in ('combat', 'skill', 'social', 'stealth'):
            print(f"\n[步骤2] 裁决: 跳过（非对抗类行为: {category}）")
            return None

        print(f"\n[步骤2] 裁决 (FLASH)...")

        try:
            adjudicator = AdjudicatorFactory.create(category)
            injection = adjudicator.execute(
                initiator_assets=parsed.get("initiator_matched_assets", []),
                target_assets=parsed.get("target_matched_assets", []),
                world_tier=self.tc.world_anchor,
                ability_name=parsed.get("detected_ability"),
                initiator_name=parsed.get("initiator_entity"),
                target_name=parsed.get("target_entity"),
                target_ongoing_action=parsed.get("target_ongoing_action"),
                major_graph=self.graph,
            )

            print(f"   ✅ 裁决完成")
            print(f"   📊 裁决结果:")
            for line in injection.split('\n'):
                if line.strip():
                    print(f"      {line}")

            self.results["adjudication"] = injection
            return injection
        except Exception as e:
            print(f"   ❌ 裁决错误: {e}")
            import traceback
            traceback.print_exc()
            self.results["adjudication_error"] = str(e)
            return None

    def run_pro_narrative(self, adjudication: str):
        """步骤3: PRO 叙事生成"""
        print(f"\n[步骤3] PRO 叙事生成...")

        context_text = f"""你是一个沉浸式 TRPG 叙事引擎。基于以下信息生成叙事回复。

【世界设定】{self.tc.world_anchor}
【当前场景】{self.tc.scene_context}

{adjudication or ''}

【叙事约束】
- 严禁在叙事文本中显式写出伤害数字、HP、DC、掷骰点数或公式
- 以感官描写与因果映射替代数值播报
- 文风紧凑，贴合历史对话语气"""

        try:
            from core_engine import generate_chat_stream

            pro_output = ""
            for chunk in generate_chat_stream(context_text, [{"role": "user", "content": self.tc.user_input}]):
                pro_output += chunk

            print(f"   ✅ PRO 生成完成 ({len(pro_output)} 字符)")
            print(f"\n   📝 PRO 叙事输出:")
            print(f"   {'─'*60}")
            for line in pro_output.split('\n'):
                print(f"   {line}")
            print(f"   {'─'*60}")

            self.results["pro_output"] = pro_output
            return pro_output
        except Exception as e:
            print(f"   ❌ PRO 生成错误: {e}")
            import traceback
            traceback.print_exc()
            self.results["pro_error"] = str(e)
            return None

    def judge(self, pro_output: str):
        """步骤4: 自动评判"""
        print(f"\n[步骤4] 结果评判:")

        issues = []

        # 检查数值泄露
        if pro_output:
            number_leaks = re.findall(r'\b\d{2,}\s*(HP|伤害|DC|骰|点数|检定)', pro_output)
            if number_leaks:
                issues.append(f"⚠ 数值泄露: {number_leaks}")

            if len(pro_output) < 20:
                issues.append("⚠ PRO 输出过短")

        if issues:
            for issue in issues:
                print(f"   {issue}")
        else:
            print(f"   ✅ PRO 叙事合理，无数值泄露")

        self.results["issues"] = issues
        return issues

    def run(self):
        """执行完整测试流程"""
        print(f"\n{'='*70}")
        print(f"🧪 {self.tc.name}")
        print(f"{'='*70}")

        self.print_initial_state()
        self.validate_items()

        print(f"\n📋 玩家输入: {self.tc.user_input}")

        parsed = self.run_intent_parse()
        adjudication = self.run_adjudication(parsed)
        pro_output = self.run_pro_narrative(adjudication)
        issues = self.judge(pro_output)

        print(f"\n{'='*70}")
        print(f"✅ 测试完成")
        print(f"{'='*70}")

        return self.results


# ============================================================================
# 6. 主入口
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="通用 CLI 测试运行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
预设测试用例:
  ability_recognition  - NPC能力识别测试
  full_pipeline        - 完整流程测试（意图解析→裁决→PRO）
  combat_only          - 纯战斗裁决测试
  social_check         - 社交对抗测试
  item_acquisition     - 物品获取测试
  fuzzy_ability        - 模糊能力引用测试

示例:
  python cli_test_runner.py --preset full_pipeline
  python cli_test_runner.py --input "我攻击山贼" --inventory "长剑,盾牌"
  python cli_test_runner.py --input "山贼使用快刀" --npc "山贼:快刀14,铁布衫10"
        """
    )

    parser.add_argument("--preset", choices=list(PRESETS.keys()),
                        help="使用预设测试用例")
    parser.add_argument("--input", "-i", help="玩家输入")
    parser.add_argument("--scene", "-s", help="场景上下文")
    parser.add_argument("--pc-name", help="玩家名称")
    parser.add_argument("--inventory", help="玩家背包（逗号分隔）")
    parser.add_argument("--capabilities", help="玩家能力（格式: 能力名:power,...)")
    parser.add_argument("--npc", action="append", help="NPC配置（格式: NPC名:能力1:power1,能力2:power2）")
    parser.add_argument("--output-json", help="将结果输出为 JSON 文件")

    args = parser.parse_args()

    print(f"\n{'='*70}")
    print(f"🚀 CLI 测试运行器 v2.0")
    print(f"{'='*70}")
    print(f"API Key: {'*'*20}{_api_key[-4:]}")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 确定测试用例
    if args.preset:
        tc = PRESETS[args.preset]
        print(f"预设: {args.preset}")
    else:
        # 从命令行参数构建
        if not args.input:
            print("❌ 错误: 必须指定 --input 或 --preset")
            sys.exit(1)

        pc_stats = EntityStats()
        if args.inventory:
            pc_stats.inventory = [x.strip() for x in args.inventory.split(',')]
        if args.capabilities:
            for cap in args.capabilities.split(','):
                if ':' in cap:
                    name, power = cap.split(':', 1)
                    pc_stats.capabilities[name.strip()] = float(power)

        npcs = {}
        if args.npc:
            for npc_spec in args.npc:
                parts = npc_spec.split(':')
                npc_name = parts[0]
                stats = EntityStats(tags=["敌人"])
                for cap in parts[1:]:
                    if ':' in cap:
                        name, power = cap.split(':', 1)
                        stats.capabilities[name.strip()] = float(power)
                npcs[npc_name] = stats

        tc = TestCase(
            name="命令行测试",
            user_input=args.input,
            scene_context=args.scene or "无",
            pc_name=args.pc_name or "方拓",
            pc_stats=pc_stats,
            npcs=npcs,
        )

    # 运行测试
    runner = TestRunner(tc)
    results = runner.run()

    # JSON 输出
    if args.output_json:
        with open(args.output_json, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n📄 结果已保存到: {args.output_json}")

    return results


if __name__ == "__main__":
    main()
