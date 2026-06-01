# -*- coding: utf-8 -*-
import unittest

from sandbox_npc_lifecycle import (
    build_npc_evidence_context,
    create_pending_reference,
    ensure_npc_identity,
    merge_npc_alias,
    resolve_npc_reference,
    should_initialize_npc,
)


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

    def test_bandit_can_initialize_when_annotation_allows(self):
        resolution = {"status": "new_npc_allowed", "canonical_graph_key": "山贼"}
        decision = should_initialize_npc("山贼", {"entity_type": "character", "should_initialize_npc": True}, resolution)

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["graph_key"], "山贼")


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


if __name__ == "__main__":
    unittest.main()
