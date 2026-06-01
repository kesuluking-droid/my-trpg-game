# 沙盒版本镜像化 - 迁移状态报告

> 最后更新：2026-06-01

---

## 已完成文件

### 根目录文件

| 文件 | 状态 | 说明 |
|------|------|------|
| `sandbox_turn_engine.py` | ✅ 已创建 | 回合总控引擎（完整1:1镜像） |
| `sandbox_intent_engine.py` | ✅ 已创建 | 意图解析引擎（完整1:1镜像） |
| `sandbox_turn_runtime.py` | ✅ 已创建 | 回合运行时（简化版核心功能） |
| `sandbox_config.py` | ✅ 已创建 | 配置（完整1:1镜像） |
| `sandbox_app.py` | ✅ 已存在 | Streamlit UI |
| `sandbox_core_engine.py` | ✅ 已存在 | 核心服务层 |

### rules 目录文件

| 文件 | 状态 | 说明 |
|------|------|------|
| `sandbox_rules/__init__.py` | ✅ 已创建 | 包初始化 |
| `sandbox_rules/factory.py` | ✅ 已创建 | 规则工厂（完整1:1镜像） |
| `sandbox_rules/base_adjudicator.py` | ✅ 已创建 | 基类（完整1:1镜像） |
| `sandbox_rules/adjudication_utils.py` | ✅ 已创建 | 检定工具（完整1:1镜像） |

---

## 待创建文件

### 根目录文件

| 源文件 | 目标文件 | 优先级 | 状态 |
|--------|----------|--------|------|
| `memory_manager.py` | `sandbox_memory_manager.py` | 🟡 中 | ⏳ 待创建 |
| `ability_matcher.py` | `sandbox_ability_matcher.py` | 🟡 中 | ⏳ 待创建 |

### rules 目录文件

| 源文件 | 目标文件 | 优先级 | 状态 |
|--------|----------|--------|------|
| `rules/complex_encounter.py` | `sandbox_rules/complex_encounter.py` | 🔴 高 | ⏳ 待创建 |
| `rules/atomic_adjudicator.py` | `sandbox_rules/atomic_adjudicator.py` | 🔴 高 | ⏳ 待创建 |
| `rules/classic_combat.py` | `sandbox_rules/classic_combat.py` | 🟡 中 | ⏳ 待创建 |
| `rules/skill_check.py` | `sandbox_rules/skill_check.py` | 🟡 中 | ⏳ 待创建 |
| `rules/social_check.py` | `sandbox_rules/social_check.py` | 🟡 中 | ⏳ 待创建 |
| `rules/stealth_check.py` | `sandbox_rules/stealth_check.py` | 🟡 中 | ⏳ 待创建 |

---

## 已完成的修改清单

### 1. 导入路径修改

所有已创建的 `sandbox_*.py` 文件中的导入已从：
```python
from config import MODEL_FLASH
from core_engine import get_user_client
from intent_engine import parse_and_adjudicate_intent
from rules.adjudication_utils import run_standard_adjudication
```

改为：
```python
from sandbox_config import MODEL_FLASH
from sandbox_core_engine import get_user_client
from sandbox_intent_engine import parse_and_adjudicate_intent
from sandbox_rules.adjudication_utils import run_standard_adjudication
```

### 2. 文件头模板

所有已创建的文件都包含：
```python
"""
sandbox_xxx.py — 功能描述

================================================================================
🔔 AI 助手维护提醒（每次修改前必读）
================================================================================

【沙盒版本绝对隔离原则】
- 本文件是 xxx.py 的 1:1 沙盒镜像副本
- 所有导入必须指向 sandbox_ 前缀版本
- 禁止直接调用主版本（xxx.py 等）
- 沙盒修改不得污染主版本管线

【修改步骤】
1. 如需修改功能，先在此沙盒版本测试验证
2. 验证通过后，将修改实质迁移到主版本
3. 不要简单让主版本跳转到沙盒版本

【文件对应关系】
- sandbox_xxx.py ↔ xxx.py

================================================================================
"""
```

---

## 下一步行动

由于上下文长度限制，剩余文件需要分批创建。建议：

1. **高优先级（立即）**：
   - `sandbox_rules/complex_encounter.py` - 复杂对抗核心
   - `sandbox_rules/atomic_adjudicator.py` - 原子裁判器

2. **中优先级（后续）**：
   - `sandbox_memory_manager.py`
   - `sandbox_ability_matcher.py`
   - `sandbox_rules/classic_combat.py`
   - `sandbox_rules/skill_check.py`
   - `sandbox_rules/social_check.py`
   - `sandbox_rules/stealth_check.py`

---

## 设计原则.md 已创建

✅ `设计原则.md` 已放在根目录，包含：
- 核心设计哲学（5条）
- 开发工作流
- 代码规范
- 架构分层
- 关键术语

---

## 测试验证

已创建的文件可以通过以下命令验证语法：

```bash
# 验证单个文件
python -m py_compile sandbox_turn_engine.py
python -m py_compile sandbox_intent_engine.py
python -m py_compile sandbox_turn_runtime.py
python -m py_compile sandbox_config.py

# 验证 rules 目录
python -m py_compile sandbox_rules/__init__.py
python -m py_compile sandbox_rules/factory.py
python -m py_compile sandbox_rules/base_adjudicator.py
python -m py_compile sandbox_rules/adjudication_utils.py
```

---

*本文件用于跟踪沙盒版本镜像化的进度。*
