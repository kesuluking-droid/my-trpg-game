# 沙盒完全隔离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让沙盒管线不再直接导入或调用原始管线函数，所有核心依赖均在沙盒侧拥有独立实现。

**Architecture:** 沙盒文件只依赖 `sandbox_*` 模块与第三方库；需要从原始 `core_engine.py` 借用的函数复制进 `sandbox_core_engine.py`，并在沙盒侧改名或保留同名供沙盒调用。同步到主版本时仍由 `sync_sandbox_to_main.py` 将 `sandbox_*` 导入转换为主版本导入。

**Tech Stack:** Python, Streamlit, OpenAI SDK, Supabase, 现有沙盒规则系统。

---

## 文件结构与责任

- 修改 `sandbox_core_engine.py`：新增/沙盒化 `get_user_client`、`generate_chat_stream`、`get_current_world_anchor_text`、`init_npc_combat_stats`、`sandbox_sync_dynamic_status`，删除对 `core_engine` 与 `rules` 的直接依赖。
- 修改 `sandbox_intent_parser.py`：把 `config` 和 `core_engine` 导入改成 `sandbox_config` 与 `sandbox_core_engine`。
- 修改 `sandbox_integration.py`：把 `config` 和 `core_engine.sync_dynamic_status/get_user_client` 改成沙盒版本。
- 修改 `sandbox_app.py`：把 `memory_manager` 和 `core_engine` 改成沙盒别名导入。
- 不修改 `core_engine.py`、`config.py`、`rules/` 原始管线文件。

---

### Task 1: 提取沙盒核心基础函数

**Files:**
- Modify: `d:\game\AI\sandbox_core_engine.py`

- [ ] **Step 1: 在 `sandbox_core_engine.py` 顶部导入沙盒配置与 OpenAI/Supabase 依赖**

目标导入形态：

```python
import os
import time
import json
import random
import re
import streamlit as st
from copy import deepcopy
from openai import OpenAI
from supabase import create_client, Client
from sandbox_config import MODEL_FLASH, MODEL_PRO, API_BASE_URL, DEBUG_MODE
import sandbox_config as config
```

- [ ] **Step 2: 新增沙盒版 `get_user_client`**

实现要求：保留单例缓存；只读取 `st.session_state["user_api_key"]`；不导入 `core_engine`。

- [ ] **Step 3: 新增沙盒版 `generate_chat_stream`**

实现要求：复制原始 PRO 流式生成逻辑；模型使用 `sandbox_config.MODEL_PRO`；客户端使用沙盒 `get_user_client`。

- [ ] **Step 4: 新增沙盒版 `get_current_world_anchor_text`**

实现要求：复制原始查询逻辑，但 Supabase 客户端来自沙盒配置；失败时返回安全兜底文本。

---

### Task 2: 沙盒化 NPC 初始化与缓存

**Files:**
- Modify: `d:\game\AI\sandbox_core_engine.py`

- [ ] **Step 1: 移除 `from core_engine import init_npc_combat_stats as _init_npc_combat_stats`**

- [ ] **Step 2: 将原始 `init_npc_combat_stats` 的 LLM 生成逻辑复制到沙盒函数内部**

实现要求：当前沙盒包装函数不得再调用 `_init_npc_combat_stats`；缓存未命中时直接在沙盒函数内调用 FLASH 生成 NPC 六维。

- [ ] **Step 3: 保留 NPC 缓存逻辑**

缓存键仍为 `NPC名称 + 标签 + 世界观前缀`；玩家实体不缓存。

---

### Task 3: 沙盒化动态状态同步

**Files:**
- Modify: `d:\game\AI\sandbox_core_engine.py`
- Modify: `d:\game\AI\sandbox_integration.py`

- [ ] **Step 1: 从 `core_engine.py::sync_dynamic_status` 复制函数到 `sandbox_core_engine.py`**

新函数名：

```python
def sandbox_sync_dynamic_status(rendered_text, target_name, major_graph, active_scene, active_stage_names=None, pc_name="主角", suppress_inventory_sync=False):
    ...
```

- [ ] **Step 2: 函数内部调用全部使用沙盒本地依赖**

包括 `get_user_client`、`MODEL_FLASH`、`json`、`re`，不得导入 `core_engine`。

- [ ] **Step 3: 替换 `sandbox_integration.py` 中两处 `from core_engine import sync_dynamic_status`**

替换为：

```python
from sandbox_core_engine import sandbox_sync_dynamic_status
```

调用名同步替换为 `sandbox_sync_dynamic_status(...)`。

---

### Task 4: 替换沙盒导入

**Files:**
- Modify: `d:\game\AI\sandbox_core_engine.py`
- Modify: `d:\game\AI\sandbox_intent_parser.py`
- Modify: `d:\game\AI\sandbox_integration.py`
- Modify: `d:\game\AI\sandbox_app.py`

- [ ] **Step 1: 替换 `sandbox_core_engine.py` 原始导入**

目标：

```python
from sandbox_rules.adjudication_utils import run_standard_adjudication
```

- [ ] **Step 2: 替换 `sandbox_intent_parser.py` 原始导入**

目标：

```python
from sandbox_config import MODEL_FLASH
from sandbox_core_engine import get_user_client
```

- [ ] **Step 3: 替换 `sandbox_integration.py` 原始导入**

目标：

```python
from sandbox_config import MODEL_FLASH
from sandbox_core_engine import get_user_client, sandbox_sync_dynamic_status
```

- [ ] **Step 4: 替换 `sandbox_app.py` 原始别名导入**

目标：

```python
import sandbox_memory_manager as memory_manager
import sandbox_core_engine as core_engine
```

---

### Task 5: 验证隔离与同步脚本

**Files:**
- No code changes expected

- [ ] **Step 1: 运行语法检查**

Run:

```powershell
cd 'd:\game\AI' ; python -c "import py_compile; [py_compile.compile(f, doraise=True) for f in ['sandbox_core_engine.py','sandbox_intent_parser.py','sandbox_integration.py','sandbox_app.py']] ; print('sandbox syntax OK')"
```

- [ ] **Step 2: 运行隔离扫描**

Run:

```powershell
cd 'd:\game\AI' ; python -c "import pathlib,re; files=list(pathlib.Path('.').glob('sandbox_*.py'))+list(pathlib.Path('sandbox_rules').glob('*.py')); bad=[]; pats=[r'from core_engine',r'import core_engine',r'from config import',r'import config',r'from rules\\.',r'import rules']; [bad.append((str(f),p)) for f in files for p in pats if re.search(p, f.read_text(encoding='utf-8'))]; print(bad if bad else 'SANDBOX ISOLATED')"
```

Expected: `SANDBOX ISOLATED`。

- [ ] **Step 3: 检查同步脚本 dry-run**

Run:

```powershell
cd 'd:\game\AI' ; python sync_sandbox_to_main.py --dry-run
```

Expected: 不报错；只显示预览，不写入主版本。

- [ ] **Step 4: 运行 CLI 回归测试**

Run:

```powershell
cd 'd:\game\AI' ; python cli_test_runner.py --preset full_pipeline
```

Expected: 意图解析、裁决、PRO 叙事均完成，无数值泄露。

---

## Self-Review

- 覆盖要求：计划覆盖了所有已发现的沙盒到原始管线依赖。
- 无占位符：每个任务都有明确文件、替换目标和测试命令。
- 同步脚本影响：方案保留 `sandbox_*` 命名，符合当前 `sync_sandbox_to_main.py` 的导入转换规则。
