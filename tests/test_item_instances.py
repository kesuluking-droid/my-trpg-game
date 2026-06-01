# -*- coding: utf-8 -*-
import unittest

from sandbox_item_instances import (
    create_item_instance,
    ensure_item_instances,
    mark_item_consumed,
    move_item_instance,
    resolve_item_reference,
    sync_legacy_item_index,
    update_item_state_tags,
)


class ItemInstancesMigrationTest(unittest.TestCase):
    def test_legacy_inventory_migrates_to_item_instances(self):
        graph = {
            "entities": {
                "方拓": {
                    "tags": ["玩家"],
                    "6_inventory": {
                        "火把": {"tags": ["照明"], "multiplier": 1.0}
                    },
                    "7_held_items": {},
                }
            }
        }

        migrated = ensure_item_instances(graph)

        self.assertIn("item_instances", migrated)
        inventory_item = migrated["entities"]["方拓"]["6_inventory"]["火把"]
        self.assertIn("instance_id", inventory_item)
        instance_id = inventory_item["instance_id"]
        self.assertIn(instance_id, migrated["item_instances"])
        instance = migrated["item_instances"][instance_id]
        self.assertEqual(instance["canonical_name"], "火把")
        self.assertEqual(instance["holder"], "方拓")
        self.assertEqual(instance["container"], "inventory")
        self.assertEqual(instance["tags"], ["照明"])


class ItemInstanceMovementTest(unittest.TestCase):
    def test_create_wall_torch_and_move_to_held_index(self):
        graph = {"entities": {"方拓": {"6_inventory": {}, "7_held_items": {}}}, "item_instances": {}}
        instance_id = create_item_instance(
            graph,
            "火把",
            {"display_name": "墙上的燃烧火把", "tags": ["照明", "燃烧"], "state_tags": ["燃烧"], "multiplier": 1.0},
            holder=None,
            container="environment",
            location="墙上",
            source="墙上",
        )

        move_item_instance(graph, instance_id, holder="方拓", container="held", location="手持")
        sync_legacy_item_index(graph, "方拓", instance_id, "7_held_items")

        self.assertIn("火把", graph["entities"]["方拓"]["7_held_items"])
        held = graph["entities"]["方拓"]["7_held_items"]["火把"]
        self.assertEqual(held["instance_id"], instance_id)
        self.assertEqual(graph["item_instances"][instance_id]["holder"], "方拓")
        self.assertEqual(graph["item_instances"][instance_id]["container"], "held")


class ItemReferenceResolutionTest(unittest.TestCase):
    def test_use_torch_prefers_held_item(self):
        graph = {"entities": {"方拓": {"6_inventory": {}, "7_held_items": {}}}, "item_instances": {}}
        held_id = create_item_instance(graph, "火把", {"display_name": "手中的火把", "tags": ["照明"]}, holder="方拓", container="held", location="手持")
        wall_id = create_item_instance(graph, "火把", {"display_name": "墙上的火把", "tags": ["照明"]}, holder=None, container="environment", location="墙上")

        result = resolve_item_reference("火把", "火把", graph, "方拓", {"verb": "用"})

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["instance_id"], held_id)
        self.assertNotEqual(result["instance_id"], wall_id)

    def test_take_torch_prefers_environment_item(self):
        graph = {"entities": {"方拓": {"6_inventory": {}, "7_held_items": {}}}, "item_instances": {}}
        inventory_id = create_item_instance(graph, "火把", {"display_name": "背包里的火把", "tags": ["照明"]}, holder="方拓", container="inventory", location="背包")
        wall_id = create_item_instance(graph, "火把", {"display_name": "墙上的火把", "tags": ["照明"]}, holder=None, container="environment", location="墙上")

        result = resolve_item_reference("墙上的火把", "火把", graph, "方拓", {"verb": "拔下"})

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["instance_id"], wall_id)
        self.assertNotEqual(result["instance_id"], inventory_id)

    def test_ambiguous_left_and_right_torches(self):
        graph = {"entities": {"方拓": {"6_inventory": {}, "7_held_items": {}}}, "item_instances": {}}
        left_id = create_item_instance(graph, "火把", {"display_name": "左墙火把", "tags": ["照明"]}, holder=None, container="environment", location="左墙")
        right_id = create_item_instance(graph, "火把", {"display_name": "右墙火把", "tags": ["照明"]}, holder=None, container="environment", location="右墙")

        result = resolve_item_reference("火把", "火把", graph, "方拓", {"verb": "拔下"})

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(set(result["candidates"]), {left_id, right_id})


class ItemStateAndStackTest(unittest.TestCase):
    def test_update_state_tags_does_not_create_new_instance(self):
        graph = {"entities": {"方拓": {"6_inventory": {}, "7_held_items": {}}}, "item_instances": {}}
        torch_id = create_item_instance(graph, "火把", {"display_name": "熄灭的火把", "state_tags": ["熄灭"]}, holder="方拓", container="held", location="手持")
        update_item_state_tags(graph, torch_id, add_tags=["燃烧"], remove_tags=["熄灭"])

        self.assertEqual(len(graph["item_instances"]), 1)
        self.assertIn("燃烧", graph["item_instances"][torch_id]["state_tags"])
        self.assertNotIn("熄灭", graph["item_instances"][torch_id]["state_tags"])

    def test_mark_consumed_removes_legacy_index(self):
        graph = {"entities": {"方拓": {"6_inventory": {}, "7_held_items": {}}}, "item_instances": {}}
        torch_id = create_item_instance(graph, "火把", {"display_name": "火把"}, holder="方拓", container="held", location="手持")
        sync_legacy_item_index(graph, "方拓", torch_id, "7_held_items")

        mark_item_consumed(graph, torch_id)

        self.assertEqual(graph["item_instances"][torch_id]["status"], "consumed")
        self.assertEqual(graph["entities"]["方拓"]["7_held_items"], {})

    def test_coin_quantity_is_stack(self):
        graph = {"entities": {"方拓": {"6_inventory": {"铜钱": {"quantity": 100, "unit": "枚"}}, "7_held_items": {}}}}
        ensure_item_instances(graph)
        coin = next(iter(graph["item_instances"].values()))
        self.assertEqual(coin["canonical_name"], "铜钱")
        self.assertEqual(coin["item_kind"], "stack")
        self.assertEqual(coin["quantity"], 100)


if __name__ == "__main__":
    unittest.main()
