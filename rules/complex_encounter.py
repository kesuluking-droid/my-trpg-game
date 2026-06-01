# -*- coding: utf-8 -*-
"""
sandbox_rules/complex_encounter.py — 沙盒版本复杂对抗环境解析器

================================================================================
🔔 AI 助手维护提醒（每次修改前必读）
================================================================================

【沙盒版本绝对隔离原则】
- 本文件是 rules/complex_encounter.py 的 1:1 沙盒镜像副本
- 所有导入必须指向 sandbox_ 前缀版本
- 禁止直接调用主版本（rules/ 等）
- 沙盒修改不得污染主版本管线

【修改步骤】
1. 如需修改功能，先在此沙盒版本测试验证
2. 验证通过后，将修改实质迁移到主版本
3. 不要简单让主版本跳转到沙盒版本

【文件对应关系】
- sandbox_rules/complex_encounter.py ↔ rules/complex_encounter.py

================================================================================
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from rules.atomic_adjudicator import AtomicActionRequest, get_atomic_adjudicator


SUCCESS = "success"
FAILURE = "failure"
CRITICAL_FAILURE = "critical_failure"
PRESERVE_WEIGHTS = {"CRITICAL", "HIGH"}
TRUNCATE_WEIGHTS = {"MEDIUM", "LOW"}

# 6维度物品约束字段
CONSTRAINT_FIELDS = [
    "scene_plausible",
    "obtainable",
    "ownership_clear",
    "prerequisites_met",
    "safe_to_use",
    "world_compatible",
]

# 约束字段对应的中文说明（当 LLM 未提供 reason 时使用）
CONSTRAINT_FIELD_DESCRIPTIONS = {
    "scene_plausible": "该物品在当前场景中不存在或未被铺垫",
    "obtainable": "该物品无法被拾取或控制",
    "ownership_clear": "该物品所有权不明确，需要先夺取",
    "prerequisites_met": "玩家不满足使用该物品的条件",
    "safe_to_use": "使用该物品对玩家有致命风险",
    "world_compatible": "该物品不符合当前世界法则",
}

# 4维度动作约束字段
ACTION_CONSTRAINT_FIELDS = [
    "target_exists",
    "target_reachable",
    "environment_supports",
    "actor_capable",
]

ACTION_CONSTRAINT_FIELD_DESCRIPTIONS = {
    "target_exists": "动作目标不存在于当前场景",
    "target_reachable": "动作目标不在玩家可触及范围内",
    "environment_supports": "当前环境不支持该动作",
    "actor_capable": "玩家不具备执行该动作的条件",
}


def validate_item_constraints(item_data: dict, pc_entity: dict | None = None) -> tuple[bool, str]:
    """校验物品的6维度约束，返回 (是否通过, 失败原因)"""
    constraints = item_data.get("constraints") if isinstance(item_data, dict) else None
    if not constraints:
        return True, ""
    for field in CONSTRAINT_FIELDS:
        value = constraints.get(field)
        if value is False:
            reason = constraints.get("reason", "")
            if not reason:
                reason = CONSTRAINT_FIELD_DESCRIPTIONS.get(field, f"约束未通过: {field}")
            return False, reason
    return True, ""


def validate_action_constraints(action: dict) -> tuple[bool, str]:
    """校验动作的4维度约束，返回 (是否通过, 失败原因)"""
    constraints = action.get("action_constraints") if isinstance(action, dict) else None
    if not constraints:
        return True, ""
    for field in ACTION_CONSTRAINT_FIELDS:
        value = constraints.get(field)
        if value is False:
            reason = constraints.get("reason", "")
            if not reason:
                reason = ACTION_CONSTRAINT_FIELD_DESCRIPTIONS.get(field, f"动作约束未通过: {field}")
            return False, reason
    return True, ""


def empty_state_patch() -> dict[str, Any]:
    return {
        "inventory_changes": {"add": {}, "remove": []},
        "held_item_changes": {"add": {}, "remove": []},
        "graph_updates": {"entities": {}},
        "status_changes": {},
        "relation_changes": {},
        "event_log": [],
    }


class ComplexEncounterResolver:
    """玩家复合动作首版解析器：只处理同轮 action_sequence，不引入 NPC 主动回合。"""

    def __init__(self, adjudicator=None, adjudicator_backend: str = "standard_v1"):
        self.adjudicator = adjudicator or get_atomic_adjudicator(adjudicator_backend)

    def resolve(
        self,
        action_sequence: list[dict],
        major_graph: dict,
        pc_name: str,
        world_anchor_text: str,
        active_scene: list | None = None,
        entity_annotations: list[dict] | None = None,
    ) -> dict[str, Any]:
        from item_instances import ensure_item_instances
        major_graph = ensure_item_instances(major_graph)
        pc_entity = major_graph.get("entities", {}).get(pc_name, {})
        original_inventory = deepcopy(pc_entity.get("6_inventory", {}))
        original_held_items = deepcopy(pc_entity.get("7_held_items", {}))
        virtual_inventory = self._build_virtual_inventory(original_inventory, original_held_items)
        state_patch = empty_state_patch()
        state_patch["inventory_changes"]["pc_name"] = pc_name
        state_patch["held_item_changes"]["pc_name"] = pc_name
        pending_held_adds: dict[str, dict] = {}  # 追踪本轮新增的临时物品
        action_results: dict[str, dict] = {}
        micro_contributions: list[dict] = []
        debug_log: list[str] = []
        system_parts = ["\n【复杂对抗环境 | 玩家复合动作】"]
        canonical_map = self._build_item_canonical_map(entity_annotations)

        for index, raw_action in enumerate(action_sequence or []):
            action = self._normalize_action(raw_action, index, pc_name)
            if canonical_map:
                action = self._canonicalize_action_items(action, canonical_map)
            action_id = action["action_id"]

            blocked_by = self._first_failed_dependency(action.get("depends_on", []), action_results)
            if blocked_by:
                result = self._make_result(action, FAILURE, f"前置动作失败：{blocked_by}，本动作被跳过。")
                result["skipped_by_cascade"] = True
                action_results[action_id] = result
                micro_contributions.append(result)
                system_parts.append(f"- {action_id} {action['intended_action']}：前置动作失败，跳过。")
                continue

            required_ok, required_note = self._check_virtual_items(
                virtual_inventory,
                action.get("required_items", {}),
                action.get("reward_items", {}),
                action.get("temporary_items", {}),
            )
            if not required_ok:
                result = self._make_result(action, FAILURE, required_note)
                result["inventory_insufficient"] = True
                action_results[action_id] = result
                micro_contributions.append(result)
                system_parts.append(f"- {action_id} {action['intended_action']}：{required_note}")
                continue

            consumed_ok, consumed_note = self._check_virtual_items(
                virtual_inventory,
                action.get("consumed_items", {}),
                action.get("reward_items", {}),
                action.get("temporary_items", {}),
            )
            if not consumed_ok:
                result = self._make_result(action, FAILURE, consumed_note)
                result["inventory_insufficient"] = True
                action_results[action_id] = result
                micro_contributions.append(result)
                system_parts.append(f"- {action_id} {action['intended_action']}：{consumed_note}")
                continue

            # 检查动作的4维度约束
            action_passed, action_reason = validate_action_constraints(action)
            if not action_passed:
                result = self._make_result(action, FAILURE, f"动作约束未通过：{action_reason}")
                result["constraint_violation"] = True
                action_results[action_id] = result
                micro_contributions.append(result)
                system_parts.append(f"- {action_id} {action['intended_action']}：动作约束未通过")
                continue

            # 检查临时物品的6维度约束
            temp_items = action.get("temporary_items", {})
            pc_entity = major_graph.get("entities", {}).get(pc_name, {})
            for item_name, item_data in (temp_items or {}).items():
                passed, reason = validate_item_constraints(item_data, pc_entity)
                if not passed:
                    result = self._make_result(action, FAILURE, f"物品「{item_name}」约束未通过：{reason}")
                    result["constraint_violation"] = True
                    action_results[action_id] = result
                    micro_contributions.append(result)
                    system_parts.append(f"- {action_id} {action['intended_action']}：物品约束未通过（{item_name}）")
                    break
            else:
                # 所有约束通过，继续执行
                pass
            if action_results.get(action_id, {}).get("constraint_violation"):
                continue

            if action.get("is_risk") is False:
                numeric_result, adjudication_text, adjudication_debug = SUCCESS, f"动作【{action['intended_action']}】为无风险准备动作，自动成立。", {"backend_id": "setup_gate", "tier": "setup_success"}
            else:
                numeric_result, adjudication_text, adjudication_debug = self._resolve_action(
                    action,
                    major_graph,
                    world_anchor_text,
                    virtual_inventory,
                    pc_name,
                )
            result = self._make_result(action, numeric_result, adjudication_text)
            result["adjudicator_backend"] = adjudication_debug.get("backend_id")
            action_results[action_id] = result
            micro_contributions.append(result)
            debug_log.append(adjudication_debug)
            system_parts.append(f"- {action_id} {action['intended_action']}：{self._result_label(numeric_result)}")
            if adjudication_text:
                system_parts.append(f"\n【子动作 {action_id} 原子裁判】\n{adjudication_text}")

            if numeric_result == SUCCESS:
                temp_items = action.get("temporary_items", {})
                self._apply_temporary_to_virtual_inventory(temp_items, virtual_inventory)
                # 追踪本轮新增的临时物品
                for item_name, item_data in (temp_items or {}).items():
                    if item_name not in original_held_items and item_name not in original_inventory:
                        pending_held_adds[item_name] = deepcopy(item_data)
                self._apply_reward_to_virtual_inventory(
                    action.get("reward_items", {}),
                    virtual_inventory,
                    action.get("consumed_items", {}),
                )
                self._consume_virtual_items(virtual_inventory, action.get("consumed_items", {}))
                self._mark_consumed_held_items(action.get("consumed_items", {}), state_patch, pending_held_adds)
                self._apply_graph_delta(action.get("graph_entity_delta"), state_patch)
            else:
                # 失败时也要消耗投掷物、消耗品等"失败也消耗"类型
                consumed = action.get("consumed_items", {})
                if consumed:
                    self._consume_virtual_items_on_failure(
                        virtual_inventory,
                        consumed,
                        action.get("action_type", ""),
                        action.get("temporary_items", {}),
                        action.get("action_label")
                    )
                    self._mark_consumed_held_items_on_failure(
                        consumed,
                        action.get("action_type", ""),
                        action.get("temporary_items", {}),
                        virtual_inventory,
                        state_patch,
                        pending_held_adds,
                        action.get("action_label")
                    )

        # 把本轮新增的临时物品合并到 held_item_changes.add
        for item_name, item_data in pending_held_adds.items():
            state_patch["held_item_changes"]["add"][item_name] = deepcopy(item_data)

        self._finalize_inventory_patch(original_inventory, original_held_items, virtual_inventory, state_patch)
        sliced = self._slice_micro_contributions(micro_contributions)
        narrative_payload = self._build_narrative_payload(sliced)
        system_parts.append("指令：以上复合动作已按顺序裁决。续写时必须遵守先后因果，禁止向玩家暴露骰点、公式或内部数值。")

        # 检查是否有约束失败，向叙事生成注入强约束
        constraint_failed_items = []
        constraint_failed_actions = []
        for aid, ares in action_results.items():
            if ares.get("constraint_violation"):
                if ares.get("inventory_insufficient"):
                    constraint_failed_items.append(str(ares.get("target", "")))
                else:
                    constraint_failed_actions.append(aid)

        # 判断是否所有执行的子动作都因约束失败
        executed_actions = [a for a in action_results.values() if not a.get("skipped_by_cascade")]
        constraint_failed_executed = [a for a in executed_actions if a.get("constraint_violation")]
        all_actions_constraint_failed = bool(executed_actions) and len(constraint_failed_executed) == len(executed_actions)

        if constraint_failed_items or constraint_failed_actions:
            constraint_warning = "【世界法则约束·最高优先级】以下物品/动作被世界法则拒绝，叙事中绝对不可编造其出现或成功："
            if constraint_failed_items:
                constraint_warning += f"\n- 物品「{', '.join(constraint_failed_items)}」在当前场景中根本不存在，叙事中不能描写玩家获得、使用或看到这些物品。"
            if constraint_failed_actions:
                constraint_warning += f"\n- 动作「{', '.join(constraint_failed_actions)}」因前置条件不满足而无法执行，叙事中不能描写该动作成功或产生效果。"
            constraint_warning += "\n正确处理：描写玩家尝试失败、发现物品不存在、或动作无法进行的情景。"
            system_parts.append(constraint_warning)

        return {
            "system_injection": "\n".join(system_parts) + "\n",
            "state_patch": state_patch,
            "narrative_payload": narrative_payload,
            "action_results": action_results,
            "debug_log": debug_log,
            "all_actions_constraint_failed": all_actions_constraint_failed,
            "constraint_failed_items": constraint_failed_items,
            "constraint_failed_actions": constraint_failed_actions,
        }

    def _normalize_action(self, action: dict, index: int, pc_name: str) -> dict:
        normalized = deepcopy(action or {})
        normalized.setdefault("action_id", f"a{index + 1}")
        normalized.setdefault("actor", pc_name)
        normalized.setdefault("target", "环境")
        normalized.setdefault("action_type", "combat")
        normalized.setdefault("intended_action", "未命名动作")
        normalized.setdefault("detected_ability", None)
        normalized.setdefault("depends_on", [])
        normalized.setdefault("required_items", {})
        normalized.setdefault("consumed_items", {})
        normalized.setdefault("cost_items", {})
        normalized.setdefault("reward_items", {})
        normalized.setdefault("temporary_items", {})
        normalized.setdefault("target_part", None)
        normalized.setdefault("narrative_weight", "MEDIUM")
        normalized.setdefault("is_risk", True)
        if not normalized.get("consumed_items") and normalized.get("cost_items"):
            normalized["consumed_items"] = normalized.get("cost_items", {})
        if isinstance(normalized["depends_on"], str):
            normalized["depends_on"] = [normalized["depends_on"]]
        return normalized

    def _build_item_canonical_map(self, entity_annotations: list[dict] | None) -> dict[str, str]:
        item_types = {"object", "location_feature", "environment", "unknown"}
        item_roles = {"tool", "temporary_tool", "loot", "obstacle", "terrain", "context"}
        mapping: dict[str, str] = {}
        for ann in entity_annotations or []:
            if not isinstance(ann, dict):
                continue
            entity_type = str(ann.get("entity_type", "unknown")).strip()
            role = str(ann.get("role_in_action", "unknown")).strip()
            if entity_type not in item_types and role not in item_roles:
                continue
            name = str(ann.get("name", "")).strip()
            if not name:
                continue
            canonical = str(ann.get("canonical_name", name)).strip() or name
            mapping[name] = canonical
            mapping[canonical] = canonical
        return mapping

    def _canonicalize_action_items(self, action: dict, canonical_map: dict[str, str]) -> dict:
        normalized = deepcopy(action)
        for field in ("required_items", "consumed_items", "cost_items"):
            normalized[field] = self._canonicalize_quantity_items(normalized.get(field, {}), canonical_map)
        for field in ("temporary_items", "reward_items"):
            normalized[field] = self._canonicalize_data_items(normalized.get(field, {}), canonical_map)
        if not normalized.get("consumed_items") and normalized.get("cost_items"):
            normalized["consumed_items"] = normalized.get("cost_items", {})
        return normalized

    def _canonicalize_quantity_items(self, items: dict, canonical_map: dict[str, str]) -> dict:
        result: dict = {}
        for raw_name, qty in (items or {}).items():
            name = str(raw_name).strip()
            if not name:
                continue
            canonical = canonical_map.get(name, name)
            if canonical in result:
                result[canonical] = int(result[canonical] or 0) + int(qty or 0)
            else:
                result[canonical] = qty
        return result

    def _merge_persistence(self, old_value: str | None, new_value: str | None) -> str | None:
        priority = {"unknown": 0, "ephemeral": 1, "scene_bound": 2, "persistent": 3}
        old_text = str(old_value or "unknown")
        new_text = str(new_value or "unknown")
        return old_text if priority.get(old_text, 0) >= priority.get(new_text, 0) else new_text

    def _canonicalize_data_items(self, items: dict, canonical_map: dict[str, str]) -> dict:
        result: dict = {}
        for raw_name, item_data in (items or {}).items():
            name = str(raw_name).strip()
            if not name:
                continue
            canonical = canonical_map.get(name, name)
            data = deepcopy(item_data if isinstance(item_data, dict) else {"value": item_data})
            data.setdefault("source_name", name)
            if canonical not in result:
                result[canonical] = data
                continue
            existing = result[canonical]
            existing_tags = list(existing.get("tags", []) or []) if isinstance(existing, dict) else []
            new_tags = list(data.get("tags", []) or []) if isinstance(data, dict) else []
            if isinstance(existing, dict):
                existing["tags"] = list(dict.fromkeys(existing_tags + new_tags))
                existing["persistence"] = self._merge_persistence(existing.get("persistence"), data.get("persistence"))
                sources = existing.get("source_names") or [existing.get("source_name", canonical)]
                if name not in sources:
                    sources.append(name)
                existing.pop("source_name", None)
                existing["source_names"] = sources
        return result

    def _first_failed_dependency(self, depends_on: list[str], action_results: dict[str, dict]) -> str | None:
        for dep_id in depends_on or []:
            dep = action_results.get(dep_id)
            if not dep:
                return dep_id
            if dep.get("numeric_result") in {FAILURE, CRITICAL_FAILURE}:
                return dep_id
        return None

    def _check_virtual_items(self, virtual_inventory: dict, items: dict, same_action_rewards: dict | None = None, temporary_items: dict | None = None) -> tuple[bool, str]:
        same_action_rewards = same_action_rewards or {}
        temporary_items = temporary_items or {}
        for item_name, qty in (items or {}).items():
            count = int(qty or 0)
            if count <= 0:
                continue
            if item_name not in virtual_inventory and item_name not in temporary_items and item_name not in same_action_rewards:
                return False, f"虚拟资产不足：{item_name}"
        return True, ""

    def _build_virtual_inventory(self, original_inventory: dict, original_held_items: dict) -> dict:
        virtual_inventory = deepcopy(original_inventory or {})
        for item_name, item_data in (original_held_items or {}).items():
            virtual_inventory[item_name] = deepcopy(item_data)
        return virtual_inventory

    def _consume_virtual_items(self, virtual_inventory: dict, consumed_items: dict):
        for item_name, qty in (consumed_items or {}).items():
            if int(qty or 0) > 0:
                virtual_inventory.pop(item_name, None)

    def _should_consume_on_failure(self, item_name: str, item_data: dict | None, action_type: str, action_label: str | None = None) -> bool:
        """判断物品在动作失败时是否仍应消耗。
        投掷物、消耗品、给予动作 → 失败也消耗
        武器、工具、装备 → 失败不消耗
        """
        if item_data and isinstance(item_data, dict):
            tags = item_data.get("tags", [])
            # 投掷、消耗品、一次性 → 失败也消耗
            if any(t in tags for t in ["投掷", "投掷物", "消耗品", "一次性", "消耗"]):
                return True
        # 动作类型判断（同时检查 action_type 和 action_label）
        effective_type = action_label or action_type
        if effective_type in ["give", "offer", "throw", "ranged_attack", "throw_item"]:
            return True
        # 默认失败不消耗
        return False

    def _consume_virtual_items_on_failure(self, virtual_inventory: dict, consumed_items: dict, action_type: str, temporary_items: dict | None = None, action_label: str | None = None):
        """失败时只消耗'失败也消耗'类型的物品"""
        temp_items = temporary_items or {}
        for item_name, qty in (consumed_items or {}).items():
            if int(qty or 0) > 0:
                item_data = temp_items.get(item_name) or virtual_inventory.get(item_name)
                if self._should_consume_on_failure(item_name, item_data, action_type, action_label):
                    virtual_inventory.pop(item_name, None)

    def _mark_consumed_held_items(self, consumed_items: dict, state_patch: dict, pending_held_adds: dict | None = None):
        removals = state_patch.setdefault("held_item_changes", {}).setdefault("remove", [])
        pending = pending_held_adds or {}
        for item_name, qty in (consumed_items or {}).items():
            if int(qty or 0) > 0 and item_name not in removals:
                # 如果在 pending_held_adds 里，直接移除（不加入手持物）
                if item_name in pending:
                    del pending[item_name]
                else:
                    removals.append(item_name)

    def _mark_consumed_held_items_on_failure(self, consumed_items: dict, action_type: str, temporary_items: dict | None, virtual_inventory: dict, state_patch: dict, pending_held_adds: dict | None = None, action_label: str | None = None):
        """失败时只标记'失败也消耗'类型的手持物移除"""
        removals = state_patch.setdefault("held_item_changes", {}).setdefault("remove", [])
        adds = state_patch.setdefault("held_item_changes", {}).setdefault("add", {})
        temp_items = temporary_items or {}
        pending = pending_held_adds or {}
        for item_name, qty in (consumed_items or {}).items():
            if int(qty or 0) > 0 and item_name not in removals:
                item_data = temp_items.get(item_name) or virtual_inventory.get(item_name)
                if self._should_consume_on_failure(item_name, item_data, action_type, action_label):
                    # 如果已经在 pending_held_adds 里，直接移除
                    if item_name in pending:
                        del pending[item_name]
                    # 如果已经在 add 里，直接移除
                    elif item_name in adds:
                        del adds[item_name]
                    # 否则加入 remove
                    else:
                        removals.append(item_name)

    def _resolve_action(self, action: dict, major_graph: dict, world_anchor_text: str, virtual_inventory: dict | None = None, pc_name: str | None = None) -> tuple[str, str, dict]:
        explicit = action.get("numeric_result")
        if explicit in {SUCCESS, FAILURE, CRITICAL_FAILURE}:
            return explicit, action.get("scene_note") or f"动作【{action['intended_action']}】预设结果：{explicit}", {"backend_id": "explicit"}

        adjudication_graph = deepcopy(major_graph)
        if pc_name and virtual_inventory is not None:
            adjudication_graph.setdefault("entities", {}).setdefault(pc_name, {})["6_inventory"] = deepcopy(virtual_inventory)

        initiator_assets = list(action.get("initiator_matched_assets", []) or [])
        for item_name in (action.get("required_items") or {}).keys():
            if item_name not in initiator_assets:
                initiator_assets.append(item_name)

        request = AtomicActionRequest(
            action_id=action["action_id"],
            action_type=action.get("action_type", "combat"),
            initiator_name=action.get("actor"),
            target_name=action.get("target"),
            ability_name=action.get("detected_ability"),
            target_ongoing_action=action.get("target_ongoing_action"),
            initiator_assets=initiator_assets,
            target_assets=action.get("target_matched_assets", []),
            world_anchor_text=world_anchor_text,
            major_graph=adjudication_graph,
            is_social=action.get("action_type") == "social",
            ability_invalid=bool(action.get("ability_invalid", False)),
        )
        atomic_result = self.adjudicator.resolve(request)
        debug = dict(atomic_result.debug or {})
        debug["backend_id"] = atomic_result.backend_id
        debug["tier"] = atomic_result.tier
        return atomic_result.numeric_result, atomic_result.system_injection, debug

    def _make_result(self, action: dict, numeric_result: str, scene_note: str) -> dict:
        return {
            "action_id": action["action_id"],
            "actor": action.get("actor"),
            "target": action.get("target"),
            "target_part": action.get("target_part"),
            "intended_action": action.get("intended_action"),
            "numeric_result": numeric_result,
            "narrative_weight": action.get("narrative_weight", "MEDIUM"),
            "scene_note": scene_note,
            "affected_assets": action.get("affected_assets", []),
        }

    def _apply_temporary_to_virtual_inventory(self, temporary_items: dict, virtual_inventory: dict):
        for item_name, item_data in (temporary_items or {}).items():
            data = deepcopy(item_data or {"tags": ["通用"]})
            if isinstance(data, dict):
                data.setdefault("persistence", "ephemeral")
            virtual_inventory[item_name] = data

    def _apply_reward_to_virtual_inventory(self, reward_items: dict, virtual_inventory: dict, consumed_items: dict | None = None):
        consumed_items = consumed_items or {}
        for item_name, item_data in (reward_items or {}).items():
            if item_name in consumed_items:
                continue
            virtual_inventory[item_name] = deepcopy(item_data or {"tags": ["通用"], "multiplier": 1.0})

    def _finalize_inventory_patch(self, original_inventory: dict, original_held_items: dict, virtual_inventory: dict, state_patch: dict):
        original_keys = set(original_inventory.keys())
        original_held_keys = set((original_held_items or {}).keys())
        final_keys = set(virtual_inventory.keys())

        for item_name in sorted(original_keys - final_keys):
            state_patch["inventory_changes"]["remove"].append(item_name)

        for item_name in sorted(original_held_keys - final_keys):
            state_patch["held_item_changes"]["remove"].append(item_name)

        for item_name in sorted(final_keys - original_keys):
            if isinstance(virtual_inventory.get(item_name), dict) and virtual_inventory[item_name].get("persistence") == "ephemeral":
                if item_name not in original_held_keys:
                    state_patch["held_item_changes"]["add"][item_name] = deepcopy(virtual_inventory[item_name])
                continue
            state_patch["inventory_changes"]["add"][item_name] = deepcopy(virtual_inventory[item_name])

        for item_name in sorted(original_keys & final_keys):
            if original_inventory.get(item_name) != virtual_inventory.get(item_name):
                state_patch["inventory_changes"]["add"][item_name] = deepcopy(virtual_inventory[item_name])

        for item_name in sorted(original_held_keys & final_keys):
            if item_name not in original_keys and original_held_items.get(item_name) != virtual_inventory.get(item_name):
                state_patch["held_item_changes"]["add"][item_name] = deepcopy(virtual_inventory[item_name])

    def _apply_graph_delta(self, graph_delta: dict | None, state_patch: dict):
        if not isinstance(graph_delta, dict) or not graph_delta.get("entity_name"):
            return
        state_patch["graph_updates"]["entities"][graph_delta["entity_name"]] = deepcopy(graph_delta.get("fields", {}))

    def _slice_micro_contributions(self, entries: list[dict]) -> list[dict]:
        preserved = [e for e in entries if str(e.get("narrative_weight", "MEDIUM")).upper() in PRESERVE_WEIGHTS]
        truncatable = [e for e in entries if str(e.get("narrative_weight", "MEDIUM")).upper() in TRUNCATE_WEIGHTS]
        result = preserved + truncatable[:2]
        if len(truncatable) > 2:
            result.append({"action_id": "background_noise", "scene_note": "其余低权重动作被压缩为混战背景噪音。", "narrative_weight": "LOW"})
        return result

    def _build_narrative_payload(self, micro_contributions: list[dict]) -> dict:
        return {
            "micro_contributions": micro_contributions,
            "narrative_constraints": "根据复合动作裁决结果续写；禁止暴露骰点、DC、公式或内部数值。",
        }

    def _result_label(self, numeric_result: str) -> str:
        return {
            SUCCESS: "成功",
            FAILURE: "失败",
            CRITICAL_FAILURE: "灾难性失败",
        }.get(numeric_result, numeric_result)
