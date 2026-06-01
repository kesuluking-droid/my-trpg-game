# -*- coding: utf-8 -*-
"""sandbox_item_instances.py — 沙盒全局物品实例池工具层。"""

from __future__ import annotations

import re
from copy import deepcopy


def _safe_slug(text: str) -> str:
    """生成可读且稳定的实例 ID 片段。"""
    raw = str(text or "item").strip()
    raw = re.sub(r"\s+", "_", raw)
    raw = re.sub(r"[^\w\u4e00-\u9fff#-]", "", raw)
    return raw or "item"


def _make_instance_id(canonical_name: str, holder: str | None, container: str, existing: dict) -> str:
    """根据物品类型、持有者、容器生成唯一实例 ID。"""
    base = f"item_{_safe_slug(canonical_name)}_{_safe_slug(holder or 'env')}_{_safe_slug(container)}"
    idx = 1
    while True:
        candidate = f"{base}_{idx:03d}"
        if candidate not in existing:
            return candidate
        idx += 1


def _default_item_kind(name: str, item_data: dict) -> str:
    """区分实例型物品和堆叠型物品。"""
    quantity = item_data.get("quantity", 1)
    stack_words = ["铜钱", "银两", "箭", "粮", "米", "水", "石子", "草药"]
    if isinstance(quantity, (int, float)) and quantity > 1:
        if any(word in str(name) for word in stack_words):
            return "stack"
    return "instance"


def ensure_item_instances(graph: dict) -> dict:
    """迁移旧 6_inventory / 7_held_items 到 item_instances，并写回 instance_id。"""
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
                        "state_tags": deepcopy(item_data.get("state_tags", [])),
                        "tags": deepcopy(item_data.get("tags", item_data.get("target_domains", ["通用"]))),
                        "quantity": item_data.get("quantity", 1),
                        "unit": item_data.get("unit"),
                        "multiplier": item_data.get("multiplier", 1.0),
                        "persistence": item_data.get("persistence", "persistent"),
                        "created_from": "legacy_migration",
                        "status": "active",
                    }
    return graph


def create_item_instance(graph: dict, canonical_name: str, item_data: dict, *, holder=None, container="environment", location=None, source=None) -> str:
    """创建新物品实例并返回 instance_id。"""
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
    """移动物品实例。"""
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
    """为兼容索引生成稳定 key。"""
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
    """把实例同步到 6_inventory 或 7_held_items 兼容索引。"""
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


def _candidate_score(raw_name: str, instance: dict, pc_name: str, action_context: dict) -> int:
    """根据自然语言线索为候选实例打分。"""
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
    """将自然语言物品引用解析到 instance_id。"""
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


def update_item_state_tags(graph: dict, instance_id: str, *, add_tags=None, remove_tags=None) -> dict:
    """更新物品状态标签，不创建新实例。"""
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
    """标记物品已消耗，并从兼容索引移除。"""
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


def cleanup_ephemeral_items(graph: dict) -> dict:
    """清理已失效的临时物品。"""
    instances = graph.setdefault("item_instances", {})
    for instance_id, instance in list(instances.items()):
        if instance.get("persistence") == "ephemeral" and instance.get("status") != "active":
            instances.pop(instance_id, None)
    return graph
