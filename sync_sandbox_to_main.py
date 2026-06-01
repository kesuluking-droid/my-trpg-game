# -*- coding: utf-8 -*-
"""
sync_sandbox_to_main.py — 沙盒版本 → 主版本 自动同步工具

使用方法:
    python sync_sandbox_to_main.py                    # 同步所有文件
    python sync_sandbox_to_main.py --file FILE_NAME   # 同步单个文件
    python sync_sandbox_to_main.py --dry-run          # 预览模式，不实际写入
    python sync_sandbox_to_main.py --check            # 检查差异
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Optional

# 文件映射配置：沙盒文件 -> 主版本文件
FILE_MAPPING = {
    # 根目录文件
    "sandbox_config.py": "config.py",
    "sandbox_core_engine.py": "core_engine.py",
    "sandbox_intent_engine.py": "intent_engine.py",
    "sandbox_intent_parser.py": "intent_parser.py",
    "sandbox_integration.py": "integration.py",
    "sandbox_item_instances.py": "item_instances.py",
    "sandbox_memory_manager.py": "memory_manager.py",
    "sandbox_npc_lifecycle.py": "npc_lifecycle.py",
    "sandbox_undo_manager.py": "undo_manager.py",
    "sandbox_ui_feedback.py": "ui_feedback.py",
    "sandbox_turn_engine.py": "turn_engine.py",
    "sandbox_turn_runtime.py": "turn_runtime.py",
    "sandbox_ability_matcher.py": "ability_matcher.py",
    "sandbox_app.py": "app.py",
    
    # sandbox_rules/ 目录文件
    "sandbox_rules/__init__.py": "rules/__init__.py",
    "sandbox_rules/adjudication_utils.py": "rules/adjudication_utils.py",
    "sandbox_rules/atomic_adjudicator.py": "rules/atomic_adjudicator.py",
    "sandbox_rules/base_adjudicator.py": "rules/base_adjudicator.py",
    "sandbox_rules/classic_combat.py": "rules/classic_combat.py",
    "sandbox_rules/complex_encounter.py": "rules/complex_encounter.py",
    "sandbox_rules/factory.py": "rules/factory.py",
    "sandbox_rules/sandbox_composite_adjudicator.py": "rules/sandbox_composite_adjudicator.py",
    "sandbox_rules/skill_check.py": "rules/skill_check.py",
    "sandbox_rules/social_check.py": "rules/social_check.py",
    "sandbox_rules/stealth_check.py": "rules/stealth_check.py",
}

# 需要替换的导入路径模式
# ⚠️ 顺序很重要：先替换长的、具体的，再替换短的
IMPORT_REPLACEMENTS = [
    # sandbox_rules/ 模块导入 (必须先处理，避免被后面的规则部分匹配)
    (r"from sandbox_rules\.", "from rules."),
    (r"import sandbox_rules\.", "import rules."),
    
    # 根目录模块导入 (按字母长度降序，避免部分匹配)
    (r"from sandbox_ability_matcher", "from ability_matcher"),
    (r"import sandbox_ability_matcher", "import ability_matcher"),
    (r"from sandbox_intent_engine", "from intent_engine"),
    (r"import sandbox_intent_engine", "import intent_engine"),
    (r"from sandbox_intent_parser", "from intent_parser"),
    (r"import sandbox_intent_parser", "import intent_parser"),
    (r"from sandbox_item_instances", "from item_instances"),
    (r"import sandbox_item_instances", "import item_instances"),
    (r"fromsandbox_memory_manager", "from memory_manager"),  # 处理连在一起的情况
    (r"from sandbox_memory_manager", "from memory_manager"),
    (r"import sandbox_memory_manager", "import memory_manager"),
    (r"from sandbox_npc_lifecycle", "from npc_lifecycle"),
    (r"import sandbox_npc_lifecycle", "import npc_lifecycle"),
    (r"from sandbox_undo_manager", "from undo_manager"),
    (r"import sandbox_undo_manager", "import undo_manager"),
    (r"from sandbox_ui_feedback", "from ui_feedback"),
    (r"import sandbox_ui_feedback", "import ui_feedback"),
    (r"from sandbox_turn_engine", "from turn_engine"),
    (r"import sandbox_turn_engine", "import turn_engine"),
    (r"from sandbox_turn_runtime", "from turn_runtime"),
    (r"import sandbox_turn_runtime", "import turn_runtime"),
    (r"from sandbox_core_engine", "from core_engine"),
    (r"import sandbox_core_engine", "import core_engine"),
    (r"from sandbox_integration", "from integration"),
    (r"import sandbox_integration", "import integration"),
    (r"from sandbox_config", "from config"),
    (r"import sandbox_config", "import config"),
    (r"from sandbox_app", "from app"),
    (r"import sandbox_app", "import app"),
]


def remove_maintenance_header(content: str) -> str:
    """移除维护提醒头部"""
    # 匹配多种格式的维护头部
    patterns = [
        # 标准格式 (sandbox_rules 文件使用)
        r"# ={58,62}\n# 维护提醒\n# -{58,62}\n# 本文件为沙盒版本.*?# ={58,62}\n",
        # 扩展格式 (带更多说明文本)
        r"# ={58,62}\n# 维护提醒\n# -{58,62}\n# 本文件为沙盒版本.*?# ={58,62}\n\n",
    ]
    
    for pattern in patterns:
        content = re.sub(pattern, "", content, flags=re.DOTALL)
    
    return content


def transform_imports(content: str) -> str:
    """转换沙盒导入为主版本导入"""
    for pattern, replacement in IMPORT_REPLACEMENTS:
        content = re.sub(pattern, replacement, content)
    return content


def sync_file(sandbox_file: str, main_file: str, dry_run: bool = False) -> tuple[bool, str]:
    """
    同步单个文件
    
    Returns:
        (success: bool, message: str)
    """
    sandbox_path = Path(sandbox_file)
    main_path = Path(main_file)
    
    if not sandbox_path.exists():
        return False, f"❌ 沙盒文件不存在: {sandbox_file}"
    
    # 读取沙盒文件内容
    with open(sandbox_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 转换内容
    transformed_content = remove_maintenance_header(content)
    transformed_content = transform_imports(transformed_content)
    
    if dry_run:
        # 预览模式：显示差异
        if main_path.exists():
            with open(main_path, "r", encoding="utf-8") as f:
                main_content = f.read()
            if transformed_content.strip() == main_content.strip():
                return True, f"➖ {sandbox_file} -> {main_file} (无变化)"
            else:
                return True, f"📝 {sandbox_file} -> {main_file} (有变化，预览模式未写入)"
        else:
            return True, f"➕ {sandbox_file} -> {main_file} (新文件，预览模式未写入)"
    
    # 实际写入
    try:
        # 确保目标目录存在
        main_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(main_path, "w", encoding="utf-8") as f:
            f.write(transformed_content)
        
        return True, f"✅ {sandbox_file} -> {main_file}"
    except Exception as e:
        return False, f"❌ {sandbox_file} -> {main_file}: {str(e)}"


def check_differences() -> list[tuple[str, str, bool]]:
    """检查所有文件的差异，返回 (sandbox_file, main_file, has_diff) 列表"""
    results = []
    for sandbox_file, main_file in FILE_MAPPING.items():
        sandbox_path = Path(sandbox_file)
        main_path = Path(main_file)
        
        if not sandbox_path.exists():
            results.append((sandbox_file, main_file, True))  # 沙盒文件不存在视为有差异
            continue
        
        with open(sandbox_path, "r", encoding="utf-8") as f:
            sandbox_content = f.read()
        
        transformed_content = remove_maintenance_header(sandbox_content)
        transformed_content = transform_imports(transformed_content)
        
        if not main_path.exists():
            results.append((sandbox_file, main_file, True))  # 主版本文件不存在
            continue
        
        with open(main_path, "r", encoding="utf-8") as f:
            main_content = f.read()
        
        has_diff = transformed_content.strip() != main_content.strip()
        results.append((sandbox_file, main_file, has_diff))
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="沙盒版本 → 主版本 自动同步工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python sync_sandbox_to_main.py                    # 同步所有文件
  python sync_sandbox_to_main.py --file sandbox_config.py   # 同步单个文件
  python sync_sandbox_to_main.py --dry-run          # 预览模式
  python sync_sandbox_to_main.py --check            # 检查差异
        """
    )
    parser.add_argument("--file", help="指定要同步的单个沙盒文件")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际写入")
    parser.add_argument("--check", action="store_true", help="检查差异，不执行同步")
    
    args = parser.parse_args()
    
    if args.check:
        print("🔍 检查沙盒版本与主版本的差异...\n")
        differences = check_differences()
        
        diff_count = sum(1 for _, _, has_diff in differences if has_diff)
        
        for sandbox_file, main_file, has_diff in differences:
            status = "📝 有差异" if has_diff else "➖ 一致"
            print(f"{status}: {sandbox_file} -> {main_file}")
        
        print(f"\n总计: {len(differences)} 个文件, {diff_count} 个有差异")
        return
    
    if args.file:
        # 同步单个文件
        if args.file not in FILE_MAPPING:
            print(f"❌ 未知文件: {args.file}")
            print(f"可用文件: {', '.join(FILE_MAPPING.keys())}")
            sys.exit(1)
        
        main_file = FILE_MAPPING[args.file]
        success, message = sync_file(args.file, main_file, args.dry_run)
        print(message)
        sys.exit(0 if success else 1)
    
    # 同步所有文件
    mode = "[预览模式]" if args.dry_run else ""
    print(f"🔄 开始同步沙盒版本到主版本 {mode}\n")
    
    success_count = 0
    fail_count = 0
    
    for sandbox_file, main_file in FILE_MAPPING.items():
        success, message = sync_file(sandbox_file, main_file, args.dry_run)
        print(message)
        if success:
            success_count += 1
        else:
            fail_count += 1
    
    print(f"\n{'='*60}")
    if args.dry_run:
        print(f"预览完成: {success_count} 个文件可同步, {fail_count} 个失败")
    else:
        print(f"同步完成: {success_count} 个文件成功, {fail_count} 个失败")


if __name__ == "__main__":
    main()
