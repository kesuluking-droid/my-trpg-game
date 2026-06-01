# 后悔药反向增量 Patch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this urgent storage fix task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将后悔药从全量 session 快照改为反向增量 patch，避免云存档随回合数快速膨胀。

**Architecture:** 新增 `sandbox_undo_manager.py` 负责捕获可撤回状态、生成反向 patch、应用 patch 与兼容旧快照。`sandbox_app.py` 保留原 UI 按钮，但 `save_undo_snapshot()` 变为捕获 before，新增 `commit_undo_snapshot()` 在回合成功后写入 patch；`undo_last_turn()` 同时支持新 patch 与旧全量快照。

**Tech Stack:** Python, unittest, Streamlit session_state, JSON-compatible patch objects.

---

## 文件职责

- Create: `d:\game\AI\sandbox_undo_manager.py` — diff、patch、restore、size 估算。
- Create: `d:\game\AI\tests\test_undo_manager.py` — 验证 patch 可逆与体积优势。
- Modify: `d:\game\AI\sandbox_app.py` — 接入 capture/commit/apply，保留旧 snapshot 兼容。
- Modify: `d:\game\AI\sync_sandbox_to_main.py` — 增加 `sandbox_undo_manager.py -> undo_manager.py` 映射。

---

## Task 1: undo manager 与可逆 patch 测试

- [ ] 写 `tests/test_undo_manager.py`，覆盖 dict 修改、新增 key、删除 key、list set、legacy restore、patch size。
- [ ] 创建 `sandbox_undo_manager.py`，实现 `capture_undo_state()`、`build_inverse_patch()`、`apply_inverse_patch()`、`restore_legacy_snapshot()`、`estimate_undo_size()`。
- [ ] 运行 `python -m unittest tests.test_undo_manager -v`，预期 PASS。

## Task 2: sandbox_app 接入

- [ ] `save_undo_snapshot()` 改为只保存 `_undo_before_state`。
- [ ] 新增 `commit_undo_snapshot()`，在回合成功后生成 patch 并写入 undo_stack。
- [ ] `undo_last_turn()` 支持 `version=2,type=inverse_patch` 与 legacy snapshot。
- [ ] 在 AI 回复/状态提交成功后调用 `commit_undo_snapshot()`。

## Task 3: 映射与验证

- [ ] `sync_sandbox_to_main.py` 增加模块映射和导入转换。
- [ ] 运行单元测试、语法检查、隔离扫描、同步 dry-run。
- [ ] 更新 `后台测试结果.md`。

---

## 成功标准

- undo_stack 新写入条目为 `{version:2,type:"inverse_patch",patches:[...]}`。
- 旧全量 snapshot 仍能撤回。
- 单元测试证明 patch 能把 after 恢复成 before。
- patch 大小小于 full snapshot。
- 不改变 UI 按钮交互。
