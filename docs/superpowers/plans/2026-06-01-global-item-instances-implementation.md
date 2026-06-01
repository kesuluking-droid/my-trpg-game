# 全局物品实例池 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在沙盒管线中引入全局 `item_instances` 物品实例池，同时保留 `6_inventory` / `7_held_items` 作为兼容索引，解决同物多称与多物同名的问题。

**Architecture:** 新增 `sandbox_item_instances.py` 作为唯一物品实例工具层，负责迁移、创建、解析、移动、消耗与旧索引同步。第一阶段不重写裁决/UI，只保证旧字段继续可读，新字段可追踪；沙盒验证通过后由 `sync_sandbox_to_main.py` 映射到主版本。

**Tech Stack:** Python, unittest, 现有沙盒管线 (`sandbox_*`), `sync_sandbox_to_main.py`。

---

## 文件结构与职责

- Create: `d:\game\AI\sandbox_item_instances.py`  
  全局物品实例池工具层；不依赖原始管线。
- Modify: `d:\game\AI\sync_sandbox_to_main.py`  
  增加 `sandbox_item_instances.py -> item_instances.py` 映射与导入转换。
- Modify: `d:\game\AI\sandbox_intent_parser.py`  
  意图解析后调用 `ensure_item_instances()`，为后续物品字段归一提供实例池基础。
- Modify: `d:\game\AI\sandbox_integration.py`  
  门铃同步新增物品时补写实例池，并同步旧字段兼容索引。
- Modify: `d:\game\AI\sandbox_rules/complex_encounter.py`  
  复合动作执行前确保实例池存在；第一阶段仍通过旧索引参与裁决。
- Test: `d:\game\AI\tests\test_item_instances.py`  
  覆盖旧结构迁移、多火把、手持优先、环境优先、状态变化、堆叠物品。

---

### Task 1: 新增物品实例工具层与迁移测试

**Files:**
- Create: `d:\game\AI\sandbox_item_instances.py`
- Create: `d:\game\AI\tests\test_item_instances.py`

- [ ] **Step 1: 写失败测试：旧背包迁移生成实例池**

在 `tests/test_item_instances.py` 写入：

```python
# -*- coding: utf-8 -*-
import unittest

from sandbox_item_instances import ensure_item_instances


class ItemInstancesMigrationTest(unittest.TestCase):
    def test_legacy_inventory_migrates_to_item_instances(self):
        graph = {
            "entities": {
                "方拓": {
                    "tags": ["玩家"],
                    "6_inventory": {
                        "火把": {"tags": ["照明"], "multiplier": 1.0}
                    },
                    "7_held_items": {},
                }
            }
        }

        migrated = ensure_item_instances(graph)

        self.assertIn("item_instances", migrated)
        inventory_item = migrated["entities"]["方拓"]["6_inventory"]["火把"]
        self.assertIn("instance_id", inventory_item)
        instance_id = inventory_item["instance_id"]
        self.assertIn(instance_id, migrated["item_instances"])
        instance = migrated["item_instances"][instance_id]
        self.assertEqual(instance["canonical_name"], "火把")
        self.assertEqual(instance["holder"], "方拓")
        self.assertEqual(instance["container"], "inventory")
        self.assertEqual(instance["tags"], ["照明"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
cd 'd:\game\AI' ; python -m unittest tests.test_item_instances -v
```

Expected: FAIL，原因是 `sandbox_item_instances` 不存在。

- [ ] **Step 3: 创建 `sandbox_item_instances.py` 的最小实现**

写入：

```python
# -*- coding: utf-8 -*-
"""sandbox_item_instances.py — 沙盒全局物品实例池工具层。"""

from __future__ import annotations

import re
from copy import deepcopy


def _safe_slug(text: str) -> str:
    raw = str(text or "item").strip()
    raw = re.sub(r"\s+", "_", raw)
    raw = re.sub(r"[^\w\u4e00-\u9fff#-]", "", raw)
    return raw or "item"


def _make_instance_id(canonical_name: str, holder: str | None, container: str, existing: dict) -> str:
    base = f"item_{_safe_slug(canonical_name)}_{_safe_slug(holder or 'env')}_{_safe_slug(container)}"
    idx = 1
    while True:
        candidate = f"{base}_{idx:03d}"
        if candidate not in existing:
            return candidate
        idx += 1


def _default_item_kind(name: str, item_data: dict) -> str:
    quantity = item_data.get("quantity", 1)
    stack_words = ["铜钱", "银两", "箭", "粮", "米", "水", "石子", "草药"]
    if isinstance(quantity, (int, float)) and quantity > 1:
        if any(word in str(name) for word in stack_words):
            return "stack"
    return "instance"


def ensure_item_instances(graph: dict) -> dict:
    graph.setdefault("entities", {})
    instances = graph.setdefault("item_instances", {})
    for entity_name, entity in graph.get("entities", {}).items():
        if not isinstance(entity, dict):
            continue
        for slot, container in (("6_inventory", "inventory"), ("7_held_items", "held")):
            items = entity.setdefault(slot, {})
            if not isinstance(items, dict):
                continue
            for item_name, item_data in list(items.items()):
                if not isinstance(item_data, dict):
                    item_data = {"tags": ["通用"], "multiplier": 1.0}
                    items[item_name] = item_data
                instance_id = item_data.get("instance_id")
                canonical_name = item_data.get("canonical_name") or item_name.split("#", 1)[0]
                if not instance_id:
                    instance_id = _make_instance_id(canonical_name, entity_name, container, instances)
                    item_data["instance_id"] = instance_id
                item_data.setdefault("canonical_name", canonical_name)
                if instance_id not in instances:
                    instances[instance_id] = {
                        "instance_id": instance_id,
                        "canonical_name": canonical_name,
                        "display_name": item_name,
                        "item_kind": _default_item_kind(canonical_name, item_data),
                        "holder": entity_name,
                        "owner": entity_name,
                        "container": container,
                        "location": "背包" if container == "inventory" else "手持",
                        "source": slot,
                        "state_tags": item_data.get("state_tags", []),
                        "tags": deepcopy(item_data.get("tags", item_data.get("target_domains", ["通用"]))),
                        "quantity": item_data.get("quantity", 1),
                        "unit": item_data.get("unit"),
                        "multiplier": item_data.get("multiplier", 1.0),
                        "persistence": item_data.get("persistence", "persistent"),
                        "created_from": "legacy_migration",
                        "status": "active",
                    }
    return graph
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
cd 'd:\game\AI' ; python -m unittest tests.test_item_instances -v
```

Expected: PASS。

---

### Task 2: 创建实例、移动实例与兼容索引同步

**Files:**
- Modify: `d:\game\AI\sandbox_item_instances.py`
- Modify: `d:\game\AI\tests\test_item_instances.py`

- [ ] **Step 1: 写测试：创建墙上火把并移动到手持**

追加测试：

```python
from sandbox_item_instances import create_item_instance, move_item_instance, sync_legacy_item_index


class ItemInstanceMovementTest(unittest.TestCase):
    def test_create_wall_torch_and_move_to_held_index(self):
        graph = {"entities": {"方拓": {"6_inventory": {}, "7_held_items": {}}}, "item_instances": {}}
        instance_id = create_item_instance(
            graph,
            "火把",
            {"display_name": "墙上的燃烧火把", "tags": ["照明", "燃烧"], "state_tags": ["燃烧"], "multiplier": 1.0},
            holder=None,
            container="environment",
            location="墙上",
            source="墙上",
        )

        move_item_instance(graph, instance_id, holder="方拓", container="held", location="手持")
        sync_legacy_item_index(graph, "方拓", instance_id, "7_held_items")

        self.assertIn("火把", graph["entities"]["方拓"]["7_held_items"])
        held = graph["entities"]["方拓"]["7_held_items"]["火把"]
        self.assertEqual(held["instance_id"], instance_id)
        self.assertEqual(graph["item_instances"][instance_id]["holder"], "方拓")
        self.assertEqual(graph["item_instances"][instance_id]["container"], "held")
```

- [ ] **Step 2: 实现 `create_item_instance` / `move_item_instance` / `sync_legacy_item_index`**

在 `sandbox_item_instances.py` 追加：

```python
def create_item_instance(graph: dict, canonical_name: str, item_data: dict, *, holder=None, container="environment", location=None, source=None) -> str:
    graph.setdefault("item_instances", {})
    instances = graph["item_instances"]
    instance_id = item_data.get("instance_id") or _make_instance_id(canonical_name, holder, container, instances)
    instances[instance_id] = {
        "instance_id": instance_id,
        "canonical_name": canonical_name,
        "display_name": item_data.get("display_name", canonical_name),
        "item_kind": item_data.get("item_kind", _default_item_kind(canonical_name, item_data)),
        "holder": holder,
        "owner": item_data.get("owner", holder),
        "container": container,
        "location": location,
        "source": source,
        "state_tags": deepcopy(item_data.get("state_tags", [])),
        "tags": deepcopy(item_data.get("tags", item_data.get("target_domains", ["通用"]))),
        "quantity": item_data.get("quantity", 1),
        "unit": item_data.get("unit"),
        "multiplier": item_data.get("multiplier", 1.0),
        "persistence": item_data.get("persistence", "scene_bound"),
        "created_from": item_data.get("created_from", "runtime_create"),
        "status": "active",
    }
    return instance_id


def move_item_instance(graph: dict, instance_id: str, *, holder=None, container=None, location=None) -> dict:
    instance = graph.setdefault("item_instances", {}).get(instance_id)
    if not instance:
        return graph
    if holder is not None:
        instance["holder"] = holder
    if container is not None:
        instance["container"] = container
    if location is not None:
        instance["location"] = location
    return graph


def _legacy_key_for(entity: dict, slot: str, canonical_name: str, instance_id: str) -> str:
    items = entity.setdefault(slot, {})
    for key, data in items.items():
        if isinstance(data, dict) and data.get("instance_id") == instance_id:
            return key
    if canonical_name not in items:
        return canonical_name
    idx = 2
    while f"{canonical_name}#{idx}" in items:
        idx += 1
    return f"{canonical_name}#{idx}"


def sync_legacy_item_index(graph: dict, entity_name: str, instance_id: str, target_slot: str) -> dict:
    entity = graph.setdefault("entities", {}).setdefault(entity_name, {})
    entity.setdefault("6_inventory", {})
    entity.setdefault("7_held_items", {})
    instance = graph.setdefault("item_instances", {}).get(instance_id)
    if not instance:
        return graph
    canonical_name = instance.get("canonical_name") or instance.get("display_name") or instance_id
    key = _legacy_key_for(entity, target_slot, canonical_name, instance_id)
    entity[target_slot][key] = {
        "instance_id": instance_id,
        "canonical_name": canonical_name,
        "display_name": instance.get("display_name", canonical_name),
        "tags": deepcopy(instance.get("tags", ["通用"])),
        "state_tags": deepcopy(instance.get("state_tags", [])),
        "multiplier": instance.get("multiplier", 1.0),
        "quantity": instance.get("quantity", 1),
        "persistence": instance.get("persistence", "persistent"),
    }
    return graph
```

- [ ] **Step 3: 运行测试**

Run:

```powershell
cd 'd:\game\AI' ; python -m unittest tests.test_item_instances -v
```

Expected: PASS。

---

### Task 3: 实现物品引用解析与多火把测试

**Files:**
- Modify: `d:\game\AI\sandbox_item_instances.py`
- Modify: `d:\game\AI\tests\test_item_instances.py`

- [ ] **Step 1: 写测试：手持优先、墙上优先、左右火把歧义**

追加测试：

```python
from sandbox_item_instances import resolve_item_reference


class ItemReferenceResolutionTest(unittest.TestCase):
    def test_use_torch_prefers_held_item(self):
        graph = {"entities": {"方拓": {"6_inventory": {}, "7_held_items": {}}}, "item_instances": {}}
        held_id = create_item_instance(graph, "火把", {"display_name": "手中的火把", "tags": ["照明"]}, holder="方拓", container="held", location="手持")
        wall_id = create_item_instance(graph, "火把", {"display_name": "墙上的火把", "tags": ["照明"]}, holder=None, container="environment", location="墙上")

        result = resolve_item_reference("火把", "火把", graph, "方拓", {"verb": "用"})

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["instance_id"], held_id)
        self.assertNotEqual(result["instance_id"], wall_id)

    def test_take_torch_prefers_environment_item(self):
        graph = {"entities": {"方拓": {"6_inventory": {}, "7_held_items": {}}}, "item_instances": {}}
        inventory_id = create_item_instance(graph, "火把", {"display_name": "背包里的火把", "tags": ["照明"]}, holder="方拓", container="inventory", location="背包")
        wall_id = create_item_instance(graph, "火把", {"display_name": "墙上的火把", "tags": ["照明"]}, holder=None, container="environment", location="墙上")

        result = resolve_item_reference("墙上的火把", "火把", graph, "方拓", {"verb": "拔下"})

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["instance_id"], wall_id)
        self.assertNotEqual(result["instance_id"], inventory_id)

    def test_ambiguous_left_and_right_torches(self):
        graph = {"entities": {"方拓": {"6_inventory": {}, "7_held_items": {}}}, "item_instances": {}}
        left_id = create_item_instance(graph, "火把", {"display_name": "左墙火把", "tags": ["照明"]}, holder=None, container="environment", location="左墙")
        right_id = create_item_instance(graph, "火把", {"display_name": "右墙火把", "tags": ["照明"]}, holder=None, container="environment", location="右墙")

        result = resolve_item_reference("火把", "火把", graph, "方拓", {"verb": "拔下"})

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(set(result["candidates"]), {left_id, right_id})
```

- [ ] **Step 2: 实现 `resolve_item_reference`**

在 `sandbox_item_instances.py` 追加：

```python
def _candidate_score(raw_name: str, instance: dict, pc_name: str, action_context: dict) -> int:
    raw = str(raw_name or "")
    verb = str(action_context.get("verb", ""))
    score = 0
    location = str(instance.get("location") or "")
    container = str(instance.get("container") or "")
    holder = instance.get("holder")
    display = str(instance.get("display_name") or "")

    if holder == pc_name:
        score += 2
    if container == "held":
        score += 3
    if container == "inventory":
        score += 1
    if any(word in raw for word in ["墙", "左", "右", "地", "桌"]):
        if any(word in location or word in display for word in ["墙", "左", "右", "地", "桌"]):
            score += 5
    if any(word in raw for word in ["手", "手里", "手中"]):
        if container == "held":
            score += 6
    if any(word in raw for word in ["背包", "包里"]):
        if container == "inventory":
            score += 6
    if verb in ["用", "挥", "挡", "攻击", "照"] and container == "held":
        score += 4
    if verb in ["拔下", "取下", "捡起", "拿起"] and container == "environment":
        score += 4
    if any(word in raw for word in ["再", "另一", "另一支", "第二"]):
        if container == "held" and holder == pc_name:
            score -= 6
    return score


def resolve_item_reference(raw_name: str, canonical_name: str, graph: dict, pc_name: str, action_context: dict) -> dict:
    ensure_item_instances(graph)
    instances = graph.get("item_instances", {})
    candidates = [
        (instance_id, instance)
        for instance_id, instance in instances.items()
        if instance.get("status", "active") == "active" and instance.get("canonical_name") == canonical_name
    ]
    if not candidates:
        return {"status": "create_new", "canonical_name": canonical_name, "reason": "没有找到同名实例，可按场景创建"}

    scored = [(instance_id, _candidate_score(raw_name, instance, pc_name, action_context)) for instance_id, instance in candidates]
    max_score = max(score for _, score in scored)
    winners = [instance_id for instance_id, score in scored if score == max_score]
    if len(winners) == 1:
        return {"status": "resolved", "instance_id": winners[0], "confidence": max_score, "reason": "根据持有者、位置、动作上下文解析成功"}
    return {"status": "ambiguous", "candidates": winners, "reason": "存在多个同分候选，输入未充分指定"}
```

- [ ] **Step 3: 运行测试**

Run:

```powershell
cd 'd:\game\AI' ; python -m unittest tests.test_item_instances -v
```

Expected: PASS。

---

### Task 4: 消耗、状态变化、堆叠物品

**Files:**
- Modify: `d:\game\AI\sandbox_item_instances.py`
- Modify: `d:\game\AI\tests\test_item_instances.py`

- [ ] **Step 1: 写测试：点燃不新增、消耗移除旧索引、铜钱为 stack**

追加测试：

```python
from sandbox_item_instances import mark_item_consumed, update_item_state_tags


class ItemStateAndStackTest(unittest.TestCase):
    def test_update_state_tags_does_not_create_new_instance(self):
        graph = {"entities": {"方拓": {"6_inventory": {}, "7_held_items": {}}}, "item_instances": {}}
        torch_id = create_item_instance(graph, "火把", {"display_name": "熄灭的火把", "state_tags": ["熄灭"]}, holder="方拓", container="held", location="手持")
        update_item_state_tags(graph, torch_id, add_tags=["燃烧"], remove_tags=["熄灭"])

        self.assertEqual(len(graph["item_instances"]), 1)
        self.assertIn("燃烧", graph["item_instances"][torch_id]["state_tags"])
        self.assertNotIn("熄灭", graph["item_instances"][torch_id]["state_tags"])

    def test_mark_consumed_removes_legacy_index(self):
        graph = {"entities": {"方拓": {"6_inventory": {}, "7_held_items": {}}}, "item_instances": {}}
        torch_id = create_item_instance(graph, "火把", {"display_name": "火把"}, holder="方拓", container="held", location="手持")
        sync_legacy_item_index(graph, "方拓", torch_id, "7_held_items")

        mark_item_consumed(graph, torch_id)

        self.assertEqual(graph["item_instances"][torch_id]["status"], "consumed")
        self.assertEqual(graph["entities"]["方拓"]["7_held_items"], {})

    def test_coin_quantity_is_stack(self):
        graph = {"entities": {"方拓": {"6_inventory": {"铜钱": {"quantity": 100, "unit": "枚"}}, "7_held_items": {}}}}
        ensure_item_instances(graph)
        coin = next(iter(graph["item_instances"].values()))
        self.assertEqual(coin["canonical_name"], "铜钱")
        self.assertEqual(coin["item_kind"], "stack")
        self.assertEqual(coin["quantity"], 100)
```

- [ ] **Step 2: 实现状态与消耗函数**

追加：

```python
def update_item_state_tags(graph: dict, instance_id: str, *, add_tags=None, remove_tags=None) -> dict:
    instance = graph.setdefault("item_instances", {}).get(instance_id)
    if not instance:
        return graph
    tags = list(instance.get("state_tags", []))
    for tag in remove_tags or []:
        if tag in tags:
            tags.remove(tag)
    for tag in add_tags or []:
        if tag not in tags:
            tags.append(tag)
    instance["state_tags"] = tags
    return graph


def mark_item_consumed(graph: dict, instance_id: str) -> dict:
    instance = graph.setdefault("item_instances", {}).get(instance_id)
    if not instance:
        return graph
    instance["status"] = "consumed"
    holder = instance.get("holder")
    if holder and holder in graph.get("entities", {}):
        entity = graph["entities"][holder]
        for slot in ("6_inventory", "7_held_items"):
            items = entity.get(slot, {})
            for key, data in list(items.items()):
                if isinstance(data, dict) and data.get("instance_id") == instance_id:
                    items.pop(key, None)
    return graph
```

- [ ] **Step 3: 运行测试**

Run:

```powershell
cd 'd:\game\AI' ; python -m unittest tests.test_item_instances -v
```

Expected: PASS。

---

### Task 5: 接入沙盒管线与同步脚本

**Files:**
- Modify: `d:\game\AI\sync_sandbox_to_main.py`
- Modify: `d:\game\AI\sandbox_intent_parser.py`
- Modify: `d:\game\AI\sandbox_integration.py`
- Modify: `d:\game\AI\sandbox_rules\complex_encounter.py`

- [ ] **Step 1: 修改同步脚本映射**

在 `FILE_MAPPING` 增加：

```python
"sandbox_item_instances.py": "item_instances.py",
```

在 `IMPORT_REPLACEMENTS` 增加：

```python
(r"from sandbox_item_instances", "from item_instances"),
(r"import sandbox_item_instances", "import item_instances"),
```

- [ ] **Step 2: 在意图解析入口迁移实例池**

在 `sandbox_intent_parser.py` 的 `parse_and_adjudicate_intent()` 中创建 `GraphRepository` 前或后加入：

```python
from sandbox_item_instances import ensure_item_instances

major_graph = ensure_item_instances(major_graph)
```

- [ ] **Step 3: 在复合动作 resolver 开头迁移实例池**

在 `sandbox_rules/complex_encounter.py` 的 `resolve()` 开头加入：

```python
from sandbox_item_instances import ensure_item_instances

major_graph = ensure_item_instances(major_graph)
```

- [ ] **Step 4: 在门铃同步补写实例池**

在 `sandbox_integration.py` 处理 `cat == "6_inventory"` 新增物品时，创建实例并同步兼容索引：

```python
from sandbox_item_instances import create_item_instance, sync_legacy_item_index

instance_id = create_item_instance(
    {"entities": {entity: entity_node}, "item_instances": major_graph.setdefault("item_instances", {})},
    name,
    {"tags": incoming_tags or ["通用"], "multiplier": safe_mult, "features": new_features or ["初始获得"], "persistence": "persistent"},
    holder=entity,
    container="inventory",
    location="背包",
    source="sync_dynamic_status",
)
```

如果此处局部变量拿不到 `major_graph`，则第一版只在 `sandbox_core_engine.sandbox_sync_dynamic_status()` 里接入，因为该函数持有完整 `major_graph`。

- [ ] **Step 5: 运行隔离扫描与同步 dry-run**

Run:

```powershell
cd 'd:\game\AI' ; python -c "import pathlib,re; files=list(pathlib.Path('.').glob('sandbox_*.py'))+list(pathlib.Path('sandbox_rules').glob('*.py')); bad=[]; pats=[r'from core_engine',r'import core_engine',r'from config import',r'import config',r'from rules\\.',r'import rules']; [bad.append((str(f),p)) for f in files for p in pats if re.search(p, f.read_text(encoding='utf-8'))]; print(bad if bad else 'SANDBOX ISOLATED')"
python sync_sandbox_to_main.py --dry-run
```

Expected: `SANDBOX ISOLATED`，dry-run 0 失败。

---

### Task 6: CLI 回归与文档更新

**Files:**
- Modify: `d:\game\AI\后台测试结果.md`
- Modify: `d:\game\AI\todolist.md`

- [ ] **Step 1: 运行单元测试**

Run:

```powershell
cd 'd:\game\AI' ; python -m unittest tests.test_item_instances -v
```

Expected: PASS。

- [ ] **Step 2: 运行完整流程 CLI**

Run:

```powershell
cd 'd:\game\AI' ; python cli_test_runner.py --preset full_pipeline
```

Expected: 意图解析、裁决、PRO 叙事均通过。

- [ ] **Step 3: 在 `后台测试结果.md` 追加测试记录**

记录：

```markdown
## 2026-06-01 | 全局物品实例池兼容版测试

- 单元测试：`python -m unittest tests.test_item_instances -v`
- CLI 测试：`python cli_test_runner.py --preset full_pipeline`
- 结论：item_instances 迁移、多火把消歧、旧字段兼容索引均通过。
```

- [ ] **Step 4: 更新 `todolist.md` 状态**

将 “物品名称 Canonical 归一” 状态从 `⏳ 待开始` 更新为 `🧪 单元测试通过`，并注明兼容版已落地。

---

## Self-Review

- Spec 覆盖：计划覆盖全局实例池、旧字段兼容索引、引用解析、多火把、堆叠、同步脚本和测试。
- 无占位符：每个任务给出明确文件、函数、测试命令和预期结果。
- 类型一致：核心字段统一为 `instance_id`、`canonical_name`、`item_kind`、`holder`、`container`、`state_tags`。
- 范围控制：第一阶段不删除旧字段、不重构 UI、不切换所有裁决读路径。
