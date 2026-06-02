# -*- coding: utf-8 -*-
"""ui_feedback.py — 沙盒 UI 友好等待提示文案。"""

FRIENDLY_STATUS_TEXT = {
    "turn_start": "🕯️ 正在点亮这一幕的舞台...",
    "intent_parse": "🕯️ 正在揣摩你的行动意图...",
    "npc_check": "👥 正在确认登场人物的命运线...",
    "adjudication": "⚖️ 正在掷出命运的骰子...",
    "narration": "📖 正在书写这一幕的结果...",
    "sync_state": "🧭 正在整理世界线的变化...",
    "memory": "🪶 正在把这一幕收入记忆...",
    "undo_commit": "💊 正在封存这一刻的后悔药...",
    "transition": "🌙 正在翻开下一幕...",
    "done": "✨ 命运的回声已经落定。",
}


def get_friendly_status_text(stage: str) -> str:
    """把内部阶段名翻译成玩家可见的等待提示。"""
    return FRIENDLY_STATUS_TEXT.get(stage, "✨ 正在整理命运的线索...")


def safe_status(status_callback, stage: str) -> None:
    """安全调用状态回调，避免 UI 提示影响主流程。"""
    if not status_callback:
        return
    try:
        status_callback(stage)
    except Exception:
        return
