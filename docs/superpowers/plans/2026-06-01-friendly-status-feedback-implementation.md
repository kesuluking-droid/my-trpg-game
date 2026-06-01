# 友好等待提示栏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this small UI feedback improvement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在玩家等待 LLM 与后台流程时显示通俗、贴合游戏语气的状态提示，降低焦虑感，并减少灰色系统提示的突兀感。

**Architecture:** 新增 `sandbox_ui_feedback.py` 统一维护阶段文案。`sandbox_core_engine.execute_sandbox_turn()` 接受可选 `status_callback(stage)`。`sandbox_app.py` 创建 `st.empty()` 提醒栏，通过回调更新文案，回合结束后清空。

**Tech Stack:** Python, unittest, Streamlit UI, existing sandbox pipeline.

---

## Tasks

1. 新增 `sandbox_ui_feedback.py` 与 `tests/test_ui_feedback.py`，测试阶段文案和未知阶段兜底。
2. 给 `sandbox_core_engine.execute_sandbox_turn()` 加 `status_callback=None`，在意图理解、人物确认、命运判定、叙事生成、世界线整理等阶段调用。
3. 在 `sandbox_app.py` 的常规回合创建 `status_box = st.empty()`，传入回调并在完成/异常时清空。
4. 更新 `sync_sandbox_to_main.py` 映射。
5. 运行测试、语法检查、隔离扫描、同步 dry-run，记录结果。
