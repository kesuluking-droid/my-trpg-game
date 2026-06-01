# 全局物品实例池设计文档

## 目标

引入全局物品实例池 `item_instances`，解决同一物品多种叫法导致的归一问题，同时避免场景中存在多个同类物品时误合并。例如：

- `墙上的火把`、`燃烧的火把`、`火把` 在确实指向同一支火把时应归一。
- `左墙火把`、`右墙火把`、`玩家手里的火把` 在确实为不同实体时不得合并。

第一阶段采用 **全局物品实例池 + 旧字段兼容索引**：新增 `major_graph["item_instances"]` 作为真实物品实体池，同时保留 `6_inventory` / `7_held_items` 作为旧代码兼容索引。

---

## 核心原则

1. `canonical_name` 表示“它是什么”，例如 `火把`。
2. `instance_id` 表示“它是哪一个”，例如 `item_torch_left_wall_001`。
3. `6_inventory` / `7_held_items` 暂时保留，作为兼容索引、展示索引、旧裁决兜底索引。
4. 新逻辑优先解析 `item_instances`，旧逻辑仍可读取 `6_inventory` / `7_held_items`。
5. 所有改造先在沙盒文件实现，通过 `sync_sandbox_to_main.py` 映射到主版本。

---

## 推荐架构

新增沙盒模块：

```text
sandbox_item_instances.py
```

同步脚本新增映射：

```python
"sandbox_item_instances.py": "item_instances.py"
```

同步脚本新增导入转换：

```python
(r"from sandbox_item_instances", "from item_instances"),
(r"import sandbox_item_instances", "import item_instances"),
```

---

## 数据结构

### 顶层实例池

```json
{
  "item_instances": {
    "item_torch_wall_001": {
      "instance_id": "item_torch_wall_001",
      "canonical_name": "火把",
      "display_name": "墙上的燃烧火把",
      "item_kind": "instance",
      "holder": null,
      "owner": null,
      "container": "environment",
      "location": "左墙",
      "source": "墙上",
      "state_tags": ["燃烧"],
      "tags": ["照明", "燃烧", "临时武器"],
      "quantity": 1,
      "unit": "支",
      "multiplier": 1.0,
      "persistence": "scene_bound",
      "created_from": "entity_annotation",
      "status": "active"
    }
  }
}
```

### 旧字段兼容索引

```json
{
  "entities": {
    "方拓": {
      "6_inventory": {
        "火把": {
          "instance_id": "item_torch_inventory_001",
          "canonical_name": "火把",
          "tags": ["照明"],
          "multiplier": 1.0
        }
      },
      "7_held_items": {
        "火把": {
          "instance_id": "item_torch_wall_001",
          "canonical_name": "火把",
          "tags": ["照明", "燃烧"],
          "multiplier": 1.0
        }
      }
    }
  }
}
```

旧结构中的 key 不是唯一身份，只是兼容索引。真实身份以 `instance_id` 为准。

---

## 多实例命名规则

当同一容器中存在多个同 `canonical_name` 的实例时，兼容索引 key 使用稳定短 key：

```json
"7_held_items": {
  "火把": {
    "instance_id": "item_torch_001",
    "canonical_name": "火把"
  },
  "火把#2": {
    "instance_id": "item_torch_002",
    "canonical_name": "火把"
  }
}
```

具体显示名放在物品数据内：

```json
"display_name": "左墙上的火把"
```

这样兼容旧代码的同时，避免把冗长描述当成稳定 key。

---

## 核心函数

`sandbox_item_instances.py` 应提供：

```python
def ensure_item_instances(graph: dict) -> dict:
    """迁移旧 6_inventory / 7_held_items 到 item_instances，并写回 instance_id。"""


def create_item_instance(graph: dict, canonical_name: str, item_data: dict, *, holder=None, container="environment", location=None, source=None) -> str:
    """创建新物品实例，返回 instance_id。"""


def resolve_item_reference(raw_name: str, canonical_name: str, graph: dict, pc_name: str, action_context: dict) -> dict:
    """将自然语言物品引用解析到 instance_id；歧义时返回 ambiguous。"""


def move_item_instance(graph: dict, instance_id: str, *, holder=None, container=None, location=None) -> dict:
    """移动物品实例，例如从 environment 到 held。"""


def sync_legacy_item_index(graph: dict, entity_name: str, instance_id: str, target_slot: str) -> dict:
    """把实例同步到 6_inventory 或 7_held_items 兼容索引。"""


def mark_item_consumed(graph: dict, instance_id: str) -> dict:
    """将物品标记为 consumed，并从兼容索引移除。"""


def cleanup_ephemeral_items(graph: dict) -> dict:
    """清理不再被引用的 ephemeral 物品。"""
```

---

## 引用解析规则

当玩家输入 `火把` 或 `墙上的火把` 时，Python 不直接用字符串落盘，而是：

1. 读取 `entity_annotations[].canonical_name`。
2. 收集候选实例：
   - 玩家手持物
   - 玩家背包物
   - 场景环境物
   - NPC 持有物
3. 按上下文打分：
   - `手里/手中` → 优先 `container=held`
   - `背包/包里` → 优先 `container=inventory`
   - `墙上/左边/右边/地上` → 优先匹配 `location/source`
   - 动作是 `用/挥/挡/攻击` → 优先手持
   - 动作是 `拔下/取下/捡起` → 优先环境
   - 出现 `再/另一支/第二支` → 排除已有手持实例，寻找另一个候选或创建新实例
4. 决策：
   - 唯一高置信候选 → `resolved`
   - 多个同分候选 → `ambiguous`
   - 无候选但场景合理 → `create_new`
   - 无候选且场景不合理 → `invalid`

返回示例：

```json
{
  "status": "resolved",
  "instance_id": "item_torch_wall_001",
  "confidence": 0.92,
  "reason": "raw_name 包含 墙上，且候选实例 location=墙上"
}
```

歧义示例：

```json
{
  "status": "ambiguous",
  "candidates": ["item_torch_left_001", "item_torch_right_001"],
  "reason": "存在多个火把，输入未指定位置或持有者"
}
```

---

## 堆叠物品与实例物品

新增字段：

```json
"item_kind": "instance" | "stack"
```

### instance

用于：

- 长剑
- 火把
- 钥匙
- 戒指
- 山贼刀
- 任务道具

### stack

用于：

- 铜钱
- 箭矢
- 粮食
- 水
- 普通石子

示例：

```json
"item_stack_coin_001": {
  "canonical_name": "铜钱",
  "item_kind": "stack",
  "quantity": 100,
  "unit": "枚",
  "holder": "方拓",
  "container": "inventory"
}
```

如果堆叠物品出现特殊状态，例如 `淬毒箭`，应拆成独立 stack 或 instance。

---

## 模块影响

### `sandbox_intent_parser.py`

- 保留 `entity_annotations`。
- 在解析后调用 `ensure_item_instances(graph)`。
- 使用 `resolve_item_reference()` 处理 action_sequence 中的物品字段。

### `sandbox_rules/complex_encounter.py`

- 第一阶段仍读取 `6_inventory` / `7_held_items`。
- 进入 resolver 前确保兼容索引已经同步。
- `required_items` / `consumed_items` 可先解析到 `instance_id`，再映射到兼容 key。

### `sandbox_rules/adjudication_utils.py`

- 第一阶段保持现状，继续扫描旧字段。
- 后续阶段改成优先读 `item_instances`。

### `sandbox_integration.py`

- 门铃同步新增 `6_inventory` 时，应创建物品实例并同步兼容索引。
- 第一阶段可以保留旧写入，同时补写实例池。

### `sandbox_app.py`

- 第一阶段 UI 仍展示旧字段。
- 调试面板可展示 `instance_id`、`canonical_name`、`state_tags`、`container`、`location`。

---

## 测试要求

新增：

```text
tests/test_item_instances.py
```

覆盖：

1. 旧背包迁移：`6_inventory: 火把` → 生成 `item_instances` 且写回 `instance_id`。
2. 唯一火把归一：`墙上的火把` 与 `火把` 指向同一实例。
3. 两个火把不合并：左墙/右墙火把生成两个实例。
4. 手持优先：手持火把 + 墙上火把，输入 `用火把`，选择手持。
5. 取下优先环境：背包火把 + 墙上火把，输入 `拔下火把`，选择墙上。
6. 再拿一支：已有手持火把，输入 `再拿一支`，选择另一个或创建新实例。
7. 状态变化：`点燃火把` 更新同一实例 `state_tags`，不新增 `燃烧的火把`。
8. 堆叠物品：`铜钱100枚` 是 stack，不生成 100 个实例。

---

## 第一阶段不做

- 不删除 `6_inventory` / `7_held_items`。
- 不全面重构 UI。
- 不实现完整容器嵌套。
- 不实现耐久度系统。
- 不实现经济系统。
- 不实现多玩家交易。

---

## 兼容版到完全版的过渡路线

### 阶段 1：兼容版落地

- 新增 `item_instances`。
- 迁移旧 `6_inventory` / `7_held_items`，写回 `instance_id`。
- 新物品写入实例池，同时同步旧索引。
- 裁决与 UI 仍读旧索引。

### 阶段 2：读路径切换

- 裁决系统优先读取 `item_instances`。
- 旧 `6_inventory` / `7_held_items` 只作为 fallback。
- 日志展示显示 `display_name` 与 `instance_id`。

### 阶段 3：写路径切换

- 门铃同步、复合动作、奖励/消耗全部只写 `item_instances`。
- 旧索引由 `sync_legacy_item_index()` 自动生成，不再由业务逻辑手写。

### 阶段 4：UI 与调试面板升级

- 普通 UI 聚合同类物品展示，例如 `火把 ×2`。
- 调试 UI 展示每个实例详情。
- 歧义时在日志中提示候选实例。

### 阶段 5：完全版

- 引入 `6_inventory_refs` / `7_held_item_refs`。
- 旧 `6_inventory` / `7_held_items` 降级为只读兼容视图。
- 最终可删除旧写入路径，但需保留旧存档迁移。

---

## 成功标准

1. 一个火把多种叫法能归一到同一 `instance_id`。
2. 两个火把不会误合并。
3. 旧裁决逻辑仍可通过 `6_inventory` / `7_held_items` 工作。
4. 新增物品、临时物品、手持物都能在 `item_instances` 中追踪。
5. 沙盒测试通过后，可通过映射脚本同步主版本。

