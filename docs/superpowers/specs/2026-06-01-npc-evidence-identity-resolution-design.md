# NPC 证据检索与身份解析设计文档

## 目标

改造 NPC 生成与更新前的身份判断流程，避免仅凭最近三段上下文或表面称呼粗暴生成 NPC。系统需要能处理：

- `神秘人` / `那个不能说名字的人` / `那个人` 这类中文代称。
- `乔峰` / `萧峰` 这类多名同人。
- `黑衣人摘下面罩，竟是慕容复` 这类伪装身份揭示。
- `师父` / `帮主` / `皇帝` 这类关系称呼或头衔称呼。
- 多个 `黑衣人` / 多个 `山贼` / 同名不同人。

核心目标是：**初始化 NPC 前必须先检索证据、解析指向、判断别名作用域；不能把表面称呼直接当作长期 NPC 主键。**

---

## 当前语言范围

当前游戏第一阶段只适配中文，因此本设计第一阶段只要求处理中文称呼系统：

- 中文代称：`神秘人`、`那个不能说名字的人`、`那个人`。
- 中文尊称/蔑称：`乔帮主`、`萧大王`、`老贼`、`契丹人`。
- 中文关系称呼：`师父`、`爹`、`大师兄`。
- 中文头衔称呼：`丐帮帮主`、`少林方丈`、`皇帝`。
- 中文伪装称呼：`黑衣人`、`蒙面人`、`白衣女子`。

`You-Know-Who` 等英文示例只作为概念说明和未来扩展示例，不作为第一阶段必须支持的测试目标。第一阶段对应中文测试应使用 `神秘人`、`那个不能说名字的人`、`黑魔王` 等表达。

需要强调：**中文优先是当前产品范围，不是底层设计哲学。** 身份解析系统不能写死为中文词表匹配器，而应保持“表面称呼 → 证据检索 → LLM 结构化身份解析 → scoped alias → 稳定身份”的通用结构。中文词表只用于第一阶段测试、提示词示例和证据召回辅助。

---

## 设计核心哲学

本系统必须服从项目总哲学：**LLM 造世，Python 书记**。因此，本设计的目标不是让 Python 接管 NPC 身份语义判断，而是让 Python 为 LLM 提供更好的长期记忆、证据检索和落盘边界。

本系统的局部原则不是“把某些词替换成某些人”，而是：

> **NPC 身份是稳定对象，称呼是带语境的证据。**

因此第一阶段即使只服务中文，也必须遵守以下原则。

### 1. 称呼不是身份

`神秘人`、`黑衣人`、`乔帮主`、`师父`、`萧峰` 都只是 surface name。它们可能是：

- 禁忌代称
- 尊称
- 蔑称
- 头衔
- 关系称呼
- 伪装身份
- 真名/本名
- 阶段性称呼

只有经过证据解析后，才能绑定到某个稳定 NPC。

### 2. 身份解析不是简单 canonicalize

NPC 与物品不同。物品的 `墙上的火把 -> 火把` 很多时候可以做类型归一；但 NPC 的 `黑衣人 -> 慕容复` 不能变成全局规则。NPC 解析必须保留：

- 谁这样称呼他
- 在什么场景这样称呼
- 这个称呼是尊称、蔑称、伪装还是本名
- 这个称呼是否只在某段剧情内有效
- 这个称呼是否已被叙事明确揭示

### 3. 证据优先，词表只做召回辅助

中文词表只能辅助召回“这可能是称呼/代称/头衔”的相关句段，不能直接决定身份，也不能成为正式黑白名单。真正用于身份判断的是由 LLM 阅读的证据包：

- 前文同句出现代称与真名
- 叙事出现身份揭示词
- 已有 `identity.aliases` 命中且 scope 合法
- 关系事实支持该称呼
- 场景特征与已知伪装身份一致

Python 可以给证据句段排序、去重、裁剪，但不应仅凭关键词表把 `黑衣人` 判定为某个具体 NPC。

### 4. 不确定时宁可挂起，不污染图谱

如果 LLM 基于证据包仍无法确认 `那个人`、`黑衣人`、`师父` 指谁，Python 应创建 `pending_references`，而不是初始化长期 NPC。这是落盘边界，不是对叙事自由的限制：LLM 仍可在叙事中描写神秘人，但 Python 不把未确认身份写进长期图谱。

### 5. 不自动改名

人物可以有多个名字，但 graph key 不应频繁变化。`乔峰` 被揭示本名 `萧峰` 后，默认添加 alias 和身份事实，不自动把图谱主键改为 `萧峰`。只有强剧情证据才允许更新 `display_name`，仍不改 graph key。

### 6. 局部 alias 不得污染全局

`黑衣人摘下面罩，竟是慕容复` 只说明那个特定黑衣人是慕容复。未来出现另一个黑衣人时，不得自动解析到慕容复。

### 7. 结构要为未来扩展预留空间

第一阶段测试中文，但数据结构必须能容纳未来的：

- 多语言别名
- 音译/别译
- 方言称呼
- 宗教名/法号
- 官职变动
- 秘密身份
- 错误指认
- 不同角色的不同认知

因此 alias 记录中可以预留 `language`、`speaker_scope`、`valid_scene_id`、`confidence`、`evidence` 等字段，即使第一阶段不全部使用。

---

## 与项目核心设计哲学的对齐

### 「LLM 造世，Python 书记」

本设计不得让 Python 决定“谁是谁”的开放世界语义。正确分工是：

| 环节 | 负责方 | 说明 |
|---|---|---|
| 叙事中某称呼是否具有身份含义 | LLM | LLM 根据证据包判断 |
| 跨上下文证据召回 | Python | Python 帮 LLM 找回长期记忆 |
| 是否允许写入长期图谱 | Python | Python 检查结构化结果、置信度、证据与权限边界 |
| 别名、pending、identity 的落盘 | Python | Python 作为书记员记录 LLM 的判断 |
| 不确定内容的叙事保留 | LLM | LLM 仍可描写神秘人、黑衣人、传闻人物 |

因此 `resolve_npc_reference()` 不应设计成纯 Python 身份裁决器，而应是：

```text
Python 召回证据 → LLM 读取证据并给出结构化身份解析 → Python 校验并落盘
```

### 「Python 是外置大脑，而非枷锁」

Python 的作用是补足 LLM 的长期记忆和一致性弱点：

- 帮 LLM 找回早期提到的别名、身份揭示、关系线索。
- 防止 LLM 一时幻觉把 `神秘人`、`黑衣人` 写成长期 NPC。
- 记录 alias scope，避免之后上下文遗忘。

Python 不应该禁止 LLM 创造新的神秘人物，也不应该强迫所有称呼提前解析。未解析的称呼可以作为 `pending_reference` 留在世界中，等待后续剧情揭示。

### 「反黑白名单原则」

本设计中的中文称呼示例不是正式黑白名单。实现时应避免：

```python
if name in {"黑衣人", "神秘人", "师父"}:
    不初始化
```

更合理的方式是让 LLM 输出结构化语义：

```json
{
  "surface_name": "黑衣人",
  "referent_type": "character_alias",
  "alias_scope": "scene_bound",
  "identity_confidence": 0.42,
  "should_initialize_npc": false,
  "reason": "当前证据不足以确认其真实身份"
}
```

Python 只检查这些结构化字段是否满足写入条件。

词表只允许作为召回提示和热补丁，不应成为正式架构的核心。

### 「世界不以玩家为绝对中心」

身份信息也要遵守信息不对称：

- 如果世界事实上黑衣人是慕容复，但玩家尚未获得证据，叙事不应直接剧透。
- 图谱可以在内部记录事实与玩家可知信息的差异，但第一阶段先只实现 `pending_reference` 和 `evidence`，不做完整 belief system。
- 后续如果做世界自运行，应区分 `fact_identity` 与 `player_known_identity`。

第一阶段不实现完整信息可见性系统，但设计结构必须不阻断未来扩展。

---

## 核心原则

1. **surface_name 不等于 NPC 身份**  
   `神秘人`、`那个不能说名字的人`、`黑衣人`、`师父` 是表面称呼，不应直接落成长期图谱主键。

2. **graph key 不轻易改名**  
   乔峰被揭示为萧峰时，不应直接把 `entities["乔峰"]` 改成 `entities["萧峰"]`。稳定身份由 `identity.npc_id` 表示，显示名由 `identity.display_name` 表示。

3. **alias 必须带 scope**  
   `黑衣人 -> 慕容复` 只能绑定到特定场景或特定实例，不能让后续所有黑衣人都自动等于慕容复。

4. **无法解析时挂起，不初始化**  
   无足够证据的代称进入 `pending_references`，不进入 `entities`。

5. **证据检索先于 LLM 身份解析**  
   先从 `active_scene`、`history_archive`、`major_graph`、`gm_memory` 中检索相关句段，再把精简证据包交给 LLM 做结构化身份解析。Python 只做 schema 校验、权限边界和落盘。

---

## 推荐新增模块

新增沙盒模块：

```text
sandbox_npc_lifecycle.py
```

职责：

```python
def build_npc_evidence_context(surface_name, major_graph, active_scene, history_archive=None, gm_memory=None):
    """为表面称呼构造证据上下文。"""


def resolve_npc_reference(surface_name, evidence_context, major_graph):
    """调用 LLM 基于证据包做结构化身份解析，再返回待校验结果。"""


def should_initialize_npc(surface_name, annotation, resolution):
    """基于 LLM 解析结果与结构化字段，检查是否允许初始化新 NPC。"""


def ensure_npc_identity(graph, graph_key):
    """确保已有 NPC 节点拥有 identity 子结构。"""


def merge_npc_alias(graph, graph_key, alias_record):
    """给已有 NPC 合并 alias，避免重复对象。"""


def create_pending_reference(graph, surface_name, evidence, reason):
    """记录未解析称呼，不初始化 NPC。"""
```

同步脚本后续需要增加：

```python
"sandbox_npc_lifecycle.py": "npc_lifecycle.py"
```

以及导入转换：

```python
(r"from sandbox_npc_lifecycle", "from npc_lifecycle"),
(r"import sandbox_npc_lifecycle", "import npc_lifecycle"),
```

---

## NPC identity 子结构

每个长期 NPC 节点应逐步补齐：

```json
{
  "identity": {
    "npc_id": "npc_xiao_feng_001",
    "primary_name": "乔峰",
    "display_name": "乔峰",
    "preferred_name": "乔峰",
    "legal_or_origin_name": "萧峰",
    "identity_status": "known",
    "rename_policy": "do_not_auto_rename_primary_without_strong_story_event",
    "aliases": [
      {
        "name": "萧峰",
        "type": "origin_name",
        "scope": "global_alias",
        "sentiment": "identity_reveal",
        "confidence": 1.0,
        "evidence": "乔峰其实本姓萧"
      },
      {
        "name": "乔帮主",
        "type": "title",
        "scope": "role_title",
        "sentiment": "respect",
        "speaker_scope": "江湖人士",
        "confidence": 0.95
      }
    ],
    "pending_aliases": []
  }
}
```

说明：

| 字段 | 用途 |
|---|---|
| `npc_id` | 稳定身份 ID |
| `primary_name` | 图谱初始主名，不轻易修改 |
| `display_name` | 当前叙事展示名，可随强剧情事件变化 |
| `preferred_name` | 角色主观偏好的称呼 |
| `legal_or_origin_name` | 本名、出身名、真实姓名 |
| `aliases` | 已解析称呼记录 |
| `pending_aliases` | 暂未确认但可能相关的称呼 |

---

## alias scope 设计

alias 不能只是字符串映射，必须包含作用域。

### 1. `global_alias`

全局别名，通常可稳定指向同一人。

例子：

```json
{
  "name": "神秘人",
  "type": "taboo_alias",
  "scope": "global_alias",
  "resolved_to": "伏地魔",
  "sentiment": "fear"
}
```

适合：

- 伏地魔 / 神秘人 / 黑魔王 / 那个不能说名字的人
- 乔峰 / 萧峰，前提是世界观或剧情已明确同一人

第一阶段只要求中文别名，例如 `伏地魔 / 神秘人 / 黑魔王 / 那个不能说名字的人`。英文别名留作未来扩展。

### 2. `speaker_relative`

依赖说话者关系。

例子：

```json
{
  "name": "师父",
  "scope": "speaker_relative",
  "speaker": "方拓",
  "resolved_to": "岳不群"
}
```

别人说“师父”时不能自动解析为岳不群。

### 3. `role_title`

依赖职位、时代或剧情阶段。

例子：

```json
{
  "name": "丐帮帮主",
  "scope": "role_title",
  "resolved_to": "乔峰",
  "valid_when": "乔峰仍任丐帮帮主"
}
```

乔峰卸任后，“丐帮帮主”不可继续默认指乔峰。

### 4. `scene_bound`

只在特定场景或事件中生效。

例子：

```json
{
  "name": "黑衣人",
  "scope": "scene_bound",
  "resolved_to": "慕容复",
  "valid_scene_id": "scene_竹林夜袭_001",
  "appearance_hint": ["铁面具", "青衫", "姑苏口音"],
  "evidence": "黑衣人摘下面罩，竟是慕容复"
}
```

这能防止以后所有黑衣人都被解析成慕容复。

### 5. `specific_instance`

只绑定到某个已经存在的临时 NPC 实例。

适合：

- “那个戴斗笠的人”后来揭示为某人。
- “白衣女子”后来揭示为小龙女。

---

## 证据上下文检索

### 输入

```python
surface_name = "黑衣人"
major_graph = {...}
active_scene = [...]
history_archive = [...]
gm_memory = "..."
```

### 输出

```json
{
  "surface_name": "黑衣人",
  "candidate_mentions": [
    {
      "source": "active_scene",
      "score": 18,
      "text": "黑衣人摘下面罩，竟是慕容复。",
      "evidence_type": "identity_reveal"
    },
    {
      "source": "history_archive",
      "score": 9,
      "text": "那个戴铁面具的黑衣人说话带姑苏口音。",
      "evidence_type": "appearance_hint"
    }
  ],
  "known_alias_hits": [
    {
      "graph_key": "慕容复",
      "alias": "黑衣人",
      "scope": "scene_bound",
      "confidence": 0.95
    }
  ]
}
```

### 检索来源

1. `active_scene`：最近对话与当前幕。
2. `history_archive`：历史归档或摘要。
3. `major_graph.entities`：已有 NPC 的 `desc`、`identity.aliases`、`1_relational_facts`、`update_log`。
4. `gm_memory`：世界观与长期记忆。
5. `pending_references`：之前未解析的代称。

---

## 句段评分规则

不需要第一版就使用向量检索，先用确定性评分即可。

| 特征 | 分数 |
|---|---:|
| 精确包含 `surface_name` | +5 |
| 命中已有 alias | +5 |
| 同句出现真实名和代称 | +8 |
| 出现身份揭示词：其实是、原来是、正是、真名、本名、化名、摘下面罩 | +10 |
| 出现场景局部特征：黑衣、蒙面、斗笠、铁面具、口音 | +3 |
| 来自最近 5 段 active_scene | +3 |
| 来自 history_archive | +1 |
| 只出现泛称，无身份证据 | +0 |

只把高分句段放进证据包，避免把全部历史喂给 LLM。

---

## 身份解析结果

`resolve_npc_reference()` 返回四类结果。

### 1. resolved

解析到已有 NPC。

```json
{
  "status": "resolved",
  "target_graph_key": "伏地魔",
  "npc_id": "npc_voldemort_001",
  "alias_type": "taboo_alias",
  "alias_scope": "global_alias",
  "confidence": 0.95,
  "reason": "神秘人 命中伏地魔的全局禁忌称呼"
}
```

### 2. pending

像人物，但无法确认指向。

```json
{
  "status": "pending",
  "surface_name": "那个人",
  "should_initialize_npc": false,
  "reason": "缺少足够证据确认身份"
}
```

### 3. new_npc_allowed

确认当前场景实际出现的新 NPC。

```json
{
  "status": "new_npc_allowed",
  "canonical_graph_key": "山贼#2",
  "reason": "另一个山贼从树后跳出并攻击玩家"
}
```

### 4. non_character

不是角色，不允许初始化。

```json
{
  "status": "non_character",
  "surface_name": "墙上的火把",
  "should_initialize_npc": false,
  "reason": "该实体是物品或场景结构"
}
```

---

## 初始化 gate

`should_initialize_npc()` 必须遵守：

### 允许初始化

- 当前场景实际登场。
- 发起动作或承受动作。
- 被玩家直接交互，且前情支持其存在。
- `resolution.status == "new_npc_allowed"`。

### 禁止初始化

- `resolution.status == "pending"`。
- `resolution.status == "resolved"`，因为应更新已有 NPC。
- 物品、地形、组织、概念。
- 代称、尊称、蔑称、称号在无证据时。
- 回忆、传闻、假设、比喻中的人物。

---

## 乔峰 / 萧峰改名规则

### 默认行为

如果出现：

```text
萧峰走入酒楼。
```

且证据显示 `萧峰` 是 `乔峰` 的本名，则：

```json
{
  "status": "resolved",
  "target_graph_key": "乔峰",
  "display_name_action": "keep_current",
  "alias_to_add": {
    "name": "萧峰",
    "type": "origin_name",
    "scope": "global_alias"
  }
}
```

不改 `entities` key。

### 允许更新 display_name 的强证据

只有出现类似：

- 从此改名
- 不再使用旧名
- 以萧峰之名行走天下
- 正式恢复本名
- 他自称萧峰，不再承认乔峰之名

才允许：

```json
"display_name_action": "update_to_alias"
```

仍然不改 graph key。

---

## 伏地魔 / 神秘人规则

如果已有 NPC `伏地魔` 的 aliases 包含：

```json
{
  "name": "神秘人",
  "scope": "global_alias",
  "type": "taboo_alias"
}
```

输入：

```text
神秘人要来了。
```

必须解析到 `伏地魔`，不得初始化 `神秘人`。

如果没有已有 NPC，也没有世界观证据，则创建：

```json
"pending_references": [
  {
    "surface_name": "神秘人",
    "referent_type": "character",
    "status": "unresolved",
    "should_initialize_npc": false
  }
]
```

---

## 黑衣人 / 慕容复规则

当出现：

```text
黑衣人摘下面罩，竟是慕容复。
```

只能建立：

```json
{
  "name": "黑衣人",
  "scope": "scene_bound",
  "resolved_to": "慕容复",
  "evidence": "黑衣人摘下面罩，竟是慕容复"
}
```

不得建立全局：

```json
"黑衣人" -> "慕容复"
```

以后如果再次出现：

```text
另一个黑衣人从屋顶跃下。
```

若无相同 scene、appearance_hint 或 evidence，不得解析到慕容复，应创建新的 unresolved scene NPC，如：

```json
"黑衣人#2": {
  "identity": {
    "identity_status": "unresolved",
    "aliases": [
      {
        "name": "黑衣人",
        "scope": "scene_bound"
      }
    ]
  }
}
```

---

## Prompt 辅助协议

意图解析 prompt 与 NPC 初始化 prompt 应加入：

```text
【NPC称呼与身份协议】
当输入中出现代称、尊称、蔑称、头衔、关系称呼或外号（如“神秘人”“那个不能说名字的人”“那个人”“乔帮主”“萧大王”“师父”“黑衣人”）时，不要直接把表面称呼当作长期NPC规范名。若能从前情或世界设定确定其真实指向，应在 canonical_name 中填入已知人物当前主显示名，并在 reason 中说明该称呼是 alias/title/taboo name。若无法确定指向，should_initialize_npc 必须为 false，并标记为 unresolved_reference。

人物曾用名、真名、尊称、蔑称、身份称号不等于必须改名。除非叙事明确说明角色从此改用新名，否则保持原 primary/display name，将其他称呼记录为 aliases。

“黑衣人”“蒙面人”“白衣女子”“那个人”等场景局部称呼默认是 scene_bound 或 specific_instance，不得自动作为 global_alias。
```

---

## 测试要求

新增：

```text
tests/test_npc_lifecycle_identity.py
```

必须覆盖：

1. `神秘人` 或 `那个不能说名字的人` 命中伏地魔 alias，不生成 `神秘人`。
2. 无证据的 `神秘人` 进入 pending，不初始化。
3. `萧峰` 解析到已有 `乔峰`，添加 alias，不改 graph key。
4. 强证据“从此以萧峰之名行走天下”只更新 `display_name`，不改 graph key。
5. `黑衣人摘下面罩，竟是慕容复` 创建 `scene_bound` alias。
6. 后续“另一个黑衣人”不得解析到慕容复。
7. 无上下文的“师父走进来”进入 pending。
8. 已知“方拓的师父=岳不群”时，“师父”解析到岳不群。
9. `墙上的火把`、`少林`、`丐帮` 不初始化为 NPC。

---

## 第一阶段不做

- 不引入完整 `npc_instances` 池。
- 不改 `entities` 主键结构。
- 不删除现有 `init_npc_combat_stats()`。
- 不实现向量检索。
- 不实现复杂多角色 belief system。
- 不做 NPC 主动回合 AI。

---

## 后续过渡路线

### 阶段 1：证据检索 + identity 子结构

- 新增 `sandbox_npc_lifecycle.py`。
- 已有 NPC 补齐 `identity`。
- 初始化前必须调用 `resolve_npc_reference()`。

### 阶段 2：pending reference 回填

- 对无法解析的代称记录 `pending_references`。
- 当后续出现身份揭示时，回填 alias 或合并到已有 NPC。

### 阶段 3：NPC 更新 patch 化

- 门铃同步输出 NPC 更新 patch。
- Python gate 基于 LLM 的结构化 patch、证据字段和权限边界，决定是否写入状态、关系、能力。

### 阶段 4：能力新增 gate

- 只有“领悟/学会/觉醒/突破/获得传承”等强证据才允许新增能力。
- “反击/挥刀/闪避/后退”不得新增能力。

### 阶段 5：完整 NPC 实例化

- 未来再考虑 `npc_instances`。
- `entities` 降级为兼容索引。
- 支持同名多人、伪装身份、多社会身份、玩家知识与事实知识分离。

---

## 成功标准

1. 未解析代称不会直接生成长期 NPC。
2. 多名同人不会分裂成多个实体。
3. 场景局部 alias 不会污染全局身份映射。
4. 乔峰/萧峰问题不会触发 graph key 改名。
5. 身份解析能利用远程上下文证据，而不只依赖最近三段。
6. 所有实现先在沙盒完成，再通过映射脚本同步。
