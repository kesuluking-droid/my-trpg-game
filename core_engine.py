import os
import time
import re
import json
from openai import OpenAI
from config import MODEL_PRO, MODEL_FLASH, API_BASE_URL, DEBUG_MODE
import config
import random

# ==========================================
# 🛑 云端自动基建算子 (无中生有版)
# ==========================================
# 1. 绝对路径提取，防止云端环境路径解析出 None 导致 AttributeError
user_data_dir = os.path.dirname(os.path.abspath(config.USER_DATA_FILE))
os.makedirs(user_data_dir, exist_ok=True)

# 2. 如果文件不存在，或者文件异常大小为 0，则强行初始化一个干净的空字典 {}
if not os.path.exists(config.USER_DATA_FILE) or os.path.getsize(config.USER_DATA_FILE) == 0:
    with open(config.USER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False, indent=4)

# 3. 强行初始化专属玩家存档大目录
os.makedirs(os.path.abspath(config.SAVE_DIR), exist_ok=True)

# --- 账号与权限管理算子 ---

def register_user(username, password, security_question, security_answer):
    """玩家注册算子：存入密码与密保信息，并初始化专属空间"""
    username = username.strip()
    password = password.strip()
    security_question = security_question.strip()
    security_answer = security_answer.strip()
    
    if not username or not password or not security_question or not security_answer:
        return False, "所有字段均不能为空。"
    
    if os.path.exists(config.USER_DATA_FILE):
        with open(config.USER_DATA_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
    else:
        users = {}
        
    if username in users:
        return False, "该用户名已被注册，请更换。"
    
    # 数据结构升级：存入字典形式
    users[username] = {
        "password": password,
        "question": security_question,
        "answer": security_answer
    }
    
    os.makedirs(os.path.dirname(config.USER_DATA_FILE), exist_ok=True)
    with open(config.USER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=4)
        
    os.makedirs(os.path.join(config.SAVE_DIR, username), exist_ok=True)
    return True, "注册成功！"

def login_user(username, password):
    """玩家登录算子：兼容新旧数据结构"""
    username = username.strip()
    password = password.strip()
    
    if not os.path.exists(config.USER_DATA_FILE):
        return False, "系统暂无用户注册记录。"
        
    with open(config.USER_DATA_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
        
    if username in users:
        user_data = users[username]
        # 兼容新版字典结构
        if isinstance(user_data, dict) and user_data.get("password") == password:
            return True, "登录成功"
        # 兼容旧版纯字符串结构
        elif isinstance(user_data, str) and user_data == password:
            return True, "登录成功"
            
    return False, "用户名或密码错误"

def get_security_question(username):
    """提取密保问题算子"""
    username = username.strip()
    if not os.path.exists(config.USER_DATA_FILE):
        return None
        
    with open(config.USER_DATA_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
        
    if username in users and isinstance(users[username], dict):
        return users[username].get("question")
    return None

def retrieve_password(username, answer):
    """验证密保并返回密码算子"""
    username = username.strip()
    answer = answer.strip()
    
    with open(config.USER_DATA_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
        
    if username in users and isinstance(users[username], dict):
        if users[username].get("answer") == answer:
            return True, users[username].get("password")
            
    return False, "密保答案错误，或该账号为旧版账号未设置密保。"

def modify_password(username, old_password, new_password):
    """修改密码算子：校验旧密码，兼容旧版数据结构"""
    username = username.strip()
    old_password = old_password.strip()
    new_password = new_password.strip()
    
    if not username or not old_password or not new_password:
        return False, "字段不能为空。"
        
    if not os.path.exists(config.USER_DATA_FILE):
        return False, "系统暂无用户注册记录。"
        
    with open(config.USER_DATA_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
        
    if username not in users:
        return False, "该用户不存在。"
        
    user_data = users[username]
    
    # 校验旧密码并执行更新
    if isinstance(user_data, dict):
        if user_data.get("password") != old_password:
            return False, "旧密码错误。"
        users[username]["password"] = new_password
    elif isinstance(user_data, str):
        if user_data != old_password:
            return False, "旧密码错误。"
        # 旧版账号验证通过后，强制升级为字典结构
        users[username] = {
            "password": new_password,
            "question": "",
            "answer": ""
        }
        
    with open(config.USER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=4)
        
    return True, "密码修改成功。"

# 全局宏观战力锚定设置
ANCHOR_THRESHOLD_TABLE = """
【战力与破坏力量化锚定基准表 (Base数值参考)】
- Base 80-120+ (灾变级/神明级): 轻易抹除街区，普通人触之瞬间气化，绝世高手面临生死存亡。
- Base 40-70 (致命级/重火力级): 导弹轰炸、泥石流直击。普通人必然死亡，精英重伤致残，绝世高手破防受伤。
- Base 25-39 (高危级/强兵器级): 疾驰车辆撞击、大口径枪械、精英刺客必杀。普通人重伤濒死，熟手受创，精英轻伤。
- Base 12-24 (标准级/街头级): 重拳挥击、高处跌落、普通持械斗殴。普通人轻伤流血，熟手感到棘手，对精英毫无威胁。
- Base 1-11 (微弱级/日常级): 日常绊倒、生锈的普通门锁、微风。普通人可轻易化解，仅造成体力消耗或轻微阻碍。
"""


def get_user_client():
    import streamlit as st
    key = st.session_state.get("user_api_key", "")
    if not key or not key.startswith("sk-"):
        return None
    return OpenAI(api_key=key, base_url=API_BASE_URL)


def detect_action_intent(user_input, active_scene, pc_name, major_graph):
    """
    意图拦截器：判断玩家输入是否触发机制检定（带上下文与实体资产智能扫描版）。
    """
    # 1. 成功调用最近3幕对话上下文
    recent_context = "\n".join([f"{m['role']}: {m['content']}" for m in active_scene[-3:]]) if active_scene else "无"
    
    # 2. 从动态图谱中提取当前世界实体的资产快照，供大模型比对
    entities_snapshot = ""
    for name, data in major_graph.get("entities", {}).items():
        caps = ", ".join(data.get("3_capabilities", {}).keys()) or "无"
        traits = ", ".join([t.get("name", "") for t in data.get("5_traits", []) if isinstance(t, dict)]) or "无"
        inv = ", ".join(data.get("6_inventory", {}).keys()) or "无"
        entities_snapshot += f"【实体名: {name}】\n- 备选能力: [{caps}]\n- 先天特质: [{traits}]\n- 背包物品: [{inv}]\n\n"

    system_prompt = f"""你是一个跑团系统（TRPG）的冷酷规则裁判。
请判断最新剧情中是否发生了一次“具有挑战性的机制动作”或“突发灾难/不可抗力豁免”。

【核心判决法则】
1. 闲聊、普通的观察、顺从的互动 -> 非机制动作 (is_action: false)
2. 攻击、使用特定能力、试图偷窃、欺骗、遭遇天灾轰炸、强行突围 -> 机制动作 (is_action: true)

【双端实体识别最高协议】
- 主动行为：玩家主动对某物发难。initiator_entity 填 "{pc_name}"，target_entity 填目标NPC或环境。
- 被动豁免：突发灾难、天灾、大范围不可抗力波及或加害角色。
  此时，【核心威胁/灾难源头】才是真正的发起方！
  必须填：
    initiator_entity = "灾难/天灾的具体名称"（例如 "核弹爆炸"），
    detected_ability = "灾难的核心特征或类型"（例如 "核弹爆炸冲击波"、"洪水冲击"），
    target_entity = "{pc_name}"，
    target_ongoing_action = "玩家用来应对或躲避的招式/动作"。
- 绝对严禁把“掩体”、“大树”、“水下”、“墙壁”等玩家用来躲避的媒介误识别为对抗方实体！

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


def generate_chat_stream(context_text, active_scene):
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
    
    【最高指令：六维数据保护与命名协议】
    1. 数值保护：角色的武功、状态、物品等数值已处理完毕。你【绝对不可】在 base_desc 中编造武功数值。
    2. 命名强制规则：如果剧情中出现了没有名字的NPC（如：女军官、大夫、门房），请直接用其【显著特征或职业】作为 name（如："女军官"）。绝对严禁将NPC的名字误填为主角的名字！

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
        "relation_updates": []
    }}"""
    client = get_user_client()
    if not client:
        return {
            "summary": "【系统提示】：未配置正确的 API Key，无法提取摘要。", 
            "current_location": "未知", 
            "current_tension": 0, 
            "npc_updates": [], 
            "relation_updates": []
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
            
        return {"summary": "提取失败。", "current_location": "未知", "current_tension": 0, "npc_updates": [], "relation_updates": []}
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

def init_npc_combat_stats(target_name, active_scene, major_graph, world_tier):
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

    system_prompt = f"""你是一个 TRPG 的动态实体生成与资产补全引擎 (Game Master)。
当前世界观定调：{world_tier}

【目标实体情报】
姓名：{target_name}
基础已知设定：{existing_desc}
基础身份标签：{existing_tags}

【近期剧情上下文】
{recent_context}

【任务协议】
请根据该角色在剧情和世界观中的实际生态位与名望，推导其合理的背景描述、身份标签、掌握功法/能力以及当前的身心状态。
- 能力基础物理威力 (base_power) 必须严格对照基准：市井凡人/流氓 (10-20)；熟练老手/精英 (50-70)；绝世高手/宗师 (90-120+)。熟练度 (mastery_level) 默认填 1.0。

必须返回纯 JSON 格式，结构严格对齐系统底盘：
{{
    "desc": "基于剧情与知名度提炼的一段客观中立的NPC背景描述",
    "tags": ["NPC", "阵营或身份标签"],
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
                "1_relational_facts": {},
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


def resolve_action_mechanics(action_type, ability_name, initiator_name, target_name, target_ongoing_action, major_graph, gm_memory, world_tier, initiator_matched_assets=None, target_matched_assets=None):
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
        try:
            response = client.chat.completions.create(
                model=MODEL_FLASH,
                messages=[{"role": "system", "content": f"你是一个 TRPG 的动态数值裁决引擎。世界观：{world_tier}"}],
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
        
        if specific_exp != 1.0:
            buffs.append(f"{used_ability}经验(x{specific_exp})")
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

def sync_dynamic_status(rendered_text, target_name, major_graph, pc_name="主角"):
    """战后影子同步算子（完全体）：同步身心状态 + 动态提取武功/新资产"""
    entities_to_check = [pc_name]
    if target_name and str(target_name) != "None" and target_name in major_graph.get("entities", {}):
        if target_name not in entities_to_check:
            entities_to_check.append(target_name)

    system_prompt = f"""你是一个TRPG状态同步与数值生成引擎。
请阅读动作结算文本，提取以下角色的状态变更与资产变动：{entities_to_check}。

【任务1：状态提取与乘区量化】
提取 physical 和 mental 状态。
乘区规则必须严格量化：
- 绝佳/顿悟/狂暴/极度自信：1.2-1.5
- 良好/自信/专注/轻微增益：1.05-1.15
- 正常/平静：1.0
- 受挫/疲惫/轻伤/轻微恐惧：0.7-0.9
- 崩溃/绝望/重伤/濒死：0.1-0.5

【任务2：资产进化与新能力提取（AI涌现数值最高协议）】
若角色获得了新物品/特质/武功，或【已有物品/特质/武功发生了强化、重铸、进化、经验上升、添加了新属性/新变种标签】，必须将其提取。
- category：必须是 `6_inventory`, `5_traits`, `1_relational_facts`, 或 `3_capabilities` 之一。
- name：资产或武功名称（如果是已有资产升级，必须严格保持名字与历史原名完全一致）。
- target_domains：提取或追加的名词标签列表（如 ["毒", "破甲", "吸血"]）。如果是旧资产获得了新属性，请把新属性标签写在这里，系统会自动合并去重。
- features：字符串列表，提炼本次突变/强化在剧情中获得的特定扩展词条描述（如 ["附魔", "饮血", "炉火纯青"]），若无则填空列表 []。
- multiplier / base_power：若为全新资产，输出其基础物理威力/乘数；若为旧资产升级，可输出强化后的目标乘数/威力，系统会自动执行安全递增。

【任务3：资产退化与能力失去（移除最高协议）】
若角色失去了某件资产，或者已有物品/特质/武功的某种属性标签消失、退化、被净化（例如：武器上的“毒”失效了、武功失去了“破甲”特性），必须将其写入 removed_assets。
若指定了 target_domains（或 tags），系统将仅精准剔除该资产内部对应的属性标签。
若 target_domains 为空列表 []，系统将直接物理抹除整件资产。

【最新动作结算文本】
{rendered_text}

必须返回纯JSON格式：
{{
    "角色姓名": {{
        "2_dynamic_status": {{
            "physical": {{"desc": "精炼描述", "multiplier": 1.0}},
            "mental": {{"desc": "精炼描述", "multiplier": 1.1}}
        }},
        "new_assets": [
            {{
                "category": "6_inventory", 
                "name": "已有武器名或新资产名",
                "target_domains": ["新标签A", "新标签B"],
                "base_power": 60,
                "multiplier": 1.2,
                "features": ["新词条A", "新词条B"]
            }}
        ],
        "removed_assets": [
            {{
                "category": "6_inventory",
                "name": "已有武器名或能力名",
                "target_domains": ["要剥离的旧标签A", "要剥离的旧标签B"] 
            }}
        ]
    }}
}}"""
    
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

        for entity, data in result.items():
            if entity not in major_graph["entities"]:
                continue
            
            entity_node = major_graph["entities"][entity]

            # 1. 更新身心状态
            status_data = data.get("2_dynamic_status", {})
            if "2_dynamic_status" not in entity_node:
                entity_node["2_dynamic_status"] = {
                    "physical": {"desc": "正常", "multiplier": 1.0},
                    "mental": {"desc": "正常", "multiplier": 1.0}
                }
            if "physical" in status_data:
                entity_node["2_dynamic_status"]["physical"] = status_data["physical"]
            if "mental" in status_data:
                entity_node["2_dynamic_status"]["mental"] = status_data["mental"]

            # 2. 扣除物品/特质或其特定标签 (全新升级：双向标签剥离算子)
            for removed in data.get("removed_assets", []):
                cat = removed.get("category")
                name = removed.get("name")
                if not cat or not name:
                    continue
                
                # 提取 AI 指定需要剥离的标签
                incoming_rem_tags = removed.get("target_domains", removed.get("tags", []))
                if isinstance(incoming_rem_tags, str):
                    incoming_rem_tags = [incoming_rem_tags]
                elif not isinstance(incoming_rem_tags, list):
                    incoming_rem_tags = []

                # 处理字典类型的资产 (3_capabilities, 6_inventory, 1_relational_facts)
                if cat in entity_node and isinstance(entity_node[cat], dict) and name in entity_node[cat]:
                    if incoming_rem_tags:
                        # 确定当前资产的标签槽位键名
                        tag_key = "domains" if cat == "3_capabilities" else ("tags" if cat == "6_inventory" else "target_domains")
                        if tag_key in entity_node[cat][name] and isinstance(entity_node[cat][name][tag_key], list):
                            # 计算差集：剔除指定标签
                            entity_node[cat][name][tag_key] = [t for t in entity_node[cat][name][tag_key] if t not in incoming_rem_tags]
                            if "标签剥离" not in entity_node[cat][name].get("features", []):
                                if "features" not in entity_node[cat][name]:
                                    entity_node[cat][name]["features"] = []
                                entity_node[cat][name]["features"].append("属性消退")
                    else:
                        # 若未指定具体标签，执行原有逻辑：直接整件销毁
                        entity_node[cat].pop(name, None)
                        
                # 处理列表类型的资产 (5_traits)
                elif cat == "5_traits" and isinstance(entity_node.get(cat), list):
                    existing_trait = next((t for t in entity_node["5_traits"] if isinstance(t, dict) and t.get("name") == name), None)
                    if existing_trait:
                        if incoming_rem_tags:
                            if "target_domains" in existing_trait and isinstance(existing_trait["target_domains"], list):
                                existing_trait["target_domains"] = [t for t in existing_trait["target_domains"] if t not in incoming_rem_tags]
                                if "features" not in existing_trait:
                                    existing_trait["features"] = []
                                existing_trait["features"].append("特质衰减")
                        else:
                            entity_node["5_traits"].remove(existing_trait)

            # 3. 动态落盘新资产与新武功 (全新升级：支持Tag标签并集扩充与词条追加版)
            for new_asset in data.get("new_assets", []):
                cat = new_asset.get("category")
                name = new_asset.get("name")
                if not cat or not name:
                    continue
                    
                if cat not in entity_node:
                    entity_node[cat] = {} if cat != "5_traits" else []

                # 提取 AI 返回的新标签（兼容 target_domains 和 tags 字段）
                incoming_tags = new_asset.get("target_domains", new_asset.get("tags", []))
                if isinstance(incoming_tags, str):
                    incoming_tags = [incoming_tags]
                elif not isinstance(incoming_tags, list):
                    incoming_tags = []

                new_features = new_asset.get("features", [])
                if isinstance(new_features, str):
                    new_features = [new_features]
                elif not isinstance(new_features, list):
                    new_features = []

                # --- 分支1：能力/武功动态追加 Tag (3_capabilities) ---
                if cat == "3_capabilities":
                    if name in entity_node["3_capabilities"]:
                        # 1. 熟练度递增
                        current_mastery = entity_node["3_capabilities"][name].get("mastery_level", 1.0)
                        entity_node["3_capabilities"][name]["mastery_level"] = round(current_mastery + 0.1, 2)
                        # 2. 动态追加新 Tag (domains) 并去重
                        if "domains" not in entity_node["3_capabilities"][name]:
                            entity_node["3_capabilities"][name]["domains"] = []
                        for tag in incoming_tags:
                            if tag not in entity_node["3_capabilities"][name]["domains"]:
                                entity_node["3_capabilities"][name]["domains"].append(tag)
                        # 3. 词条追加
                        if "features" not in entity_node["3_capabilities"][name]:
                            entity_node["3_capabilities"][name]["features"] = []
                        for feat in new_features:
                            if feat not in entity_node["3_capabilities"][name]["features"]:
                                entity_node["3_capabilities"][name]["features"].append(feat)
                        if "经验提升" not in entity_node["3_capabilities"][name]["features"]:
                            entity_node["3_capabilities"][name]["features"].append("经验提升")
                    else:
                        entity_node[cat][name] = {
                            "domains": incoming_tags if incoming_tags else ["通用"],
                            "base_power": max(1, int(new_asset.get("base_power", 20))),
                            "mastery_level": 1.0,
                            "features": new_features if new_features else ["剧情顿悟"]
                        }
                    continue

                # --- 分支2：背包物品/武器动态追加 Tag (6_inventory) ---
                elif cat == "6_inventory":
                    raw_mult = new_asset.get("multiplier", 1.0)
                    safe_mult = max(0.1, min(float(raw_mult), 3.0))
                    
                    if name in entity_node["6_inventory"]:
                        # 1. 乘数微调
                        old_mult = entity_node["6_inventory"][name].get("multiplier", 1.0)
                        entity_node["6_inventory"][name]["multiplier"] = round(max(old_mult + 0.05, safe_mult), 2)
                        # 2. 动态追加新 Tag (tags) 并去重
                        if "tags" not in entity_node["6_inventory"][name]:
                            entity_node["6_inventory"][name]["tags"] = []
                        for tag in incoming_tags:
                            if tag not in entity_node["6_inventory"][name]["tags"]:
                                entity_node["6_inventory"][name]["tags"].append(tag)
                        # 3. 物品词条追加
                        if "features" not in entity_node["6_inventory"][name]:
                            entity_node["6_inventory"][name]["features"] = []
                        for feat in new_features:
                            if feat not in entity_node["6_inventory"][name]["features"]:
                                entity_node["6_inventory"][name]["features"].append(feat)
                        if "资产强化" not in entity_node["6_inventory"][name]["features"]:
                            entity_node["6_inventory"][name]["features"].append("资产强化")
                    else:
                        entity_node["6_inventory"][name] = {
                            "tags": incoming_tags if incoming_tags else ["通用"],
                            "multiplier": safe_mult,
                            "features": new_features if new_features else ["初始获得"]
                        }
                    continue

                # --- 分支3：特质动态追加 Tag (5_traits) ---
                elif cat == "5_traits":
                    raw_mult = new_asset.get("multiplier", 1.0)
                    safe_mult = max(0.1, min(float(raw_mult), 3.0))
                    
                    existing_trait = next((t for t in entity_node["5_traits"] if isinstance(t, dict) and t.get("name") == name), None)
                    
                    if existing_trait:
                        # 1. 特质乘数微调
                        old_mult = existing_trait.get("multiplier", 1.0)
                        existing_trait["multiplier"] = round(max(old_mult + 0.05, safe_mult), 2)
                        # 2. 动态追加新 Tag (target_domains) 并去重
                        if "target_domains" not in existing_trait:
                            existing_trait["target_domains"] = []
                        for tag in incoming_tags:
                            if tag not in existing_trait["target_domains"]:
                                existing_trait["target_domains"].append(tag)
                        # 3. 特质词条追加
                        if "features" not in existing_trait:
                            existing_trait["features"] = []
                        for feat in new_features:
                            if feat not in existing_trait["features"]:
                                existing_trait["features"].append(feat)
                        if "特质蜕变" not in existing_trait["features"]:
                            existing_trait["features"].append("特质蜕变")
                    else:
                        entity_node["5_traits"].append({
                            "name": name,
                            "target_domains": incoming_tags if incoming_tags else ["通用"],
                            "multiplier": safe_mult,
                            "features": new_features if new_features else ["觉醒"]
                        })
                    continue

                # --- 分支4：其余类型事实兜底 ---
                else:
                    if isinstance(entity_node[cat], dict):
                        raw_mult = new_asset.get("multiplier", 1.0)
                        entity_node[cat][name] = {
                            "target_domains": incoming_tags if incoming_tags else ["通用"],
                            "multiplier": max(0.1, min(float(raw_mult), 3.0))
                        }

    except Exception:
        pass 

    raw_sync_json = result if 'result' in locals() else {}
    return major_graph, raw_sync_json


if __name__ == "__main__":
    print("测试 Core Engine 流式输出 (PRO)...")
    test_msgs = [{"role": "user", "content": "你好，测试一下！"}]
    for chunk in generate_chat_stream("系统设定：测试。", test_msgs):
        print(chunk, end="", flush=True)
    print("\n测试完成。")