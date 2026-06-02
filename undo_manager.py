# -*- coding: utf-8 -*-
"""undo_manager.py — 后悔药反向增量 patch 管理器。"""

from __future__ import annotations

import copy
import json


UNDO_TRACKED_KEYS = [
    "history_archive",
    "active_scene",
    "memory",
    "minor_npcs",
    "major_graph",
    "graveyard",
    "director_directive",
    "scene_index",
    "tension_history",
    "current_location",
    "mechanics_log",
    "sync_log",
    "ai_suggestions",
]


def _get_state_value(session_state, key):
    if hasattr(session_state, "get"):
        return session_state.get(key)
    return getattr(session_state, key, None)


def _set_state_value(session_state, key, value):
    try:
        session_state[key] = value
    except Exception:
        setattr(session_state, key, value)


def capture_undo_state(session_state) -> dict:
    """捕获可撤回字段的 JSON-compatible 深拷贝。"""
    return {key: copy.deepcopy(_get_state_value(session_state, key)) for key in UNDO_TRACKED_KEYS}


def _json_clone(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def _diff_inverse(before, after, path, patches):
    if before == after:
        return
    if isinstance(before, dict) and isinstance(after, dict):
        before_keys = set(before.keys())
        after_keys = set(after.keys())
        for key in sorted(after_keys - before_keys, key=str):
            patches.append({"op": "delete", "path": path + [key]})
        for key in sorted(before_keys - after_keys, key=str):
            patches.append({"op": "set", "path": path + [key], "value": _json_clone(before[key])})
        for key in sorted(before_keys & after_keys, key=str):
            _diff_inverse(before[key], after[key], path + [key], patches)
        return
    # 第一阶段 list 或 scalar 直接整段 set 回 before，安全优先。
    patches.append({"op": "set", "path": path, "value": _json_clone(before)})


def build_inverse_patch(before: dict, after: dict, label: str = "后悔药") -> dict:
    """根据 before/after 生成撤回用反向 patch。"""
    patches = []
    _diff_inverse(before or {}, after or {}, [], patches)
    return {"version": 2, "type": "inverse_patch", "label": label, "patches": patches}


def is_patch_undo(entry: dict) -> bool:
    return isinstance(entry, dict) and entry.get("version") == 2 and entry.get("type") == "inverse_patch"


def _delete_path(root, path):
    if not path:
        return
    cur = root
    for part in path[:-1]:
        cur = cur[part]
    if isinstance(cur, dict):
        cur.pop(path[-1], None)
    elif isinstance(cur, list) and isinstance(path[-1], int) and 0 <= path[-1] < len(cur):
        cur.pop(path[-1])


def _set_path(root, path, value):
    if not path:
        if isinstance(root, dict) and isinstance(value, dict):
            root.clear()
            root.update(value)
        return
    cur = root
    for part in path[:-1]:
        if isinstance(cur, dict):
            cur = cur.setdefault(part, {})
        else:
            cur = cur[part]
    if isinstance(cur, dict):
        cur[path[-1]] = copy.deepcopy(value)
    else:
        cur[path[-1]] = copy.deepcopy(value)


def apply_inverse_patch_to_state(state: dict, undo_entry: dict) -> dict:
    """对普通 dict 状态应用反向 patch，便于测试和 UI 复用。"""
    for patch in undo_entry.get("patches", []):
        op = patch.get("op")
        path = patch.get("path", [])
        if op == "delete":
            _delete_path(state, path)
        elif op == "set":
            _set_path(state, path, patch.get("value"))
    return state


def apply_inverse_patch(session_state, undo_entry: dict) -> None:
    """将反向 patch 应用于 Streamlit session_state。"""
    current = capture_undo_state(session_state)
    restored = apply_inverse_patch_to_state(current, undo_entry)
    for key in UNDO_TRACKED_KEYS:
        _set_state_value(session_state, key, restored.get(key))


def restore_legacy_snapshot(session_state, snapshot: dict) -> None:
    """兼容旧全量快照。"""
    for key in UNDO_TRACKED_KEYS:
        if key in snapshot:
            _set_state_value(session_state, key, copy.deepcopy(snapshot[key]))


def estimate_undo_size(obj) -> int:
    """估算 JSON 存储体积。"""
    return len(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))
