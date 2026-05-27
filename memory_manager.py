import json
import os
from config import HISTORY_DIR

os.makedirs(HISTORY_DIR, exist_ok=True)

GM_HISTORY_DIR = os.path.join(HISTORY_DIR, "gm_data")
if not os.path.exists(GM_HISTORY_DIR):
    os.makedirs(GM_HISTORY_DIR)

def get_chat_files():
    return sorted([f for f in os.listdir(HISTORY_DIR) if f.endswith(".json")], reverse=True)

def save_session(file_name, memory, history_archive, active_scene, minor_npcs, major_graph, graveyard, director_directive, scene_index, tension_history, current_location, mechanics_log, sync_log, gm_memory, world_tier, pc_name):
    if not file_name:
        return
    data = {
        "memory": memory,
        "history_archive": history_archive,
        "active_scene": active_scene,
        "minor_npcs": minor_npcs,
        "major_graph": major_graph,
        "graveyard": graveyard,
        "director_directive": director_directive,
        "scene_index": scene_index,
        "tension_history": tension_history,          # 改成列表
        "current_location": current_location,
        "mechanics_log": mechanics_log,
        "sync_log": sync_log,
        "world_tier": world_tier,       # 【新增】
        "pc_name": pc_name
    }
    with open(os.path.join(HISTORY_DIR, file_name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        
    gm_file = file_name.replace(".json", "_gm.json")
    with open(os.path.join(GM_HISTORY_DIR, gm_file), "w", encoding="utf-8") as f:
        json.dump(gm_memory, f, ensure_ascii=False, indent=4)

def load_session(file_name):
    import os, json
    # (假设你的 HISTORY_DIR 已经在文件顶部定义)
    file_path = os.path.join(HISTORY_DIR, file_name)
    
    default_minor = {}
    default_major = {
        "entities": {
            "主角": {
                "desc": "世界的变数",
                "tags": ["玩家"],
                "1_relational_facts": {},
                "2_dynamic_status": {
                    "physical": {"desc": "健康", "multiplier": 1.0},
                    "mental": {"desc": "平静", "multiplier": 1.0}
                },
                "3_capabilities": {},
                "4_experience_factors": {"general_combat": 1.0, "specific_match": {}},
                "5_traits": [],
                "6_inventory": {}
            }
        }, 
        "relations": []
    }
    default_graveyard = {}
    
    # 统一定义一个发生错误或找不到文件时的保底全量返回值 (共 13 个参数，包含最后新增的三个日志)
    default_return = ("", [], [], default_minor, default_major, default_graveyard, "", 1, [], "未知区域", [], [], [],"","")

    if not os.path.exists(file_path):
        return default_return
        
    try:
        # 1. 读取主线剧情与状态存档
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        # 2. 读取伴生裁判系统存档 (Twin Session - GM Memory)
        gm_memory = []
        gm_file = file_name.replace(".json", "_gm.json")
        gm_path = os.path.join(GM_HISTORY_DIR, gm_file)
        if os.path.exists(gm_path):
            with open(gm_path, "r", encoding="utf-8") as gm_f:
                gm_memory = json.load(gm_f)
                
        return (
            data.get("memory", ""), 
            data.get("history_archive", []),
            data.get("active_scene", []),
            data.get("minor_npcs", default_minor),
            data.get("major_graph", default_major),
            data.get("graveyard", default_graveyard),
            data.get("director_directive", ""),
            data.get("scene_index", 1),
            data.get("tension_history", []),         # 改成列表
            data.get("current_location", "未知区域"),
            data.get("mechanics_log", []),           # 黑匣子检定日志
            data.get("sync_log", []),                # 状态变动落盘日志
            gm_memory,                                # 【新增】：伴生裁判长线记忆
            data.get("world_tier", "近未来都市异能 / 中低武阶段"), # 【新增】：兜底默认世界
            data.get("pc_name", "主角")
        )
        
    except Exception as e:
        # 捕获 JSONDecodeError 或其他各种读取异常，防止硬核闪退
        print(f"[警告] 存档 {file_name} 读取失败，已降级为初始状态。错误信息: {e}")
        return default_return
    
def process_npc_updates(extracted_data, minor_npcs, major_graph, graveyard, scene_index):
    PROMOTE_THRESHOLD = 10 
    # 提取全局地点，默认为未知区域
    location = extracted_data.get("current_location", "未知区域")
    npc_updates_list = extracted_data.get("npc_updates", [])
    relation_updates = extracted_data.get("relation_updates", [])
    
    # 1. 结算节点 (Nodes)
    for update in npc_updates_list:
        name = update.get("name")
        if not name:
            continue
            
        change = update.get("score_change", 0)
        is_dead = update.get("is_dead", False)
        tags = update.get("tags", [])
        new_facts = update.get("new_relational_facts", {}) # 提取羁绊事实
        
        # 构建当前幕的时空锚点切片
        latest_event = update.get("latest_event", "无特定交互")
        attitude = update.get("attitude", "中立")
        event_slice = f"[第{scene_index}幕|{location}|{attitude}] {latest_event}"
        
        if is_dead:
            graveyard[name] = {"cause_of_death": f"在第{scene_index}幕死亡：{latest_event}"}
            minor_npcs.pop(name, None)
            major_graph["entities"].pop(name, None)
            # 过滤掉与死者相关的边
            major_graph["relations"] = [r for r in major_graph["relations"] if r["source"] != name and r["target"] != name]
            continue

        # ==========================================
        # 分支 A: 处理已存在于六维大图谱的核心实体 (严密防篡改版)
        # ==========================================
        if name in major_graph["entities"]:
            node = major_graph["entities"][name]
            
            # 1. 安全追加剧情动态，避免丢失原设定
            if latest_event and latest_event not in node.get("desc", ""):
                node["desc"] = node.get("desc", "无基础设定") + f" | [幕间动态]: {latest_event}"
                
            # 2. 标签并集去重
            node["tags"] = list(set(node.get("tags", []) + tags))
            
            # 3. 追加时空轨迹
            if "trajectory" not in node:
                node["trajectory"] = []
            node["trajectory"].append(event_slice)
            
            # 4. 【六维注入防篡改】：融合羁绊事实（1_relational_facts）
            if new_facts:
                if "1_relational_facts" not in node:
                    node["1_relational_facts"] = {}
                for target, fact in new_facts.items():
                    existing_rel = node.get("1_relational_facts", {}).get(target)
                    
                    # 核心修复：如果该羁绊已经是战后算子生成的精密乘数对象（字典），绝对不覆盖！
                    if isinstance(existing_rel, dict):
                        if "features" not in existing_rel:
                            existing_rel["features"] = []
                        if fact not in existing_rel["features"]:
                            existing_rel["features"].append(fact)
                    else:
                        # 只有当它是普通文本时，才进行常规记录
                        node["1_relational_facts"][target] = fact
            continue

        # ==========================================
        # 分支 B: 处理未入战的边缘次要NPC (保留你的原逻辑)
        # ==========================================
        if name in minor_npcs:
            minor_npcs[name]["score"] += change
            # 追加时空轨迹
            if "trajectory" not in minor_npcs[name]:
                minor_npcs[name]["trajectory"] = []
            minor_npcs[name]["trajectory"].append(event_slice)
        else:
            # 【修复1：无门槛录入】无论敌(负数)、友(正数)、中立(0)，只要大模型提取了，就录入潜伏池
            brief = update.get("base_desc", update.get("brief_desc", "近期登场的新角色"))
            minor_npcs[name] = {
                "score": change, 
                "desc": brief, 
                "tags": tags,
                "trajectory": [event_slice]
            }

        # 【修复2：绝对值晋升】不管是挚友(>=10)还是死敌(<=-10)，只要绝对值达标，就晋升核心图谱
        if name in minor_npcs and abs(minor_npcs[name]["score"]) >= PROMOTE_THRESHOLD:
            # 【六维注入】：晋升时，将轨迹带入核心图谱，并强制初始化完整的六维字典
            major_graph["entities"][name] = {
                "desc": minor_npcs[name].get("desc", ""),
                "tags": minor_npcs[name].get("tags", []),
                "trajectory": minor_npcs[name].get("trajectory", []),
                "1_relational_facts": {},
                "2_dynamic_status": {
                    "physical": {"desc": "正常", "multiplier": 1.0},
                    "mental": {"desc": "正常", "multiplier": 1.0}
                },
                "3_capabilities": {},
                "4_experience_factors": {"general_combat": 1.0, "specific_match": {}},
                "5_traits": [],
                "6_inventory": {}
            }
            del minor_npcs[name]

    # 2. 结算边 (Edges - 完全保留你的连线逻辑)
    for rel in relation_updates:
        src = rel.get("source")
        tgt = rel.get("target")
        change = rel.get("score_change", 0)
        desc = rel.get("desc", "")
        
        # 仅当双方至少有一方是核心人物（或主角）时，才记录关系边，避免边缘NPC制造垃圾连线
        if src in major_graph["entities"] or tgt in major_graph["entities"] or src == "主角" or tgt == "主角":
            found = False
            for existing_rel in major_graph["relations"]:
                # 有向边匹配覆盖
                if existing_rel["source"] == src and existing_rel["target"] == tgt:
                    existing_rel["score"] = existing_rel.get("score", 0) + change
                    existing_rel["desc"] = desc # 用最新的复杂描述覆盖旧描述
                    found = True
                    break
    return minor_npcs, major_graph, graveyard