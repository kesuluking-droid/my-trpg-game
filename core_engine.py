import os
import time
import re
import json
from openai import OpenAI
from config import MODEL_PRO, MODEL_FLASH, API_BASE_URL, DEBUG_MODE
import config
import random
import streamlit as st
from supabase import create_client, Client

@st.cache_resource
def get_supabase_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

db_client = get_supabase_client()

# ==========================================
# 🛑 云端自动基建算子 (无中生有版)
# ==========================================
# 1. 绝对路径提取，防止云端环境路径解析出 None 导致 AttributeError

# --- 账号与权限管理算子 ---
def register_user(username, password, security_question, security_answer):
    username = username.strip()
    password = password.strip()
    if not username or not password or not security_question or not security_answer:
        return False, "所有字段均不能为空。"
    try:
        db_client.table("users_auth").insert({
            "username": username, "password": password, 
            "security_question": security_question, "security_answer": security_answer
        }).execute()
        return True, "注册成功！"
    except Exception as e:
        if "duplicate key" in str(e):
            return False, "该用户名已被注册，请更换。"
        return False, f"注册失败: {str(e)}"

def login_user(username, password):
    username = username.strip()
    password = password.strip()
    try:
        res = db_client.table("users_auth").select("*").eq("username", username).execute()
        if res.data and res.data[0]["password"] == password:
            return True, "登录成功"
        return False, "用户名或密码错误"
    except Exception:
        return False, "登录验证失败，请检查数据库连接。"

def get_security_question(username):
    try:
        res = db_client.table("users_auth").select("security_question").eq("username", username.strip()).execute()
        return res.data[0]["security_question"] if res.data else None
    except Exception:
        return None

def retrieve_password(username, answer):
    try:
        res = db_client.table("users_auth").select("password", "security_answer").eq("username", username.strip()).execute()
        if res.data and res.data[0]["security_answer"] == answer.strip():
            return True, res.data[0]["password"]
        return False, "密保答案错误。"
    except Exception:
        return False, "数据查询失败。"

def modify_password(username, old_password, new_password):
    if not login_user(username, old_password)[0]:
        return False, "旧密码错误。"
    try:
        db_client.table("users_auth").update({"password": new_password.strip()}).eq("username", username.strip()).execute()
        return True, "密码修改成功。"
    except Exception as e:
        return False, f"修改失败: {str(e)}"


# ======== 全局宏观战力锚定设置 ============
def _match_world_anchor_references(new_setting_name: str, threshold: float = 0.75, top_n: int = 10, per_category_top_n: int = 3):
    """
    从全部已登记世界观中检索与玩家具体世界观最相近的参考样本。
    返回: (best_category, selected_rows, debug_msg)
    """
    try:
        from ability_matcher import compute_similarity
    except Exception as e:
        return None, [], f"语义匹配模块不可用：{e}"

    try:
        res = db_client.table("world_anchors_pool").select("category, setting_name, anchor_data").execute()
        rows = res.data or []
    except Exception as e:
        return None, [], f"世界观样本库读取失败：{e}"

    scored = []
    for row in rows:
        setting_name = str(row.get("setting_name", "")).strip()
        category = str(row.get("category", "")).strip()
        anchor_data = row.get("anchor_data", {}) or {}
        if not setting_name or not category:
            continue

        # 既看具体世界名，也看锚点描述，避免只靠标题导致误判。
        anchor_text = json.dumps(anchor_data, ensure_ascii=False)
        candidate_text = f"{category} / {setting_name}\n{anchor_text}"
        score = compute_similarity(new_setting_name, candidate_text)
        if score > threshold:
            scored.append({
                "category": category,
                "setting_name": setting_name,
                "anchor_data": anchor_data,
                "score": score,
            })

    if not scored:
        return None, [], f"没有找到相似度超过 {threshold:.2f} 的世界观参考。"

    top_matches = sorted(scored, key=lambda item: item["score"], reverse=True)[:top_n]

    category_scores = {}
    for item in top_matches:
        category_scores.setdefault(item["category"], []).append(item["score"])

    best_category = max(
        category_scores.items(),
        key=lambda kv: (sum(kv[1]) / len(kv[1]), len(kv[1]))
    )[0]

    selected_rows = [item for item in top_matches if item["category"] == best_category][:per_category_top_n]
    avg_score = sum(category_scores[best_category]) / len(category_scores[best_category])
    debug_msg = f"匹配大类：{best_category}，均值相似度 {avg_score:.3f}，参考样本 {len(selected_rows)} 个。"
    return best_category, selected_rows, debug_msg


def sync_world_anchor_and_scale(category: str, new_setting_name: str, old_setting_name: str = None, major_graph: dict = None):
    """
    【世界法则枢纽】：负责查表、创世建表、以及跨界资产缩放。
    返回值: (bool_success, anchor_data_dict, updated_major_graph, msg)
    """
    category = category.strip()
    new_setting_name = new_setting_name.strip()
    
    # 1. 第一道防线：精确索引检索 (命中则直接复用，不调用大模型)
    try:
        existing_res = db_client.table("world_anchors_pool").select("anchor_data").eq("category", category).eq("setting_name", new_setting_name).execute()
        if existing_res.data:
            print(f"[世界引擎] 命中精确缓存，直接载入世界观：{new_setting_name}")
            return True, existing_res.data[0]["anchor_data"], major_graph, "从时空长河中直接唤醒了该世界法则。"
    except Exception as e:
        print(f"[世界引擎警告] 数据库查询失败: {e}")

    # 2. 未命中：触发【创世建表】协议
    print(f"[世界引擎] 未知世界，触发大模型创世建表协议...")
    
    # 2.1 全库语义匹配：自动推断最相近大类，并抽取该大类 Top3 参考样本
    ref_texts = []
    match_msg = ""
    try:
        matched_category, matched_refs, match_msg = _match_world_anchor_references(new_setting_name)
        if matched_category:
            category = matched_category
            if "st" in globals():
                st.session_state.world_category = matched_category
        ref_texts = [
            f"参考世界[{r['setting_name']}]（相似度 {r['score']:.3f}，大类 {r['category']}）:\n{json.dumps(r['anchor_data'], ensure_ascii=False)}"
            for r in matched_refs
        ]
    except Exception as e:
        match_msg = f"语义匹配失败，回退到常识生成：{e}"
    references_str = "\n\n".join(ref_texts) if ref_texts else "暂无高相似参考，请根据常识与大类基调自由发挥。"

    # 如果语义匹配切换了大类，而该大类下已有精确缓存，则直接复用，避免重复建表。
    try:
        rematch_existing = db_client.table("world_anchors_pool").select("anchor_data").eq("category", category).eq("setting_name", new_setting_name).execute()
        if rematch_existing.data:
            print(f"[世界引擎] 语义匹配后命中精确缓存：{category} / {new_setting_name}")
            return True, rematch_existing.data[0]["anchor_data"], major_graph, f"已自动匹配大类【{category}】，并从缓存载入世界法则。"
    except Exception:
        pass

    # 获取旧世界法则 (用于计算跨界折算系数)
    old_anchor_text = "无旧世界参考（视为从零开局）"
    if old_setting_name and old_setting_name != new_setting_name:
        try:
            old_res = db_client.table("world_anchors_pool").select("anchor_data").eq("setting_name", old_setting_name).execute()
            if old_res.data:
                old_anchor_text = json.dumps(old_res.data[0]["anchor_data"], ensure_ascii=False)
        except Exception:
            pass
    

    # 3. 大模型创世提示词
    system_prompt = f"""你是一个 TRPG 的宇宙法则架构师。
玩家进入了一个全新的【{category}】大类世界。
新世界具体设定：【{new_setting_name}】

【相似世界观参考样本库】（由全库语义匹配筛选，仅供战力尺度参考，需结合新设定重新定调）：
匹配说明：{match_msg}
{references_str}

【跨界战力折算系统】
该玩家上一个经历的世界法则为：
{old_anchor_text}

【你的任务】
1. 为新世界构建一份 5 级梯度的“威力与破坏力量化基准表”。
2. 对比新旧世界法则，生成一个跨界折算系数 `conversion_ratio`。
   - 如果是从【低武世界】穿越到【高武/修仙世界】（例如凡人武侠进入洪荒宇宙），旧战力会被世界法则压缩，系数应为 0.1 到 0.5。
   - 如果是从【高武世界】降维打击到【低武世界】，系数应为 2.0 到 10.0。
   - 如果力量体系平级，或者没有旧世界数据，系数固定填 1.0。
3. 不改变最低阈值1，最高阈值120+这两个总体波动阈值，中间允许微调。
必须返回纯 JSON 格式：
{{
    "conversion_ratio": 1.0,
    "anchor_data": {{
        "level_5_disaster": "Base 80-120+ (灾变级): 具体表现描述...",
        "level_4_fatal": "Base 40-79 (致命级): 具体表现描述...",
        "level_3_high_risk": "Base 25-39 (高危级): 具体表现描述...",
        "level_2_standard": "Base 12-24 (标准级): 具体表现描述...",
        "level_1_daily": "Base 1-11 (微弱级): 具体表现描述..."
    }}
}}"""

    client = get_user_client()
    if not client:
        return False, None, major_graph, "未配置 API Key，创世失败。"

    try:
        response = client.chat.completions.create(
            model=MODEL_FLASH, # 建表用 FLASH 足够快
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0.4,
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        new_anchor = result.get("anchor_data", {})
        ratio = float(result.get("conversion_ratio", 1.0))

        # 4. 落盘保存新世界法则
        try:
            db_client.table("world_anchors_pool").insert({
                "category": category,
                "setting_name": new_setting_name,
                "anchor_data": new_anchor
            }).execute()
        except Exception as e:
            print(f"[世界引擎警告] 新表录入数据库失败: {e}")

        # 5. 执行跨界资产缩放 (核心物理隔离：绝对不碰经验和羁绊)
        if ratio != 1.0 and major_graph:
            major_graph = _apply_cross_world_scaling(major_graph, ratio)
            msg = f"创世成功！检测到跨界跃迁，已执行法则压制/增幅，全图谱战力乘数：x{ratio:.2f}"
        else:
            msg = "全新世界法则录入成功，当前世界体系稳定。"

        return True, new_anchor, major_graph, msg

    except Exception as e:
        print(f"[世界引擎报错] 创世崩溃: {e}")
        return False, None, major_graph, "大模型法则推演失败，请点击重置战力表按钮重试。"

def get_current_world_anchor_text(category, setting_name):
    """轻量级读取：战斗检定时秒查字典，查不到抛出兜底文本"""
    try:
        res = db_client.table("world_anchors_pool").select("anchor_data").eq("category", category).eq("setting_name", setting_name).execute()
        if res.data:
            anchor = res.data[0]["anchor_data"]
            # 展平为字符串喂给大模型
            return f"【当前世界法则】\n{chr(10).join(anchor.values())}"
    except:
        pass
    return "【当前世界法则未初始化，按常规标准执行判定】"

# ======== 全局宏观战力锚定设置 ============


def _apply_cross_world_scaling(major_graph, ratio):
    """
    局部辅助算子：按照跨界折算系数，对图谱内所有会波动的战力硬指标进行等比例重塑。
    绝对安全阀：严禁动摇 4_experience_factors 和 1_relational_facts。
    """
    ratio = max(0.01, min(ratio, 100.0)) # 限制缩放极值，防止溢出
    
    for entity_name, entity_data in major_graph.get("entities", {}).items():
        # 1. 缩放功法基础威力 (3_capabilities -> base_power)
        caps = entity_data.get("3_capabilities", {})
        for cap_name, cap_data in caps.items():
            if "base_power" in cap_data:
                old_base = cap_data["base_power"]
                # 威力保底为 1
                cap_data["base_power"] = max(1, int(old_base * ratio))

        # 2. 缩放背包物品乘数 (6_inventory -> multiplier)
        invs = entity_data.get("6_inventory", {})
        for inv_name, inv_data in invs.items():
            if isinstance(inv_data, dict) and "multiplier" in inv_data:
                old_mult = inv_data["multiplier"]
                # 物品乘数最小 0.1
                inv_data["multiplier"] = round(max(0.1, old_mult * ratio), 2)
                
        # 3. 缩放特质乘数 (5_traits -> multiplier)
        traits = entity_data.get("5_traits", [])
        for trait in traits:
            if isinstance(trait, dict) and "multiplier" in trait:
                old_mult = trait["multiplier"]
                trait["multiplier"] = round(max(0.1, old_mult * ratio), 2)
                
    return major_graph


def get_user_client():
    import streamlit as st
    key = st.session_state.get("user_api_key", "")
    if not key or not key.startswith("sk-"):
        return None
    return OpenAI(api_key=key, base_url=API_BASE_URL)


def detect_action_intent(user_input, active_scene, pc_name, major_graph):
    """
    意图拦截器：判断玩家输入是否触发机制检定（带上下文与实体资产智能雷达扫描版）。
    """
    # 1. 调用最近3幕对话上下文
    recent_context = "\n".join([f"{m['role']}: {m['content']}" for m in active_scene[-3:]]) if active_scene else "无"
    
    # 2. 🟢 智能雷达扫描：避免全量提取导致 Token 暴涨与识别幻觉，仅圈定涉事角色
    full_radar_text = f"{user_input}\n{recent_context}"
    entities_to_check = [pc_name]  # 主角作为玩家化身，必须常驻检索池
    
    for name in major_graph.get("entities", {}).keys():
        if name == pc_name:
            continue
        # 只要该 NPC 名字在玩家当前输入或最近 3 幕历史对话中被提及过，就拉入快照名单
        if name in full_radar_text:
            entities_to_check.append(name)

    # 3. 🟢 定向提取：仅从动态图谱中提取被雷达锁定实体的资产快照，供大模型精准比对
    entities_snapshot = ""
    for name in entities_to_check:
        data = major_graph.get("entities", {}).get(name)
        if not data:
            continue
        caps = ", ".join(data.get("3_capabilities", {}).keys()) or "无"
        
        # 🟢 修正点：将特质的名字和它的作用领域拼在一起，给大模型提供完整的语义标签
        traits_list = []
        for t in data.get("5_traits", []):
            if isinstance(t, dict):
                domains_str = "/".join(t.get("target_domains", []))
                traits_list.append(f"{t.get('name')}(领域:{domains_str})")
        traits = ", ".join(traits_list) or "无"
        
        inv = ", ".join(data.get("6_inventory", {}).keys()) or "无"
        entities_snapshot += f"【实体名: {name}】\n- 备选能力: [{caps}]\n- 先天特质: [{traits}]\n- 背包物品: [{inv}]\n\n"

    system_prompt = f"""你是一个跑团系统（TRPG）的冷酷规则裁判。
请判断最新剧情中是否发生了一次“具有挑战性的机制动作”或“突发灾难/不可抗力豁免”。

【核心判决法则】
1. 闲聊、普通的观察、顺从的互动 -> 非机制动作 (is_action: false)
2. 攻击、使用特定能力、试图偷窃、欺骗、遭遇天灾轰炸、强行突围 -> 机制动作 (is_action: true)

【双端实体识别最高协议】
首先判断是"{pc_name}"的主动行为还是被动应对。进入下列分支：
- 主动行为："{pc_name}"主动对某物发难。
此时，"{pc_name}"是发起方！
必须填：
  initiator_entity = "{pc_name}"，
  detected_ability = "对应人物的技能/招式/天赋"（例如 "水下呼吸"、""），
  target_entity = "核心威胁/灾难/天灾的具体名称"，
  target_ongoing_action = "核心威胁/灾难的核心特征或类型"。
- 被动应对："{pc_name}"被动应对突发灾难、天灾、大范围不可抗力波及或加害角色的攻击。
  此时，【核心威胁/灾难源头】才是真正的发起方！
  必须填：
    initiator_entity = "核心威胁/灾难/天灾的具体名称"（例如 "核弹爆炸"），
    detected_ability = "核心威胁/灾难的核心特征或类型"（例如 "核弹爆炸冲击波"、"洪水冲击"），
    target_entity = "{pc_name}"，
    target_ongoing_action = "应对方用来应对或躲避的招式/动作"。
- 绝对严禁把“掩体”、“大树”、“水下”、“墙壁”等应对方用来躲避的媒介误识别为对抗方实体！

【资产扫描匹配协议】
当 is_action 为 true 时，请仔细阅读【当前世界实体面板快照】，智能扫描玩家的最新输入与上下文，找出双方在动作中实际动用、触发、或关联的所有资产。
- 必须精确提取快照中所列出的原名称，严禁凭空编造、缩写或改写。
- 发起方关联的能力、特质或背包物品的原名称，填入 initiator_matched_assets 数组。
- 对抗方（受害方）关联的能力、特质或背包物品的原名称，填入 target_matched_assets 数组。
- 若无匹配资产，或属于纯环境天灾，则对应数组保持为空列表 []。

【当前世界实体面板快照】
{entities_snapshot}

返回纯JSON格式：
{{
    "is_action": true/false,
    "action_category": "combat/social/stealth/skill/none",
    "initiator_entity": "发起方实体名",
    "detected_ability": "发起方使用的具体能力或灾难特征（如无填 null）",
    "target_entity": "目标或受害者实体名",
    "target_ongoing_action": "受害者即时应对动作名（如无填 null）",
    "initiator_matched_assets": ["匹配到的原能力名", "匹配到的原物品名", "匹配到的原特质名"],
    "target_matched_assets": ["匹配到的原能力名", "匹配到的原物品名", "匹配到的原特质名"]
}}
"""

    user_prompt = f"""【前情提要（最近3幕对话）】
{recent_context}

【玩家最新输入】
“{user_input}”
"""
    client = get_user_client()
    if not client:
        return {
            "is_action": False, 
            "action_category": "none", 
            "initiator_entity": pc_name, 
            "detected_ability": None, 
            "target_entity": None,
            "initiator_matched_assets": [],
            "target_matched_assets": []
        }
    
    try:
        response = client.chat.completions.create(
            model=MODEL_FLASH, 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"} 
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {
            "is_action": False, 
            "action_category": "none", 
            "initiator_entity": pc_name, 
            "detected_ability": None, 
            "target_entity": None,
            "initiator_matched_assets": [],
            "target_matched_assets": []
        }

def build_context(memory, active_stage_names, latest_input, major_graph, minor_npcs, director_directive):
    """双轨制上下文组装器（融合时空锚定轨迹与六维实体多乘区架构）"""
    context_text = f"【全局事实记忆】\n{memory}\n\n"

    def format_6d_entity(name, data):
        """局部辅助函数：将角色的六维数据降维解析为文本格式"""
        res = f"- {name} (标签:{data.get('tags', [])})：{data.get('desc', '')}\n"
        
        trajectory_list = data.get("trajectory", [])
        if trajectory_list:
            res += f"  > 近期轨迹：{' -> '.join(trajectory_list[-3:])}\n"
            
        facts = data.get("1_relational_facts", {})
        if facts:
            facts_list = []
            for k, v in facts.items():
                if isinstance(v, dict):
                    domains = v.get("target_domains", [])
                    mult = v.get("multiplier", 1.0)
                    facts_list.append(f"{k}(领域:{','.join(domains)}, 乘区:{mult})")
                else:
                    facts_list.append(f"{k}: {v}")
            res += f"  > 羁绊事实: {', '.join(facts_list)}\n"
            
        status = data.get("2_dynamic_status", {})
        if status:
            phys, ment = status.get("physical", {}), status.get("mental", {})
            res += f"  > 身体状态: {phys.get('desc', '正常')} (乘区: {phys.get('multiplier', 1.0)})\n"
            res += f"  > 心理状态: {ment.get('desc', '正常')} (乘区: {ment.get('multiplier', 1.0)})\n"
            
        caps = data.get("3_capabilities", {})
        if caps:
            caps_str = ", ".join([f"{k}(特性:{','.join(v.get('features', []))})" for k, v in caps.items()])
            res += f"  > 掌握能力: {caps_str}\n"
            
        traits = data.get("5_traits", [])
        if traits:
            traits_list = []
            for t in traits:
                name_val = t.get("name", "")
                domains = t.get("target_domains", [])
                mult = t.get("multiplier", 1.0)
                traits_list.append(f"{name_val}(领域:{','.join(domains)}, 乘区:{mult})")
            res += f"  > 固有特质: {', '.join(traits_list)}\n"
            
        inv = data.get("6_inventory", {})
        if inv:
            inv_list = []
            for k, v in inv.items():
                if isinstance(v, dict):
                    tags = v.get("tags", v.get("target_domains", []))
                    mult = v.get("multiplier", 1.0)
                    inv_list.append(f"{k}(标签:{','.join(tags)}, 乘区:{mult})")
                else:
                    inv_list.append(str(k))
            res += f"  > 携带物品: {', '.join(inv_list)}\n"
            
        return res

    # 1. 轨道一：常驻舞台（强制注入，推演暗线）
    if active_stage_names:
        context_text += "【本幕常驻核心角色】（即便未提及，他们也在此场景中或暗中干预）：\n"
        for name in active_stage_names:
            entity = major_graph.get("entities", {}).get(name)
            if not entity: continue
            
            # 注入六维数据
            context_text += format_6d_entity(name, entity)
            
            # 牵引与该角色相关的关系边
            for rel in major_graph.get("relations", []):
                if rel["source"] == name or rel["target"] == name:
                    context_text += f"  > 关系暗线 [{rel['source']} ↔ {rel['target']}] (当前好感:{rel.get('score', 0)})：{rel.get('desc', '')}\n"

    # 2. 轨道二：异步雷达（关键字触发，按需拉取）
    lazy_load_text = ""
    
    # 扫描未在舞台上的主要人物（触发雷达时拉取其完整六维数据）
    for name, data in major_graph.get("entities", {}).items():
        if name in latest_input and name not in active_stage_names:
            lazy_load_text += format_6d_entity(name, data)
            
    # 扫描次要人物池 (T1)
    for name, data in minor_npcs.items():
        if name in latest_input and name not in active_stage_names:
            trajectory_list = data.get("trajectory", [])
            traj_str = f"\n  > 近期轨迹：{' -> '.join(trajectory_list[-3:])}" if trajectory_list else ""
            lazy_load_text += f"- {name} (次要人物)：{data.get('desc', '')}{traj_str}\n"

    if lazy_load_text:
        context_text += f"\n【触发雷达：临时提及角色情报】\n{lazy_load_text}"
        
    context_text += """

【最高执行协议：视点隔离与暗线潜行】
1. 绝对有限视角：你只能描述主角当前能够“看到、听到、闻到、触碰到”的客观表象。
2. 严禁心理越权：绝对禁止描写任何NPC的内心独白、隐藏动机或主角视线外的暗中行动（严禁出现“其实他心里想…”、“暗地里…”等剧透句式）。
3. 行为映射（Show, Don't Tell）：你已知道舞台上NPC的真实关系与阵营暗线，请将这些暗线转化为实质性的微动作、欺骗性台词、不寻常的巧合或敌对阻碍。让玩家自己去推测，而不是由你来宣告。
4. NPC知道的信息也应该有限，并非全知。
"""
    
    if director_directive:
        context_text += f"\n{director_directive}\n注意：严格遵循行为映射原则，通过客观表象展现该指令，绝不向玩家直接宣告。"
    
    return context_text


def generate_chat_stream(context_text, active_scene, override_tail=None):
    """流式对话生成器（使用 PRO 模型）- 带网络防断流装甲版"""
    if DEBUG_MODE:
        time.sleep(0.5)
        for word in list("【DEBUG模式-PRO】测试回复。"):
            yield word
            time.sleep(0.05)
        return

    # 直接使用组装好的双轨 context_text
    runtime_messages = [{"role": "system", "content": context_text}]
    runtime_messages.extend(active_scene)

    # 【新增】：尾部强注入协议
    tail_instruction = "【最高执行协议】：若本次回复推演导致任何角色身心状态、特质、重要物品发生重大非战斗性转变（身心状态如大喜大悲、心神不宁、顿悟洗心革面等，特质比如吃下宝物导致百毒不侵等、重要物品比如丢失、意外获得利器），必须在回复最末尾独立一行输出 `<STATUS_UPDATE: 角色名>`。若无重大转变，绝对不要输出此标记。"

    # 如果有校验覆盖指令，追加到尾部（最高优先级，紧贴对话内容）
    if override_tail:
        tail_instruction += f"\n{override_tail}"

    runtime_messages.append({"role": "system", "content": tail_instruction})

    # 【新增防御】：第一层 try，捕获初始连接失败或限流报错
    
    client = get_user_client()
    if not client:
        yield "【系统提示】：请先在左侧边栏配置正确的 DeepSeek API Key。"
        return
    
    try:
        response = client.chat.completions.create(
            model=MODEL_PRO, 
            messages=runtime_messages, 
            stream=True
        )
        
        # 【新增防御】：第二层 try，专门防范刚才你遇到的流式传输到一半突然掐断 (RemoteProtocolError)
        try:
            for chunk in response:
                if chunk.choices and hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as stream_e:
            # 捕获断流异常，向网页输出一段提示语句收尾，阻止 Python 抛出红字崩溃
            yield f"\n\n[系统警告：数据流在传输中途断开 ({type(stream_e).__name__})。这通常是由于 API 网络波动引起，当前文本已安全保留，您可以直接继续或重新点击发送。]"
            
    except Exception as e:
        # 捕获创建请求时的崩溃（如余额不足、模型名写错、完全没网）
        yield f"\n\n[系统警告：API 连接建立失败 ({type(e).__name__})。错误详情: {str(e)}]"

def extract_memory_summary(messages, scene_index):
    """幕间信息提取算子（保留原版元数据 + 融合六维数据保护协议 + 正则容错）"""
    if not messages:
        return {"summary": "无有效剧情。", "current_location": "未知", "current_tension": 0, "npc_updates": [], "relation_updates": []}

    chat_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
    
    system_prompt = f"""你是一个智能记忆管理引擎。当前是第 {scene_index} 幕。请执行：
    1. 总结核心要点，评估戏剧张力（0-10），并提取本幕主要【发生地点】。
    2. 抓取所有出场角色，记录其本幕交互。
    3. 生成“幕间推进”：让世界在幕间自然向前推进一小步，并给下一幕留下开场钩子。
    
    【最高指令：六维数据保护与命名协议】
    1. 数值保护：角色的武功、状态、物品等数值已处理完毕。你【绝对不可】在 base_desc 中编造武功数值。
    2. 命名强制规则：如果剧情中出现了没有名字的NPC（如：女军官、大夫、门房），请直接用其【显著特征或职业】作为 name（如："女军官"）。绝对严禁将NPC的名字误填为主角的名字！
    3. 幕间推进只用于叙事推进与下一幕钩子，严禁在其中新增能力、物品、数值变化或确定隐藏真相。NPC幕间动作必须是可观察或可被传闻感知的表层行动。

    返回纯JSON格式：
    {{
        "summary": "...",
        "current_location": "酒馆/密林/未知区域",
        "current_tension": 5,
        "npc_updates": [
            {{
                "name": "姓名或特征称呼", 
                "score_change": 1, // 敌对填-1，中立填0，友善填1
                "is_dead": false, 
                "tags": ["阵营或身份标签"], 
                "base_desc": "基础身份描述", 
                "latest_event": "交谈/战斗/交易的具体行动",
                "attitude": "友善/敌对/中立",
                "new_relational_facts": {{
                    "目标角色名（如主角）": "新增或改变的羁绊事实"
                }}
            }}
        ],
        "relation_updates": [],
        "interlude_progression": {{
            "time_skip": "片刻后/一夜之后/数日后/与此同时",
            "progression": "幕间发生的局势推进，体现时间流逝、后果发酵或阵营动作。",
            "npc_moves": ["已知NPC在幕间采取的可观察行动或传闻"],
            "next_hook": "下一幕开场钩子，让玩家进入下一幕时有明确可响应的事件。",
            "recommended_location": "下一幕推荐地点",
            "tone": "喘息/悬疑/危机/追击/日常"
        }}
    }}"""
    client = get_user_client()
    if not client:
        return {
            "summary": "【系统提示】：未配置正确的 API Key，无法提取摘要。", 
            "current_location": "未知", 
            "current_tension": 0, 
            "npc_updates": [], 
            "relation_updates": [],
            "interlude_progression": {}
        }
    try:
        response = client.chat.completions.create(
            model=MODEL_FLASH,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": chat_text}],
            temperature=0.2
        )
        raw_content = response.choices[0].message.content.strip()
        
        # 使用正则强行剥离可能存在的 ```json 和 ``` 标记
        match = re.search(r'\{.*\}', raw_content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        else:
            return json.loads(raw_content)
            
    except Exception as e:
        # 打印真实报错到控制台，拒绝静默失败
        print(f"\n[引擎警告] 提取幕间摘要失败: {e}")
        if 'raw_content' in locals():
            print(f"[引擎警告] 大模型原始输出: {raw_content}\n")
            
        return {"summary": "提取失败。", "current_location": "未知", "current_tension": 0, "npc_updates": [], "relation_updates": [], "interlude_progression": {}}
def generate_narrative_directive(current_tension, major_graph, manual_targets=None):
    if manual_targets is None:
        manual_targets = []
    
    # 1. 负反馈调节计算下一幕目标张力
    # 采用简易反相逻辑防疲劳：高张力后必接低张力缓冲，低张力后逐步推高
    if current_tension >= 7:
        target_tension = random.randint(1, 4)
    elif current_tension <= 3:
        target_tension = random.randint(5, 8)
    else:
        target_tension = random.randint(4, 9)

    # ---------------- 2. 引入工业级戏剧管理矩阵 (Drama Matrix) ----------------
    drama_matrix = {
        "low": { # 张力 1-4：冷却与铺垫期
            "phase": "缓冲与铺垫 (Relax & Build)",
            "narrative_function": ["提供世界观线索", "建立情感羁绊", "日常资源交易", "展现伪装的平静"],
            "information_control": "透露表层信息，埋下深层悬念。严禁直接暴露冲突。",
            "stakes": "无直接生存威胁，主要涉及个人声誉、小额财产或好感的微调。",
            "emotion_pool": ["信任", "怀旧", "好奇", "慵懒", "隐秘的忧郁"]
        },
        "medium": { # 张力 5-7：发展与危机期
            "phase": "冲突升级 (Complication & Escalation)",
            "narrative_function": ["设置道德困境", "破坏原有计划", "暴露出卖与试探", "资源或情报争夺"],
            "information_control": "制造信息不对称。NPC必须隐瞒关键意图，抛出半真半假的情报。",
            "stakes": "涉及阵营关系破裂、重要物品丢失或轻度物理/精神伤害。",
            "emotion_pool": ["猜忌", "贪婪", "焦虑", "嫉妒", "狂热的试探"]
        },
        "high": { # 张力 8-10：高潮与决算期
            "phase": "高潮与危机 (Climax & Crisis)",
            "narrative_function": ["背叛与决裂", "生死存亡的战斗", "核心秘密的血腥揭露", "绝境中的惨烈牺牲"],
            "information_control": "底牌尽出。所有被隐藏的动机强制曝光，不再有任何伪装。",
            "stakes": "生命危险、核心信仰彻底崩塌、阵营或据点覆灭。",
            "emotion_pool": ["恐惧", "绝望", "复仇", "牺牲的决意", "极度疯狂"]
        }
    }
    
    # 提取对应张力的矩阵切片
    if target_tension <= 4:
        tier = drama_matrix["low"]
    elif target_tension <= 7:
        tier = drama_matrix["medium"]
    else:
        tier = drama_matrix["high"]
        
    primary_emotion, secondary_emotion = random.sample(tier["emotion_pool"], 2)
    selected_function = random.choice(tier["narrative_function"])

    # 3. 实体池采样（排除主角，仅从已有设定的核心NPC中随机抽取）
    if manual_targets:
        available_npcs = [name for name in manual_targets if name != "主角" and name in major_graph.get("entities", {})]
    else:
        available_npcs = [name for name in major_graph.get("entities", {}).keys() if name != "主角"]
    
    if not available_npcs:
        return ""
        
    # ---------------- 【非线性加权选角算法】 ----------------
    npc_affinities = {}
    for rel in major_graph.get("relations", []):
        if rel["source"] == "主角" and rel["target"] in available_npcs:
            npc_affinities[rel["target"]] = rel.get("score", 0)
        elif rel["target"] == "主角" and rel["source"] in available_npcs:
            npc_affinities[rel["source"]] = rel.get("score", 0)
    
    weights = []
    # 记录该 NPC 的真实分数，后续发给大模型做人设防偏离
    chosen_npc_score = 0 
    
    for npc in available_npcs:
        # 1. 约束边界：强行将分数锁定在 -100 到 100 之间，防止后期数值膨胀
        raw_score = npc_affinities.get(npc, 0)
        clamped_score = max(-100, min(100, raw_score)) 
        abs_score = abs(clamped_score)
        
        # 2. 非线性权重计算
        if target_tension >= 7:
            # 高张力：使用指数级放大 (1.5次方)。
            # 效果：50分的宿敌权重高达约350，10个0分路人总权重才50。宿敌出场率碾压群演。
            weight = (abs_score ** 1.5) + 5
        elif target_tension <= 4:
            # 低张力：反向倒数。0分路人权重100，50分熟人权重50，90分死敌权重10。
            weight = max(100 - abs_score, 1)
        else:
            # 中张力：线性过渡，稳步升温。
            weight = abs_score + 10
            
        weights.append(weight)

    chosen_npc = random.choices(available_npcs, weights=weights, k=1)[0]
    chosen_npc_score = npc_affinities.get(chosen_npc, 0) # 提取保留真实带正负号的分数
    # ----------------------------------------------------------------
    npc_desc = major_graph["entities"][chosen_npc].get("desc", "")

    # ---------------- 4. 构建结构化厚重提示词 (Thick Plan Prompt) ----------------
    system_prompt = f"""你是一个高级AI戏剧导演，精通情节起伏与信息控制。
当前任务：为下一幕生成一条单人暗线动作指令。
目标NPC：{chosen_npc} （设定：{npc_desc}）
对主角当前好感度：{chosen_npc_score} （正为友，负为敌，0为中立）

【下一幕戏剧指标】
- 目标张力值：{target_tension}/10 （当前处于：{tier['phase']}）
- 主次情绪基调：{primary_emotion} / {secondary_emotion}
- 核心叙事功能：{selected_function}
- 隐藏与展现法则：{tier['information_control']}
- 涉及的赌注/风险：{tier['stakes']}

规则：
1. 严谨对齐好感度：敌对（负数）要体现加害或算计，友善（正数）要体现庇护或自我牺牲，中立（0附近）体现利益交换或冷眼旁观。
2. 动作优先：将上述所有的情绪、功能、赌注，转化为一个具体的物理动作、一句话或一个微小事件。
3. 只能输出纯粹的一句话指令，绝不能包含任何解释、注音或多余格式。"""
    

    client = get_user_client()
    if not client:
        return ""
    
    try:
        response = client.chat.completions.create(
            model=MODEL_FLASH,
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0.7 # 稍微降低温度以确保逻辑对齐
        )
        directive = response.choices[0].message.content.strip()
        return f"【导演指令：暗线推演】{chosen_npc} 下一幕行动：{directive}"
    except Exception as e:
        return ""

def init_npc_combat_stats(target_name, active_scene, major_graph, world_anchor_text):
    """
    全生命周期NPC初始化与资产补全算子。
    支持从零构建新NPC实体并注册入图谱，或对已有实体的空缺核心矩阵进行动态补全。
    """
    if not target_name or target_name in ["环境", "None", "null"] or not isinstance(target_name, str):
        return major_graph

    if "entities" not in major_graph:
        major_graph["entities"] = {}

    # 判定当前角色的生存状态
    is_new_npc = target_name not in major_graph["entities"]
    npc_data = major_graph["entities"].get(target_name, {})
    has_caps = bool(npc_data.get("3_capabilities"))

    # 如果角色已存在且拥有完整的战斗技能树，直接跳过以维护局内成长资产
    if not is_new_npc and has_caps:
        return major_graph

    recent_context = "\n".join([f"{m['role']}: {m['content']}" for m in active_scene[-3:]]) if active_scene else "无"
    existing_desc = npc_data.get("desc", "暂无历史设定，属于剧情首次登场的全新人物。请根据上下文合理推断设定。")
    existing_tags = npc_data.get("tags", ["NPC"])

    # 提取已知角色名列表（用于关系推断）
    known_entities = list(major_graph.get("entities", {}).keys())
    known_entities_str = "、".join(known_entities) if known_entities else "无"

    # 判断是否是玩家主角：主角严格约束，NPC 自由揣测
    is_player = (target_name in known_entities and "玩家" in major_graph["entities"].get(target_name, {}).get("tags", []))
    if is_player:
        capability_constraint = (
            "- 【严格约束 - 玩家主角】3_capabilities 中只允许填入近期剧情上下文中该角色**实际使用或被提及**的能力/招式。"
            "严禁凭空编造剧情中从未出现过的技能。如果上下文中没有描述任何具体招式，只填写一个「基础应对」作为兜底。"
        )
    else:
        capability_constraint = (
            "- 【NPC 自由揣测】根据该角色的身份、名望和世界观基调，合理推断其可能掌握的全部技能树。"
            "NPC 作为独立存在的个体，应当拥有与其身份匹配的完整能力配置。"
        )

    system_prompt = f"""你是一个 TRPG 的动态实体生成与资产补全引擎 (Game Master)。
【当前宇宙法则与威力比例尺】
{world_anchor_text}

【目标实体情报】
姓名：{target_name}
基础已知设定：{existing_desc}
基础身份标签：{existing_tags}

【已存在的角色】
{known_entities_str}

【近期剧情上下文】
{recent_context}

【任务协议】
请根据该角色在剧情和世界观中的实际生态位与名望，推导其合理的背景描述、身份标签、掌握功法/能力以及当前的身心状态。
- 能力基础物理威力 (base_power) 必须严格对照基准：市井凡人/流氓 (10-20)；熟练老手/精英 (50-70)；绝世高手/宗师 (90-120+)。熟练度 (mastery_level) 默认填 1.0。
- 如果目标与已存在角色（特别是玩家主角）有明确的关系（如兄弟、仇敌、主仆等），必须在 relational_facts 中记录。
{capability_constraint}

必须返回纯 JSON 格式，结构严格对齐系统底盘：
{{
    "desc": "基于剧情与知名度提炼的一段客观中立的NPC背景描述",
    "tags": ["NPC", "阵营或身份标签"],
    "relational_facts": {{"已知角色名": "与该角色的关系描述"}},
    "3_capabilities": {{
        "核心招式名": {{"domains": ["战斗", "技术类型"], "base_power": 105, "mastery_level": 1.0, "features": ["特性描写"]}}
    }},
    "2_dynamic_status": {{
        "physical": {{"desc": "正常", "multiplier": 1.0}},
        "mental": {{"desc": "平静", "multiplier": 1.0}}
    }}
}}"""

    client = get_user_client()
    if not client:
        return major_graph
    try:
        response = client.chat.completions.create(
            model=MODEL_FLASH,
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)

        if is_new_npc:
            # 场景 1：全新角色入录，物理构建标准六维底层壳结构
            major_graph["entities"][target_name] = {
                "desc": result.get("desc", "神秘莫测的人物"),
                "tags": result.get("tags", ["NPC"]),
                "1_relational_facts": result.get("relational_facts", {}),
                "2_dynamic_status": result.get("2_dynamic_status", {}),
                "3_capabilities": result.get("3_capabilities", {}),
                "4_experience_factors": {"general_combat": 1.0, "specific_match": {}},
                "5_traits": [],
                "6_inventory": {}
            }
        else:
            # 场景 2：已有角色（如仅有名字和描述描述），增量补全核心矩阵
            if not major_graph["entities"][target_name].get("3_capabilities"):
                major_graph["entities"][target_name]["3_capabilities"] = result.get("3_capabilities", {})
            if not major_graph["entities"][target_name].get("2_dynamic_status"):
                major_graph["entities"][target_name]["2_dynamic_status"] = result.get("2_dynamic_status", {})
            # 补全关系（合并而非覆盖）
            if result.get("relational_facts"):
                major_graph["entities"][target_name].setdefault("1_relational_facts", {})
                major_graph["entities"][target_name]["1_relational_facts"].update(result["relational_facts"])
                
    except Exception:
        # 系统级异常兜底
        if is_new_npc:
            major_graph["entities"][target_name] = {
                "desc": "战局中突发介入的未知第三方实体",
                "tags": ["NPC"],
                "1_relational_facts": {},
                "2_dynamic_status": {"physical": {"desc": "正常", "multiplier": 1.0}, "mental": {"desc": "谨慎", "multiplier": 1.0}},
                "3_capabilities": {"基础应对": {"domains": ["通用"], "base_power": 15, "mastery_level": 1.0, "features": ["防卫本能"]}},
                "4_experience_factors": {"general_combat": 1.0, "specific_match": {}},
                "5_traits": [],
                "6_inventory": {}
            }
    return major_graph


def resolve_action_mechanics(action_type, ability_name, initiator_name, target_name, target_ongoing_action, major_graph, gm_memory, world_anchor_text, initiator_matched_assets=None, target_matched_assets=None):
    """
    数值检定算子（全能沙盒裁决版）。
    """
    # 转换确保为列表格式
    init_assets = initiator_matched_assets if isinstance(initiator_matched_assets, list) else []
    tgt_assets = target_matched_assets if isinstance(target_matched_assets, list) else []

    def calculate_conditional_buffs(entity_data, action_domains, opp_name, is_social, matched_assets):
        total_mult = 1.0
        activated = []
        
        for item_name, item_data in entity_data.get("6_inventory", {}).items():
            if isinstance(item_data, dict):
                tags = item_data.get("tags", item_data.get("target_domains", []))
                # 精准资产对齐：名字直接被大模型扫描锁定，或者标签交集命中
                if item_name in matched_assets or set(tags).intersection(set(action_domains)):
                    mult = item_data.get("multiplier", 1.0)
                    total_mult *= mult
                    activated.append(f"{item_name}(x{mult})")
                    
        for trait in entity_data.get("5_traits", []):
            t_name = trait.get("name", "")
            domains = trait.get("target_domains", [])
            if t_name in matched_assets or set(domains).intersection(set(action_domains)):
                mult = trait.get("multiplier", 1.0)
                total_mult *= mult
                activated.append(f"{t_name}(x{mult})")
                
        if is_social and opp_name:
            rel = entity_data.get("1_relational_facts", {}).get(opp_name)
            if isinstance(rel, dict):
                domains = rel.get("target_domains", [])
                if not domains or set(domains).intersection(set(action_domains)) or "社交" in action_domains:
                    mult = rel.get("multiplier", 1.0)
                    total_mult *= mult
                    activated.append(f"羁绊(x{mult})")
                    
        return total_mult, activated

    def _call_llm_for_dynamic_base(entity_name, specific_action, is_defense):
        role_type = "防御方 (判定目标抗打击度或破解难度/DC)" if is_defense else "发起方 (判定其侵袭烈度 or 出力 Base)"
        client = get_user_client()
        if not client:
            return entity_name or "环境", 15
        
        
        system_prompt = f"""你是一个 TRPG 的动态数值裁决引擎。

【当前宇宙法则与威力比例尺】
{world_anchor_text}

【任务协议】
当前正在评估 {role_type}：{entity_name or '环境'}
使用的动作/应对特征：{specific_action or '环境默认作用'}

请严格对照上方的【威力比例尺】，推断其在当前世界法则下合理的 dynamic_base (基数)。
必须返回纯 JSON 格式：
{{
    "dynamic_name": "提炼的具体动作或灾难/环境特征名",
    "dynamic_base": 25
}}"""
        
        
        try:
            response = client.chat.completions.create(
                model=MODEL_FLASH,
                messages=[{"role": "system", "content": system_prompt}],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            return result.get("dynamic_name", entity_name or "环境"), result.get("dynamic_base", 15)
        except Exception:
            return entity_name or "环境", 15

    def get_entity_combat_stats(entity_name, specific_ability, is_defense, opp_name, matched_assets):
        if not entity_name or entity_name not in major_graph.get("entities", {}) or entity_name == "环境":
            dyn_name, dyn_base = _call_llm_for_dynamic_base(entity_name, specific_ability, is_defense)
            d20 = random.randint(1, 20)
            return {
                "name": dyn_name, "ability": specific_ability or "环境作用",
                "base": dyn_base, "mastery": 1.0, "phys": 1.0, "ment": 1.0, "exp": 1.0, "cond": 1.0,
                "buffs": ["(动态裁决)"], "d20": d20, "final": dyn_base + d20
            }

        entity = major_graph["entities"][entity_name]
        caps = entity.get("3_capabilities", {})
        status = entity.get("2_dynamic_status", {})
        exp = entity.get("4_experience_factors", {})

        used_ability = "基础行动"
        base_power, mastery = 10, 1.0
        
        action_mapping = {"combat": "战斗", "skill": "技能", "stealth": "潜行", "social": "社交"}
        domains = [action_type, "通用"]
        if action_type in action_mapping:
            domains.append(action_mapping[action_type])
            
        if is_defense:
            domains.extend(["防御", "身法", "护体"])

        # 3. 智能匹配能力资产
        if caps:
            matched_key = None
            # 优先使用大模型扫描锁定的原资产能力键名
            for k in caps.keys():
                if k in matched_assets:
                    matched_key = k
                    break
            # 模糊文本包含兜底
            if not matched_key and specific_ability:
                for k in caps.keys():
                    if k in specific_ability or specific_ability in k:
                        matched_key = k; break
            
            if not matched_key and is_defense:
                for k, v in caps.items():
                    if any(d in v.get("domains", []) for d in ["防御", "身法", "护体"]):
                        matched_key = k; break
                        
            if not matched_key and is_defense:
                best_ability = max(caps.items(), key=lambda x: x[1].get("base_power", 10) * x[1].get("mastery_level", 1.0))
                matched_key = best_ability[0]
            elif not matched_key and not is_defense and specific_ability:
                used_ability = specific_ability 
                base_power = 25 
                
            if matched_key:
                used_ability = matched_key
                base_power = caps[matched_key].get("base_power", 10)
                mastery = caps[matched_key].get("mastery_level", 1.0)
                domains.extend(caps[matched_key].get("domains", []))
        elif specific_ability:
            used_ability = specific_ability
            if not is_defense:
                 base_power = 25

        # 4. 乘区乘算
        phys_mult = status.get("physical", {}).get("multiplier", 1.0)
        ment_mult = status.get("mental", {}).get("multiplier", 1.0)
        
        general_exp = exp.get("general_combat", 1.0)
        specific_exp = exp.get("specific_match", {}).get(used_ability, 1.0)
        exp_mult = general_exp * specific_exp
        
        # 【物理剔除旧猜测代码】：直接将大模型提取的匹配队列传给特质/背包结算器
        cond_mult, buffs = calculate_conditional_buffs(entity, domains, opp_name, action_type == "social", matched_assets)
        
        if general_exp != 1.0:
            buffs.append(f"通用经验(x{general_exp})")
        if specific_exp != 1.0:
            buffs.append(f"{used_ability}专精经验(x{specific_exp})")
        d20 = random.randint(1, 20)
        
        return {
            "name": entity_name, "ability": used_ability,
            "base": base_power, "mastery": mastery,
            "phys": phys_mult, "ment": ment_mult, "exp": exp_mult, "cond": cond_mult,
            "buffs": buffs, "d20": d20,
            "final": (base_power * mastery * phys_mult * ment_mult * exp_mult * cond_mult) + d20
        }

    # 进行双端推演
    initiator_stats = get_entity_combat_stats(initiator_name, ability_name, is_defense=False, opp_name=target_name, matched_assets=init_assets)
    target_stats = get_entity_combat_stats(target_name, target_ongoing_action, is_defense=True, opp_name=initiator_name, matched_assets=tgt_assets)

    delta = initiator_stats["final"] - target_stats["final"]
    if delta >= 15:
        tier = "发起方效果本次对抗中完全碾压了抵抗方效果"
    elif delta >= 0:
        tier = "发起方效果本次对抗中成功胜过了抵抗方效果"
    elif delta >= -10:
        tier = "发起方和抵抗方的效果本次对抗中相持不下"
    else:
        tier = "抵抗方效果本次对抗中完全碾压了发起方效果"

    def format_buffs(buffs):
        return f" * {' * '.join(buffs)}" if buffs else ""

    init_ability = initiator_stats['ability'] if "(动态裁决)" not in initiator_stats['buffs'] else "天灾/环境特征"
    tgt_ability = target_stats['ability'] if "(动态裁决)" not in target_stats['buffs'] else "阻碍/掩体特征"

    injection = f"\n【机制检定】{action_type.upper()}\n"
    
    if "(动态裁决)" in initiator_stats['buffs']:
        injection += f"[发起方] {initiator_stats['name']} ➔ 能力/特征: 【{init_ability}】\n"
        injection += f"         公式: (环境/天灾基数 {initiator_stats['base']}) + D20({initiator_stats['d20']}) = 出力 {initiator_stats['final']:.1f}\n"
    else:
        injection += f"[发起方] {initiator_stats['name']} ➔ 能力/特征: 【{init_ability}】\n"
        injection += f"         公式: ({initiator_stats['base']*initiator_stats['mastery']:.1f} * 体{initiator_stats['phys']} * 心{initiator_stats['ment']} * 状态特质{initiator_stats['cond']:.2f}{format_buffs(initiator_stats['buffs'])}) + D20({initiator_stats['d20']}) = 出力 {initiator_stats['final']:.1f}\n"
        
    if "(动态裁决)" in target_stats['buffs']:
        injection += f"[对抗方] {target_stats['name'] or '环境'} ➔ 应对/阻碍: 【{tgt_ability}】\n"
        injection += f"         公式: (环境/机关基数 {target_stats['base']}) + D20({target_stats['d20']}) = 抵抗 {target_stats['final']:.1f}\n"
    else:
        injection += f"[对抗方] {target_stats['name'] or '环境'} ➔ 应对/阻碍: 【{tgt_ability}】\n"
        injection += f"         公式: ({target_stats['base']*target_stats['mastery']:.1f} * 体{target_stats['phys']} * 心{target_stats['ment']} * 状态特质{target_stats['cond']:.2f}{format_buffs(target_stats['buffs'])}) + D20({target_stats['d20']}) = 抵抗 {target_stats['final']:.1f}\n"

    injection += f"【裁决结果】{tier} (Δ: {delta:.1f})\n"
    injection += f"指令: 严格服从裁决。合理映射上述优劣势乘区与运气对撞过程，禁止显式暴露任何数字。"

    return injection

def sync_dynamic_status(rendered_text, target_name, major_graph, active_scene, active_stage_names=None, pc_name="主角"):
    """
    战后影子同步算子（硬化完全体 - 智能雷达扫描版）：
    强行引入最近3幕上下文与舞台出场人物，通过时空全文本雷达动态提取涉事人物，绝育资产克隆Bug与全盘污染。
    """
    if active_stage_names is None:
        active_stage_names = []

    # 1. 物理灌入最近3幕对话上下文，给大模型提供“前情提要”，同时也作为雷达扫描池
    recent_context = "\n".join([f"{m['role']}: {m['content']}" for m in active_scene[-3:]]) if active_scene else "无"

    # 2. 物理灌入当前舞台在场的核心NPC，防止大模型孤立识别
    stage_info = ", ".join(active_stage_names) if active_stage_names else "仅主角在场"

    # 3. 🟢 智能雷达系统：初始化检查名录，主角作为终极宿主常驻
    entities_to_check = [pc_name]
    
    # 拼装全文本雷达扫描池
    full_radar_text = f"{rendered_text}\n{recent_context}"
    
    # 遍历大图谱中所有已知 NPC 进行捕获
    for name in major_graph.get("entities", {}).keys():
        if name == pc_name:
            continue
        # 捕获判定：在全文本中被提及 / 是舞台常驻角色 / 被检定算子明确作为 target_name 传了过来
        if (name in full_radar_text) or (name in active_stage_names) or (str(target_name) == name):
            if name not in entities_to_check:
                entities_to_check.append(name)

    # 4. 极端兜底防线：防止未在 entities 里正确迭代却被系统强传进来的已知实体遗漏
    if target_name and str(target_name) != "None" and target_name in major_graph.get("entities", {}):
        if target_name not in entities_to_check:
            entities_to_check.append(target_name)

    system_prompt = f"""你是一个TRPG状态同步与数值生成引擎。
请阅读动作结算文本，提取以下角色的状态变更与资产变动：{entities_to_check}。

【当前舞台时空坐标】
- 本幕在场核心角色名录: [{stage_info}]

【前情提要（最近3幕历史对话）】
{recent_context}

【核心任务与原子操作量化协议】
1. 状态重置 (2_dynamic_status)：
   必须依据文本严格量化乘区（绝佳/顿悟: 1.2-1.5；良好/专注: 1.05-1.15；正常: 1.0；疲惫/轻伤: 0.7-0.9；重伤/崩溃: 0.1-0.5）。
2. 资产新增/强化 (new_assets)：
   - 场景 A (无中生有)：角色获得了全新武器、特质、羁绊或武功。
   - 场景 B (旧物进化)：已有资产（名字必须与历史原名一字不差）获得了新标签（target_domains）或新词条（features）。
   ⚠️ 绝对红线：严禁将“观察/研究/装备/使用”背包里已有的物品误判为“获得新物品”。只有明确发生“拾取/购买/别人赠予”等资产净增量时才允许提取！
3. 资产剥离/移除 (removed_assets)：
   - 场景 C (属性削弱/洗练)：指定 `name` 并在 `target_domains` 中填入特定标签。系统将仅精准剔除该资产内部的这些属性（例如：武器上的“毒”标签失效）。
   - 场景 D (整体彻底销毁)：指定 `name`，并将 `target_domains` 保持为空列表 `[]`。系统将把该资产（如：武器丢失、NPC彻底死亡、特质被剥离）从图谱中物理抹除。
4. 需要替换属性时，可以先新增新属性后移除旧属性，参照2、3.

【AI可执行全操作终极完全体 JSON 样例】
必须严格参照以下全谱系样例结构进行 JSON 输出（若某个角色没有任何变动，则对应的 `new_assets` 和 `removed_assets` 保持为空列表 `[]`）：
{{
    "主角": {{
        "2_dynamic_status": {{
            "physical": {{"desc": "左臂被利刃斩中，流血不止", "multiplier": 0.75}},
            "mental": {{"desc": "燃起复仇的熊熊怒火，神志高度专注", "multiplier": 1.25}}
        }},
        "new_assets": [
            {{
                "category": "3_capabilities",
                "name": "天刀绝意斩",
                "target_domains": ["刀法", "爆发", "斩杀"],
                "base_power": 85,
                "features": ["临战顿悟", "无视轻甲"]
            }},
            {{
                "category": "6_inventory",
                "name": "戒指",
                "target_domains": ["储物", "未解密"],
                "multiplier": 1.0,
                "features": ["古朴的铜戒"]
            }}
        ],
        "removed_assets": [
            {{
                "category": "5_traits",
                "name": "文弱书生",
                "target_domains": []
            }}
        ]
    }},
    "敌对NPC姓名": {{
        "2_dynamic_status": {{
            "physical": {{"desc": "右腿骨折，行动力几近丧失", "multiplier": 0.40}},
            "mental": {{"desc": "陷入绝望，战意彻底崩溃", "multiplier": 0.30}}
        }},
        "new_assets": [],
        "removed_assets": [
            {{
                "category": "6_inventory",
                "name": "青钢长剑",
                "target_domains": []
            }},
            {{
                "category": "3_capabilities",
                "name": "狂风快剑",
                "target_domains": ["连击"] 
            }}
        ]
    }}
}}

【最新动作结算文本】
{rendered_text}

请严格以上述 JSON 样例为标准，输出本次清算结果："""
    
    client = get_user_client()
    if not client:
        return major_graph, {}
    try:
        response = client.chat.completions.create(
            model=MODEL_FLASH,
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)

        # ... 下方保留原有的数据落盘循环逻辑（无需改动） ...
        for entity, data in result.items():
            if entity not in major_graph["entities"]: continue
            entity_node = major_graph["entities"][entity]
            status_data = data.get("2_dynamic_status", {})
            if "2_dynamic_status" not in entity_node:
                entity_node["2_dynamic_status"] = {"physical": {"desc": "正常", "multiplier": 1.0}, "mental": {"desc": "正常", "multiplier": 1.0}}
            if "physical" in status_data: entity_node["2_dynamic_status"]["physical"] = status_data["physical"]
            if "mental" in status_data: entity_node["2_dynamic_status"]["mental"] = status_data["mental"]
            
            # （保留你原本代码里的 removed_assets 和 new_assets 循环部分即可）
            for removed in data.get("removed_assets", []):
                cat = removed.get("category"); name = removed.get("name")
                if not cat or not name: continue
                incoming_rem_tags = removed.get("target_domains", removed.get("tags", []))
                if isinstance(incoming_rem_tags, str): incoming_rem_tags = [incoming_rem_tags]
                elif not isinstance(incoming_rem_tags, list): incoming_rem_tags = []
                if cat in entity_node and isinstance(entity_node[cat], dict) and name in entity_node[cat]:
                    if incoming_rem_tags:
                        tag_key = "domains" if cat == "3_capabilities" else ("tags" if cat == "6_inventory" else "target_domains")
                        if tag_key in entity_node[cat][name] and isinstance(entity_node[cat][name][tag_key], list):
                            entity_node[cat][name][tag_key] = [t for t in entity_node[cat][name][tag_key] if t not in incoming_rem_tags]
                    else:
                        entity_node[cat].pop(name, None)
                elif cat == "5_traits" and isinstance(entity_node.get(cat), list):
                    existing_trait = next((t for t in entity_node["5_traits"] if isinstance(t, dict) and t.get("name") == name), None)
                    if existing_trait:
                        if incoming_rem_tags:
                            if "target_domains" in existing_trait and isinstance(existing_trait["target_domains"], list):
                                existing_trait["target_domains"] = [t for t in existing_trait["target_domains"] if t not in incoming_rem_tags]
                        else:
                            entity_node["5_traits"].remove(existing_trait)

            for new_asset in data.get("new_assets", []):
                cat = new_asset.get("category"); name = new_asset.get("name")
                if not cat or not name: continue
                if cat not in entity_node: entity_node[cat] = {} if cat != "5_traits" else []
                incoming_tags = new_asset.get("target_domains", new_asset.get("tags", []))
                if isinstance(incoming_tags, str): incoming_tags = [incoming_tags]
                elif not isinstance(incoming_tags, list): incoming_tags = []
                new_features = new_asset.get("features", [])
                if isinstance(new_features, str): new_features = [new_features]
                elif not isinstance(new_features, list): new_features = []

                if cat == "3_capabilities":
                    if name in entity_node["3_capabilities"]:
                        current_mastery = entity_node["3_capabilities"][name].get("mastery_level", 1.0)
                        entity_node["3_capabilities"][name]["mastery_level"] = round(current_mastery + 0.1, 2)
                        if "domains" not in entity_node["3_capabilities"][name]: entity_node["3_capabilities"][name]["domains"] = []
                        for tag in incoming_tags:
                            if tag not in entity_node["3_capabilities"][name]["domains"]: entity_node["3_capabilities"][name]["domains"].append(tag)
                        if "features" not in entity_node["3_capabilities"][name]: entity_node["3_capabilities"][name]["features"] = []
                        for feat in new_features:
                            if feat not in entity_node["3_capabilities"][name]["features"]: entity_node["3_capabilities"][name]["features"].append(feat)
                    else:
                        entity_node[cat][name] = {"domains": incoming_tags if incoming_tags else ["通用"], "base_power": max(1, int(new_asset.get("base_power", 20))), "mastery_level": 1.0, "features": new_features if new_features else ["剧情顿悟"]}
                elif cat == "6_inventory":
                    raw_mult = new_asset.get("multiplier", 1.0); safe_mult = max(0.1, min(float(raw_mult), 3.0))
                    if name in entity_node["6_inventory"]:
                        old_mult = entity_node["6_inventory"][name].get("multiplier", 1.0)
                        entity_node["6_inventory"][name]["multiplier"] = round(max(old_mult + 0.05, safe_mult), 2)
                        if "tags" not in entity_node["6_inventory"][name]: entity_node["6_inventory"][name]["tags"] = []
                        for tag in incoming_tags:
                            if tag not in entity_node["6_inventory"][name]["tags"]: entity_node["6_inventory"][name]["tags"].append(tag)
                        if "features" not in entity_node["6_inventory"][name]: entity_node["6_inventory"][name]["features"] = []
                        for feat in new_features:
                            if feat not in entity_node["6_inventory"][name]["features"]: entity_node["6_inventory"][name]["features"].append(feat)
                    else:
                        entity_node["6_inventory"][name] = {"tags": incoming_tags if incoming_tags else ["通用"], "multiplier": safe_mult, "features": new_features if new_features else ["初始获得"]}
                elif cat == "5_traits":
                    raw_mult = new_asset.get("multiplier", 1.0); safe_mult = max(0.1, min(float(raw_mult), 3.0))
                    existing_trait = next((t for t in entity_node["5_traits"] if isinstance(t, dict) and t.get("name") == name), None)
                    if existing_trait:
                        old_mult = existing_trait.get("multiplier", 1.0)
                        existing_trait["multiplier"] = round(max(old_mult + 0.05, safe_mult), 2)
                        if "target_domains" not in existing_trait: existing_trait["target_domains"] = []
                        for tag in incoming_tags:
                            if tag not in existing_trait["target_domains"]: existing_trait["target_domains"].append(tag)
                        if "features" not in existing_trait: existing_trait["features"] = []
                        for feat in new_features:
                            if feat not in existing_trait["features"]: existing_trait["features"].append(feat)
                    else:
                        entity_node["5_traits"].append({"name": name, "target_domains": incoming_tags if incoming_tags else ["通用"], "multiplier": safe_mult, "features": new_features if new_features else ["觉醒"]})
                else:
                    if isinstance(entity_node[cat], dict):
                        raw_mult = new_asset.get("multiplier", 1.0)
                        entity_node[cat][name] = {"target_domains": incoming_tags if incoming_tags else ["通用"], "multiplier": max(0.1, min(float(raw_mult), 3.0))}

    except Exception:
        pass 

    raw_sync_json = result if 'result' in locals() else {}
    return major_graph, raw_sync_json


# --- 存档物理销毁与重命名算子 ---

def rename_user_session(old_file_name, new_name):
    current_user = st.session_state.get("current_user")
    if not current_user or not old_file_name or not new_name.strip():
        return False, "参数无效。"
    if not new_name.endswith(".json"):
        new_name += ".json"
    try:
        db_client.table("user_sessions").update({"file_name": new_name}).eq("username", current_user).eq("file_name", old_file_name).execute()
        return True, new_name
    except Exception:
        return False, "新名字已被占用。"

def delete_user_session(file_name):
    current_user = st.session_state.get("current_user")
    if not current_user or not file_name:
        return False, "无效操作。"
    try:
        db_client.table("user_sessions").delete().eq("username", current_user).eq("file_name", file_name).execute()
        return True, "存档已成功粉碎。"
    except Exception as e:
        return False, f"粉碎失败: {str(e)}"
    
    
if __name__ == "__main__":
    print("测试 Core Engine 流式输出 (PRO)...")
    test_msgs = [{"role": "user", "content": "你好，测试一下！"}]
    for chunk in generate_chat_stream("系统设定：测试。", test_msgs):
        print(chunk, end="", flush=True)
    print("\n测试完成。")
