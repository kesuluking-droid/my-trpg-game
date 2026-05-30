import json
import os
import time
import config
import streamlit as st
from supabase import create_client, Client

# --- 🚀 激活 Supabase 官方直连通道（含自动重连） ---
@st.cache_resource
def _create_supabase_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

def get_supabase_client() -> Client:
    """获取 Supabase 客户端，连接断开时自动重建。"""
    try:
        client = _create_supabase_client()
        # 轻量级心跳检测：执行一个最小查询验证连接存活
        client.table("user_sessions").select("file_name", count="exact").limit(1).execute()
        return client
    except Exception:
        # 连接已死，清除缓存强制重建
        st.cache_resource.clear()
        return _create_supabase_client()

db_client = None  # 延迟初始化，每次调用时获取最新客户端

def _get_db():
    """获取数据库客户端（每次调用时验证连接）。"""
    global db_client
    try:
        db_client = get_supabase_client()
        return db_client
    except Exception as e:
        print(f"[严重错误] Supabase 重连失败: {e}")
        return None

def get_chat_files():
    current_user = st.session_state.get("current_user")
    if not current_user:
        return []
        
    try:
        db = _get_db()
        if not db:
            return []
        res = db.table("user_sessions").select("file_name").eq("username", current_user).order("updated_at", desc=True).execute()
        return [item["file_name"] for item in res.data if item["file_name"] != "major_graph.json"]
    except Exception as e:
        print(f"[严重错误] 获取云端存档列表物理失败。底层原因: {e}")
        return []

def save_session(file_name, memory, history_archive, active_scene, minor_npcs, major_graph, graveyard, director_directive, scene_index, tension_history, current_location, mechanics_log, sync_log, gm_memory, world_tier, pc_name):
    if not file_name:
        return
        
    current_user = st.session_state.get("current_user")
    if not current_user:
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
        "tension_history": tension_history,
        "current_location": current_location,
        "mechanics_log": mechanics_log,
        "sync_log": sync_log,
        "world_tier": world_tier,
        "pc_name": pc_name
    }
    
    try:
        db = _get_db()
        if not db:
            return
        db.table("user_sessions").upsert({
            "username": current_user,
            "file_name": file_name,
            "session_data": data,
            "gm_data": gm_memory,
            "updated_at": "now()"
        }, on_conflict="username, file_name").execute()
    except Exception as e:
        print(f"[警告] 存档 {file_name} 同步云端失败。错误信息: {e}")

def load_session(file_name):
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
    
    default_return = ("", [], [], default_minor, default_major, default_graveyard, "", 1, [], "未知区域", [], [], [], "", "")

    current_user = st.session_state.get("current_user")
    if not current_user:
        return default_return
        
    try:
        db = _get_db()
        if not db:
            return default_return
        res = db.table("user_sessions").select("session_data", "gm_data").eq("username", current_user).eq("file_name", file_name).execute()
        
        if not res.data:
            return default_return
            
        # 🟢 健壮性增强：提取时若整个字段由于网络断流存成了 None，物理强制回退到标准字典，防止抛出 AttributeError
        raw_data = res.data[0].get("session_data")
        data = raw_data if isinstance(raw_data, dict) else {}
        
        raw_gm = res.data[0].get("gm_data")
        gm_memory = raw_gm if isinstance(raw_gm, list) else []
                
        # 🟢 终极防御：在 get 层面强制校验返回类型，严禁释放 None 溢出到前端导致 .append() 闪退
        return (
            data.get("memory") or "", 
            data.get("history_archive") if isinstance(data.get("history_archive"), list) else [],
            data.get("active_scene") if isinstance(data.get("active_scene"), list) else [],
            data.get("minor_npcs") if isinstance(data.get("minor_npcs"), dict) else default_minor,
            data.get("major_graph") if isinstance(data.get("major_graph"), dict) else default_major,
            data.get("graveyard") if isinstance(data.get("graveyard"), dict) else default_graveyard,
            data.get("director_directive") or "",
            int(data.get("scene_index")) if data.get("scene_index") is not None else 1,
            data.get("tension_history") if isinstance(data.get("tension_history"), list) else [], 
            data.get("current_location") or "未知区域",
            data.get("mechanics_log") if isinstance(data.get("mechanics_log"), list) else [], 
            data.get("sync_log") if isinstance(data.get("sync_log"), list) else [], 
            gm_memory, 
            data.get("world_tier") or "近未来都市异能 / 中低武阶段",
            data.get("pc_name") or "主角"
        )
        
    except Exception as e:
        print(f"[警告] 存档 {file_name} 云端读取严重崩溃，已执行物理降级防护。错误信息: {e}")
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