# -*- coding: utf-8 -*-
"""npc_lifecycle.py — NPC 证据检索与身份生命周期工具层。"""

from __future__ import annotations

import re


IDENTITY_REVEAL_MARKERS = ["其实是", "原来是", "正是", "竟是", "本名", "真名", "化名", "摘下面罩"]
UNRESOLVED_REFERENCE_HINTS = ["神秘", "那个", "那人", "黑衣", "蒙面", "白衣", "师父", "帮主", "方丈", "皇帝"]


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
    """确保已有 NPC 节点拥有 identity 子结构。"""
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
    """给已有 NPC 合并 alias，避免重复对象。"""
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


def _score_evidence(surface_name: str, text: str, source: str, recent_bonus: int = 0) -> tuple[int, str]:
    """给身份相关证据句段打分。"""
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
    """为表面称呼构造证据上下文。"""
    candidate_mentions = []
    active_scene = active_scene or []
    for idx, msg in enumerate(active_scene):
        text = str(msg.get("content", ""))
        score, evidence_type = _score_evidence(
            surface_name,
            text,
            "active_scene",
            recent_bonus=3 if idx >= max(0, len(active_scene) - 5) else 0,
        )
        if score > 0:
            candidate_mentions.append({"source": "active_scene", "score": score, "text": text, "evidence_type": evidence_type})

    for item in history_archive or []:
        text = str(item.get("content", item) if isinstance(item, dict) else item)
        score, evidence_type = _score_evidence(surface_name, text, "history_archive")
        if score > 0:
            candidate_mentions.append({"source": "history_archive", "score": score, "text": text, "evidence_type": evidence_type})

    if gm_memory:
        text = str(gm_memory)
        score, evidence_type = _score_evidence(surface_name, text, "gm_memory")
        if score > 0:
            candidate_mentions.append({"source": "gm_memory", "score": score, "text": text, "evidence_type": evidence_type})

    known_alias_hits = []
    for graph_key, node in major_graph.get("entities", {}).items():
        identity = node.get("identity", {}) if isinstance(node, dict) else {}
        for alias in identity.get("aliases", []):
            if alias.get("name") == surface_name:
                known_alias_hits.append({
                    "graph_key": graph_key,
                    "alias": surface_name,
                    "scope": alias.get("scope", "global_alias"),
                    "confidence": alias.get("confidence", 1.0),
                })

    candidate_mentions.sort(key=lambda x: x["score"], reverse=True)
    return {"surface_name": surface_name, "candidate_mentions": candidate_mentions[:8], "known_alias_hits": known_alias_hits}


def create_pending_reference(graph: dict, surface_name: str, evidence: str, reason: str) -> dict:
    """记录未解析称呼，不初始化 NPC。"""
    pending = graph.setdefault("pending_references", [])
    record = {
        "surface_name": surface_name,
        "referent_type": "character",
        "status": "unresolved",
        "evidence": evidence,
        "reason": reason,
        "should_initialize_npc": False,
    }
    pending.append(record)
    return graph


def resolve_npc_reference(surface_name: str, evidence_context: dict, major_graph: dict) -> dict:
    """第一阶段确定性解析：alias 命中与身份揭示句；后续可替换为 LLM 结构化解析。"""
    for hit in evidence_context.get("known_alias_hits", []):
        return {
            "status": "resolved",
            "target_graph_key": hit["graph_key"],
            "alias_scope": hit.get("scope", "global_alias"),
            "confidence": hit.get("confidence", 1.0),
            "reason": "命中已有 NPC alias",
        }

    for mention in evidence_context.get("candidate_mentions", []):
        if mention.get("evidence_type") == "identity_reveal":
            text = mention.get("text", "")
            for graph_key in major_graph.get("entities", {}).keys():
                if graph_key in text and graph_key != surface_name:
                    return {
                        "status": "resolved",
                        "target_graph_key": graph_key,
                        "alias_scope": "scene_bound",
                        "confidence": 0.9,
                        "reason": "证据句段揭示表面称呼指向已有 NPC",
                        "evidence": text,
                    }

    if evidence_context.get("candidate_mentions") and any(hint in surface_name for hint in UNRESOLVED_REFERENCE_HINTS):
        return {
            "status": "pending",
            "surface_name": surface_name,
            "should_initialize_npc": False,
            "reason": "有提及但无充分身份解析证据",
        }

    return {
        "status": "new_npc_allowed",
        "canonical_graph_key": surface_name,
        "reason": "无已有别名或待解析证据，允许后续结合 annotation 判断是否新建",
    }


def should_initialize_npc(surface_name: str, annotation: dict, resolution: dict) -> dict:
    """基于 LLM annotation 与结构化 resolution 检查是否允许初始化新 NPC。"""
    if resolution.get("status") in {"resolved", "pending", "non_character"}:
        return {"allowed": False, "reason": f"resolution={resolution.get('status')} 不应初始化新 NPC"}
    if annotation.get("entity_type") != "character":
        return {"allowed": False, "reason": "非角色实体不得初始化 NPC"}
    if not annotation.get("should_initialize_npc", False):
        return {"allowed": False, "reason": "LLM annotation 未授权初始化"}
    return {"allowed": True, "graph_key": resolution.get("canonical_graph_key") or surface_name, "reason": "角色实体且通过初始化 gate"}
