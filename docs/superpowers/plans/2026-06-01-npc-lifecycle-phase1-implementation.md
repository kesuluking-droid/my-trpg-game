# NPC 生命周期第一阶段 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在沙盒管线中实现 NPC 初始化前的证据检索、身份解析 gate 与 pending reference 机制，防止代称、头衔、物品、组织被误初始化为长期 NPC。

**Architecture:** 新增 `sandbox_npc_lifecycle.py` 作为 NPC 身份生命周期工具层。Python 负责证据召回、identity 结构维护、结构化结果校验与落盘；LLM 仍负责开放世界语义判断。第一阶段用确定性测试桩覆盖核心行为，不引入完整 NPC 实例池、不改 graph key、不做 NPC 主动回合。

**Tech Stack:** Python, unittest, 现有沙盒管线 (`sandbox_*`), `sync_sandbox_to_main.py`。

---

## 文件结构与职责

- Create: `d:\game\AI\sandbox_npc_lifecycle.py`  
  NPC 证据检索、identity 初始化、alias 合并、pending reference、初始化 gate。
- Create: `d:\game\AI\tests\test_npc_lifecycle_identity.py`  
  覆盖神秘人、乔峰/萧峰、黑衣人/慕容复、师父、非角色、山贼初始化。
- Modify: `d:\game\AI\sync_sandbox_to_main.py`  
  增加 `sandbox_npc_lifecycle.py -> npc_lifecycle.py` 映射。
- Modify: `d:\game\AI\sandbox_core_engine.py`  
  在调用 `init_npc_combat_stats()` 前接入 `should_initialize_npc()`。
- Modify: `d:\game\AI\sandbox_intent_engine.py`  
  在意图解析 prompt 中加入 NPC 称呼与身份协议。

---

### Task 1: 新增 NPC lifecycle 基础模块与 identity 测试

**Files:**
- Create: `d:\game\AI\sandbox_npc_lifecycle.py`
- Create: `d:\game\AI\tests\test_npc_lifecycle_identity.py`

- [ ] **Step 1: 写基础测试**

创建 `tests/test_npc_lifecycle_identity.py`：

```python
# -*- coding: utf-8 -*-
import unittest

from sandbox_npc_lifecycle import ensure_npc_identity, merge_npc_alias


class NpcIdentityBasicTest(unittest.TestCase):
    def test_ensure_npc_identity_adds_identity_structure(self):
        graph = {"entities": {"乔峰": {"tags": ["NPC"], "desc": "丐帮帮主"}}}

        ensure_npc_identity(graph, "乔峰")

        identity = graph["entities"]["乔峰"]["identity"]
        self.assertTrue(identity["npc_id"].startswith("npc_乔峰_"))
        self.assertEqual(identity["primary_name"], "乔峰")
        self.assertEqual(identity["display_name"], "乔峰")
        self.assertEqual(identity["preferred_name"], "乔峰")
        self.assertEqual(identity["aliases"], [])

    def test_merge_alias_deduplicates_by_name_and_scope(self):
        graph = {"entities": {"乔峰": {"tags": ["NPC"]}}}
        ensure_npc_identity(graph, "乔峰")
        alias = {"name": "萧峰", "type": "origin_name", "scope": "global_alias", "confidence": 1.0}

        merge_npc_alias(graph, "乔峰", alias)
        merge_npc_alias(graph, "乔峰", alias)

        aliases = graph["entities"]["乔峰"]["identity"]["aliases"]
        self.assertEqual(len(aliases), 1)
        self.assertEqual(aliases[0]["name"], "萧峰")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 创建 `sandbox_npc_lifecycle.py` 最小实现**

```python
# -*- coding: utf-8 -*-
"""sandbox_npc_lifecycle.py — NPC 证据检索与身份生命周期工具层。"""

from __future__ import annotations

import re


def _safe_slug(text: str) -> str:
    raw = str(text or "npc").strip()
    raw = re.sub(r"\s+", "_", raw)
    raw = re.sub(r"[^\w\u4e00-\u9fff#-]", "", raw)
    return raw or "npc"


def _make_npc_id(graph_key: str, existing_entities: dict) -> str:
    base = f"npc_{_safe_slug(graph_key)}"
    used = {
        data.get("identity", {}).get("npc_id")
        for data in existing_entities.values()
        if isinstance(data, dict)
    }
    idx = 1
    while True:
        candidate = f"{base}_{idx:03d}"
        if candidate not in used:
            return candidate
        idx += 1


def ensure_npc_identity(graph: dict, graph_key: str) -> dict:
    entities = graph.setdefault("entities", {})
    node = entities.setdefault(graph_key, {})
    identity = node.setdefault("identity", {})
    identity.setdefault("npc_id", _make_npc_id(graph_key, entities))
    identity.setdefault("primary_name", graph_key)
    identity.setdefault("display_name", graph_key)
    identity.setdefault("preferred_name", graph_key)
    identity.setdefault("identity_status", "known")
    identity.setdefault("rename_policy", "do_not_auto_rename_primary_without_strong_story_event")
    identity.setdefault("aliases", [])
    identity.setdefault("pending_aliases", [])
    return graph


def merge_npc_alias(graph: dict, graph_key: str, alias_record: dict) -> dict:
    ensure_npc_identity(graph, graph_key)
    aliases = graph["entities"][graph_key]["identity"].setdefault("aliases", [])
    name = alias_record.get("name")
    scope = alias_record.get("scope", "global_alias")
    for alias in aliases:
        if alias.get("name") == name and alias.get("scope", "global_alias") == scope:
            alias.update(alias_record)
            return graph
    aliases.append(dict(alias_record))
    return graph
```

- [ ] **Step 3: 运行测试**

Run:

```powershell
cd 'd:\game\AI' ; python -m unittest tests.test_npc_lifecycle_identity -v
```

Expected: PASS。

---

### Task 2: 证据上下文与 pending reference

**Files:**
- Modify: `d:\game\AI\sandbox_npc_lifecycle.py`
- Modify: `d:\game\AI\tests\test_npc_lifecycle_identity.py`

- [ ] **Step 1: 写测试**

追加：

```python
from sandbox_npc_lifecycle import build_npc_evidence_context, create_pending_reference


class NpcEvidenceContextTest(unittest.TestCase):
    def test_evidence_context_finds_identity_reveal_sentence(self):
        graph = {"entities": {"慕容复": {"tags": ["NPC"], "desc": "姑苏慕容"}}}
        active_scene = [
            {"role": "assistant", "content": "一个戴铁面具的黑衣人出现在竹林中。"},
            {"role": "assistant", "content": "黑衣人摘下面罩，竟是慕容复。"},
        ]

        context = build_npc_evidence_context("黑衣人", graph, active_scene)

        self.assertEqual(context["surface_name"], "黑衣人")
        self.assertTrue(any("慕容复" in hit["text"] for hit in context["candidate_mentions"]))
        self.assertTrue(any(hit["evidence_type"] == "identity_reveal" for hit in context["candidate_mentions"]))

    def test_create_pending_reference_does_not_create_entity(self):
        graph = {"entities": {}}
        create_pending_reference(graph, "神秘人", "有人提到了神秘人", "缺少身份解析证据")

        self.assertNotIn("神秘人", graph["entities"])
        self.assertEqual(graph["pending_references"][0]["surface_name"], "神秘人")
        self.assertFalse(graph["pending_references"][0]["should_initialize_npc"])
```

- [ ] **Step 2: 实现证据检索与 pending**

追加：

```python
IDENTITY_REVEAL_MARKERS = ["其实是", "原来是", "正是", "竟是", "本名", "真名", "化名", "摘下面罩"]


def _score_evidence(surface_name: str, text: str, source: str, recent_bonus: int = 0) -> tuple[int, str]:
    score = 0
    evidence_type = "mention"
    if surface_name and surface_name in text:
        score += 5
    if any(marker in text for marker in IDENTITY_REVEAL_MARKERS):
        score += 10
        evidence_type = "identity_reveal"
    if any(word in text for word in ["黑衣", "蒙面", "斗笠", "铁面具", "口音"]):
        score += 3
        if evidence_type == "mention":
            evidence_type = "appearance_hint"
    if source == "active_scene":
        score += recent_bonus
    if source == "history_archive":
        score += 1
    return score, evidence_type


def build_npc_evidence_context(surface_name: str, major_graph: dict, active_scene: list, history_archive=None, gm_memory=None) -> dict:
    candidate_mentions = []
    for idx, msg in enumerate(active_scene or []):
        text = str(msg.get("content", ""))
        score, evidence_type = _score_evidence(surface_name, text, "active_scene", recent_bonus=3 if idx >= max(0, len(active_scene) - 5) else 0)
        if score > 0:
            candidate_mentions.append({"source": "active_scene", "score": score, "text": text, "evidence_type": evidence_type})
    for item in history_archive or []:
        text = str(item.get("content", item) if isinstance(item, dict) else item)
        score, evidence_type = _score_evidence(surface_name, text, "history_archive")
        if score > 0:
            candidate_mentions.append({"source": "history_archive", "score": score, "text": text, "evidence_type": evidence_type})
    known_alias_hits = []
    for graph_key, node in major_graph.get("entities", {}).items():
        identity = node.get("identity", {}) if isinstance(node, dict) else {}
        for alias in identity.get("aliases", []):
            if alias.get("name") == surface_name:
                known_alias_hits.append({"graph_key": graph_key, "alias": surface_name, "scope": alias.get("scope", "global_alias"), "confidence": alias.get("confidence", 1.0)})
    candidate_mentions.sort(key=lambda x: x["score"], reverse=True)
    return {"surface_name": surface_name, "candidate_mentions": candidate_mentions[:8], "known_alias_hits": known_alias_hits}


def create_pending_reference(graph: dict, surface_name: str, evidence: str, reason: str) -> dict:
    pending = graph.setdefault("pending_references", [])
    record = {"surface_name": surface_name, "referent_type": "character", "status": "unresolved", "evidence": evidence, "reason": reason, "should_initialize_npc": False}
    pending.append(record)
    return graph
```

- [ ] **Step 3: 运行测试**

Run:

```powershell
cd 'd:\game\AI' ; python -m unittest tests.test_npc_lifecycle_identity -v
```

Expected: PASS。

---

### Task 3: 身份解析 gate 的确定性第一版

**Files:**
- Modify: `d:\game\AI\sandbox_npc_lifecycle.py`
- Modify: `d:\game\AI\tests\test_npc_lifecycle_identity.py`

- [ ] **Step 1: 写测试**

追加：

```python
from sandbox_npc_lifecycle import resolve_npc_reference, should_initialize_npc


class NpcResolutionGateTest(unittest.TestCase):
    def test_alias_hit_resolves_to_existing_npc(self):
        graph = {"entities": {"伏地魔": {"tags": ["NPC"]}}}
        ensure_npc_identity(graph, "伏地魔")
        merge_npc_alias(graph, "伏地魔", {"name": "神秘人", "type": "taboo_alias", "scope": "global_alias", "confidence": 0.95})
        context = build_npc_evidence_context("神秘人", graph, [{"role": "user", "content": "神秘人要来了。"}])

        resolution = resolve_npc_reference("神秘人", context, graph)

        self.assertEqual(resolution["status"], "resolved")
        self.assertEqual(resolution["target_graph_key"], "伏地魔")
        self.assertFalse(should_initialize_npc("神秘人", {"entity_type": "character", "should_initialize_npc": True}, resolution)["allowed"])

    def test_unknown_taboo_reference_goes_pending(self):
        graph = {"entities": {}}
        context = build_npc_evidence_context("神秘人", graph, [{"role": "user", "content": "神秘人要来了。"}])
        resolution = resolve_npc_reference("神秘人", context, graph)

        self.assertEqual(resolution["status"], "pending")
        self.assertFalse(should_initialize_npc("神秘人", {"entity_type": "character", "should_initialize_npc": True}, resolution)["allowed"])

    def test_non_character_annotation_rejected(self):
        resolution = {"status": "new_npc_allowed", "canonical_graph_key": "墙上的火把"}
        decision = should_initialize_npc("墙上的火把", {"entity_type": "object", "should_initialize_npc": True}, resolution)

        self.assertFalse(decision["allowed"])
```

- [ ] **Step 2: 实现解析 gate**

追加：

```python
def resolve_npc_reference(surface_name: str, evidence_context: dict, major_graph: dict) -> dict:
    # 第一阶段确定性版本：优先用已解析 aliases 和强身份揭示句。后续可替换为 LLM 结构化解析。
    for hit in evidence_context.get("known_alias_hits", []):
        return {"status": "resolved", "target_graph_key": hit["graph_key"], "alias_scope": hit.get("scope", "global_alias"), "confidence": hit.get("confidence", 1.0), "reason": "命中已有 NPC alias"}
    for mention in evidence_context.get("candidate_mentions", []):
        if mention.get("evidence_type") == "identity_reveal":
            text = mention.get("text", "")
            for graph_key in major_graph.get("entities", {}).keys():
                if graph_key in text and graph_key != surface_name:
                    return {"status": "resolved", "target_graph_key": graph_key, "alias_scope": "scene_bound", "confidence": 0.9, "reason": "证据句段揭示表面称呼指向已有 NPC", "evidence": text}
    if evidence_context.get("candidate_mentions"):
        return {"status": "pending", "surface_name": surface_name, "should_initialize_npc": False, "reason": "有提及但无充分身份解析证据"}
    return {"status": "new_npc_allowed", "canonical_graph_key": surface_name, "reason": "无已有别名或待解析证据，允许后续结合 annotation 判断是否新建"}


def should_initialize_npc(surface_name: str, annotation: dict, resolution: dict) -> dict:
    if resolution.get("status") in {"resolved", "pending", "non_character"}:
        return {"allowed": False, "reason": f"resolution={resolution.get('status')} 不应初始化新 NPC"}
    if annotation.get("entity_type") != "character":
        return {"allowed": False, "reason": "非角色实体不得初始化 NPC"}
    if not annotation.get("should_initialize_npc", False):
        return {"allowed": False, "reason": "LLM annotation 未授权初始化"}
    return {"allowed": True, "graph_key": resolution.get("canonical_graph_key") or surface_name, "reason": "角色实体且通过初始化 gate"}
```

- [ ] **Step 3: 运行测试**

Run:

```powershell
cd 'd:\game\AI' ; python -m unittest tests.test_npc_lifecycle_identity -v
```

Expected: PASS。

---

### Task 4: 乔峰/萧峰与黑衣人/慕容复专项测试

**Files:**
- Modify: `d:\game\AI\tests\test_npc_lifecycle_identity.py`

- [ ] **Step 1: 追加专项测试**

```python
class NpcAliasScenarioTest(unittest.TestCase):
    def test_xiao_feng_alias_does_not_rename_graph_key(self):
        graph = {"entities": {"乔峰": {"tags": ["NPC"]}}}
        ensure_npc_identity(graph, "乔峰")
        merge_npc_alias(graph, "乔峰", {"name": "萧峰", "type": "origin_name", "scope": "global_alias", "confidence": 1.0})
        context = build_npc_evidence_context("萧峰", graph, [{"role": "assistant", "content": "萧峰大步走入酒楼。"}])

        resolution = resolve_npc_reference("萧峰", context, graph)

        self.assertEqual(resolution["status"], "resolved")
        self.assertEqual(resolution["target_graph_key"], "乔峰")
        self.assertIn("乔峰", graph["entities"])
        self.assertNotIn("萧峰", graph["entities"])

    def test_black_clad_reveal_is_scene_bound(self):
        graph = {"entities": {"慕容复": {"tags": ["NPC"]}}}
        ensure_npc_identity(graph, "慕容复")
        context = build_npc_evidence_context("黑衣人", graph, [
            {"role": "assistant", "content": "黑衣人摘下面罩，竟是慕容复。"}
        ])

        resolution = resolve_npc_reference("黑衣人", context, graph)
        if resolution["status"] == "resolved":
            merge_npc_alias(graph, resolution["target_graph_key"], {"name": "黑衣人", "type": "disguise_alias", "scope": "scene_bound", "confidence": resolution.get("confidence", 0.9)})

        aliases = graph["entities"]["慕容复"]["identity"]["aliases"]
        self.assertTrue(any(a["name"] == "黑衣人" and a["scope"] == "scene_bound" for a in aliases))

    def test_another_black_clad_does_not_resolve_without_matching_evidence(self):
        graph = {"entities": {"慕容复": {"tags": ["NPC"]}}}
        ensure_npc_identity(graph, "慕容复")
        merge_npc_alias(graph, "慕容复", {"name": "黑衣人", "type": "disguise_alias", "scope": "scene_bound", "confidence": 0.9})
        context = {"surface_name": "另一个黑衣人", "candidate_mentions": [{"source": "active_scene", "score": 5, "text": "另一个黑衣人从屋顶跃下。", "evidence_type": "mention"}], "known_alias_hits": []}

        resolution = resolve_npc_reference("另一个黑衣人", context, graph)

        self.assertEqual(resolution["status"], "pending")
```

- [ ] **Step 2: 运行测试**

Run:

```powershell
cd 'd:\game\AI' ; python -m unittest tests.test_npc_lifecycle_identity -v
```

Expected: PASS。

---

### Task 5: 接入沙盒初始化 gate 与 prompt 协议

**Files:**
- Modify: `d:\game\AI\sandbox_core_engine.py`
- Modify: `d:\game\AI\sandbox_intent_engine.py`
- Modify: `d:\game\AI\sync_sandbox_to_main.py`

- [ ] **Step 1: 同步脚本增加映射**

在 `sync_sandbox_to_main.py` 中增加：

```python
"sandbox_npc_lifecycle.py": "npc_lifecycle.py",
```

以及：

```python
(r"from sandbox_npc_lifecycle", "from npc_lifecycle"),
(r"import sandbox_npc_lifecycle", "import npc_lifecycle"),
```

- [ ] **Step 2: 在 `sandbox_core_engine.py` 的 NPC 初始化前接入 gate**

在处理 `entity_annotations` 调用 `init_npc_combat_stats()` 前加入：

```python
from sandbox_npc_lifecycle import build_npc_evidence_context, resolve_npc_reference, should_initialize_npc, create_pending_reference

evidence = build_npc_evidence_context(name, working_graph, active_scene)
resolution = resolve_npc_reference(name, evidence, working_graph)
decision = should_initialize_npc(name, ann, resolution)
if not decision.get("allowed"):
    if resolution.get("status") == "pending":
        create_pending_reference(working_graph, name, evidence.get("candidate_mentions", [{}])[0].get("text", ""), decision.get("reason", "未通过 NPC 初始化 gate"))
    continue
name = decision.get("graph_key", name)
```

- [ ] **Step 3: 在 Prompt 模板加入 NPC 称呼与身份协议**

在 `sandbox_intent_engine.py` 的 `_INTENT_PARSE_SYSTEM_TEMPLATE` 中加入：

```text
【NPC称呼与身份协议】代称、尊称、蔑称、头衔、关系称呼或外号（如“神秘人”“那个不能说名字的人”“乔帮主”“萧大王”“师父”“黑衣人”）不是长期NPC规范名。若能从前情确定真实指向，canonical_name 填已知人物当前主显示名，并在 reason 说明 alias/title/taboo name；若无法确定，should_initialize_npc=false 并说明 unresolved_reference。人物曾用名、真名、尊称、蔑称、身份称号不等于必须改名；除非叙事明确说明角色从此改用新名，否则保持原 primary/display name，将其他称呼记录为 aliases。“黑衣人”“蒙面人”“白衣女子”等局部称呼默认是 scene_bound/specific_instance，不得自动作为 global_alias。
```

---

### Task 6: 验证与记录

**Files:**
- Modify: `d:\game\AI\后台测试结果.md`
- Modify: `d:\game\AI\todolist.md`

- [ ] **Step 1: 单元测试**

Run:

```powershell
cd 'd:\game\AI' ; python -m unittest tests.test_npc_lifecycle_identity -v
```

Expected: PASS。

- [ ] **Step 2: 语法与隔离扫描**

Run:

```powershell
cd 'd:\game\AI' ; python -c "import py_compile; files=['sandbox_npc_lifecycle.py','sandbox_core_engine.py','sandbox_intent_engine.py','sync_sandbox_to_main.py']; [py_compile.compile(f, doraise=True) for f in files]; print('npc lifecycle syntax OK')"
python -c "import pathlib,re; files=list(pathlib.Path('.').glob('sandbox_*.py'))+list(pathlib.Path('sandbox_rules').glob('*.py')); bad=[]; pats=[r'from core_engine',r'import core_engine',r'from config import',r'import config',r'from rules\\.',r'import rules']; [bad.append((str(f),p)) for f in files for p in pats if re.search(p, f.read_text(encoding='utf-8'))]; print(bad if bad else 'SANDBOX ISOLATED')"
python sync_sandbox_to_main.py --dry-run
```

Expected: syntax OK, `SANDBOX ISOLATED`, dry-run 0 失败。

- [ ] **Step 3: CLI 回归**

Run:

```powershell
cd 'd:\game\AI' ; python cli_test_runner.py --preset full_pipeline
```

Expected: 意图解析、裁决、PRO 叙事均通过。

- [ ] **Step 4: 记录结果**

在 `后台测试结果.md` 追加：

```markdown
## 2026-06-01 | NPC 生命周期第一阶段测试

- 单元测试：`python -m unittest tests.test_npc_lifecycle_identity -v`
- 隔离扫描：`SANDBOX ISOLATED`
- 同步预览：0 失败
- CLI 回归：通过
- 结论：NPC 初始化前证据检索、身份解析 gate、pending reference 第一阶段可用。
```

在 `todolist.md` 添加或更新 NPC 生成与更新相关条目状态为 `🧪 单元测试通过`。

---

## Self-Review

- 覆盖范围：第一阶段只做初始化 gate、identity、alias、pending，不做完整更新 patch 或 NPC 主动回合。
- 核心哲学：LLM 负责语义判断；Python 负责证据召回、结构化校验、落盘边界。
- 反黑白名单：中文词表示例只用于 prompt 和测试，实际 gate 依赖结构化 annotation/resolution。
- 沙盒隔离：新增模块使用 `sandbox_` 命名，并通过同步脚本映射。
