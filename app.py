import datetime
import streamlit as st
import re
import memory_manager
import core_engine
import copy
import json

st.set_page_config(page_title="简易RPG", layout="wide")
st.title("Kesuluking-RPG")

# ==========================================
# 🛑 门卫系统：登录、注册与密码找回网关
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "current_user" not in st.session_state:
    st.session_state.current_user = None

if not st.session_state.logged_in:
    st.caption("请先登录或注册以载入您的专属世界线")
    
    tab_login, tab_reg, tab_forget, tab_modify = st.tabs(["用户登录", "新用户注册", "找回密码", "修改密码"])
    
    with tab_login:
        login_user = st.text_input("用户名", key="l_user")
        login_pwd = st.text_input("密码", type="password", key="l_pwd")
        if st.button("Kesuluking-RPG 启动！", use_container_width=True):
            success, msg = core_engine.login_user(login_user, login_pwd)
            if success:
                st.session_state.logged_in = True
                st.session_state.current_user = login_user
                st.success("登录成功，正在进入游戏大厅...")
                st.rerun() # 刷新网页，门卫放行！
            else:
                st.error(msg)
                
    with tab_reg:
        reg_user = st.text_input("设定新用户名", key="r_user")
        reg_pwd = st.text_input("设定新密码", type="password", key="r_pwd")
        # 【新增】：确认密码输入框
        reg_pwd_confirm = st.text_input("确认新密码", type="password", key="r_pwd_c") 
        reg_question = st.text_input("设置密保问题用于找回密码 (例：我的第一只宠物叫什么？)", key="r_q")
        reg_answer = st.text_input("设置密保答案", type="password", key="r_a")
        
        if st.button("创建新账号", use_container_width=True):
            # 【新增】：本地先拦截比对，不一致直接报错，不向后端发送注册请求
            if reg_pwd != reg_pwd_confirm:
                st.error("两次输入的密码不一致，请重新检查！")
            else:
                success, msg = core_engine.register_user(reg_user, reg_pwd, reg_question, reg_answer)
                if success:
                    st.success(msg + " 请切换到【用户登录】标签页登录。")
                else:
                    st.error(msg)
                
    with tab_forget:
        f_user = st.text_input("输入需要找回密码的用户名", key="f_user")
        if f_user:
            question = core_engine.get_security_question(f_user)
            if question:
                st.info(f"密保问题：{question}")
                f_ans = st.text_input("输入答案", type="password", key="f_ans")
                if st.button("验证并显示密码", use_container_width=True):
                    success, result = core_engine.retrieve_password(f_user, f_ans)
                    if success:
                        st.success(f"验证成功！您的密码是：**{result}**")
                    else:
                        st.error(result)
            else:
                st.warning("该用户不存在，或属于未设置密保的旧版账号。")
    
    with tab_modify:
        m_user = st.text_input("用户名", key="m_user")
        m_old_pwd = st.text_input("旧密码", type="password", key="m_old_pwd")
        m_new_pwd = st.text_input("新密码", type="password", key="m_new_pwd")
        m_new_pwd_c = st.text_input("确认新密码", type="password", key="m_new_pwd_c")
        
        if st.button("确认修改密码", use_container_width=True):
            if m_new_pwd != m_new_pwd_c:
                st.error("两次输入的新密码不一致，请重新检查。")
            else:
                success, msg = core_engine.modify_password(m_user, m_old_pwd, m_new_pwd)
                if success:
                    st.success(msg + " 请切换到【用户登录】标签页使用新密码重新登录。")
                else:
                    st.error(msg)
    # 核心拦截器：如果没登录，程序到这里强制刹车，绝对不会执行下面的任何游戏代码！
    st.stop()

# ==========================================
# 🟢 门卫放行：以下为原本的全局变量与状态机初始化
# ==========================================


DEFAULT_PC = {
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

DEFAULT_WORLD_TIER = "近未来都市异能 / 中低武阶段"

# 1. 状态初始化 (新增全套状态机)
# ==========================================
if "active_scene" not in st.session_state:
    st.session_state.active_scene = []  
if "history_archive" not in st.session_state:
    st.session_state.history_archive = [] 
if "memory" not in st.session_state:
    st.session_state.memory = ""
if "current_file" not in st.session_state:
    st.session_state.current_file = ""
if "minor_npcs" not in st.session_state:
    st.session_state.minor_npcs = {}

# 1.1 先确保基础默认设定变量存在
if "world_tier" not in st.session_state:
    st.session_state.world_tier = DEFAULT_WORLD_TIER
if "pc_name" not in st.session_state:
    st.session_state.pc_name = "主角"
if "pc_template" not in st.session_state:
    st.session_state.pc_template = copy.deepcopy(DEFAULT_PC)

# 1.2 【核心修复】：必须先给 major_graph 兜底初始化，才能进行更名校验！
if "major_graph" not in st.session_state:
    st.session_state.major_graph = {
        "entities": {st.session_state.pc_name: copy.deepcopy(st.session_state.pc_template)}, 
        "relations": []
    }

# 1.3 【核心修改】：现在可以安全执行图谱实体命名绝对强同步了
if "major_graph" in st.session_state and "entities" in st.session_state.major_graph:
    _entities = st.session_state.major_graph["entities"]
    _current_name = st.session_state.get("pc_name", "主角")
    
    # 场景 1：图谱里还残留着旧的 "主角" 键名，直接物理更名并迁移数据
    if _current_name != "主角" and "主角" in _entities:
        _entities[_current_name] = _entities.pop("主角")
        
    # 场景 2：极端防错。如果图谱里既没有新名字也没有老名字，强制初始化新实体
    if _current_name not in _entities:
        _entities[_current_name] = copy.deepcopy(st.session_state.pc_template)

# 1.4 其余后续变量安全初始化
if "graveyard" not in st.session_state:
    st.session_state.graveyard = {}
if "director_directive" not in st.session_state: 
    st.session_state.director_directive = ""
if "scene_index" not in st.session_state:
    st.session_state.scene_index = 1
if "mechanics_log" not in st.session_state:       
    st.session_state.mechanics_log = []
if "sync_log" not in st.session_state:            
    st.session_state.sync_log = []
if "gm_memory" not in st.session_state:       
    st.session_state.gm_memory = []

if "show_settings" not in st.session_state:
    st.session_state.show_settings = False



# ==========================================

def cb_add_cap():
    st.session_state.edit_caps.append({"name": "", "base_power": 10, "domains": ""})

def cb_del_cap(idx):
    st.session_state.edit_caps.pop(idx)

def cb_add_trait():
    st.session_state.edit_traits.append({"name": "", "multiplier": 1.0, "domains": ""})

def cb_del_trait(idx):
    st.session_state.edit_traits.pop(idx)

def cb_add_inv():
    st.session_state.edit_inv.append({"name": "", "multiplier": 1.0, "domains": ""})

def cb_del_inv(idx):
    st.session_state.edit_inv.pop(idx)

def cb_add_exp():
    st.session_state.edit_exp_specific.append({"name": "", "multiplier": 1.0})

def cb_del_exp(idx):
    st.session_state.edit_exp_specific.pop(idx)

@st.dialog("世界与主角定制面板")
def settings_dialog():
    # 初始化数据结构
    if "dialog_initialized" not in st.session_state:
        st.session_state.edit_caps = [
            {"name": k, "base_power": int(v.get("base_power", 10)), "domains": ", ".join(v.get("domains", []))}
            for k, v in st.session_state.pc_template.get("3_capabilities", {}).items()
        ]
        st.session_state.edit_traits = [
            {"name": v.get("name", ""), "multiplier": float(v.get("multiplier", 1.0)), "domains": ", ".join(v.get("target_domains", []))}
            for v in st.session_state.pc_template.get("5_traits", [])
        ]
        st.session_state.edit_inv = [
            {"name": k, "multiplier": float(v.get("multiplier", 1.0)), "domains": ", ".join(v.get("tags", []))}
            for k, v in st.session_state.pc_template.get("6_inventory", {}).items()
        ]
        # 【新增】：初始化经验系数表单数据
        st.session_state.edit_exp_general = float(st.session_state.pc_template.get("4_experience_factors", {}).get("general_combat", 1.0))
        st.session_state.edit_exp_specific = [
            {"name": k, "multiplier": float(v)}
            for k, v in st.session_state.pc_template.get("4_experience_factors", {}).get("specific_match", {}).items()
        ]
        st.session_state.settings_saved_status = False
        st.session_state.dialog_initialized = True

    tab1, tab2, tab3, tab4 = st.tabs(["基本与状态", "初始能力", "先天特质", "初始背包"])
    
    with tab1:
        new_tier = st.text_input("当前世界观定调", value=st.session_state.world_tier)
        new_pc_name = st.text_input("主角姓名", value=st.session_state.pc_name)
        new_desc = st.text_area("主角背景描述", value=st.session_state.pc_template.get("desc", "世界的变数"))
        
        current_tags = ", ".join(st.session_state.pc_template.get("tags", ["玩家"]))
        new_tags_str = st.text_input("角色身份标签 (英文逗号分隔)", value=current_tags)
        new_tags = [t.strip() for t in new_tags_str.split(",") if t.strip()]
        
        st.write("---")
        st.markdown("**初始动态状态**")
        p_data = st.session_state.pc_template["2_dynamic_status"]["physical"]
        p_desc = st.text_input("肉体状态描述", value=p_data.get("desc", "健康"))
        p_mult = st.number_input("肉体出力乘数", value=p_data.get("multiplier", 1.0), step=0.05)
        
        m_data = st.session_state.pc_template["2_dynamic_status"]["mental"]
        m_desc = st.text_input("精神状态描述", value=m_data.get("desc", "平静"))
        m_mult = st.number_input("精神出力乘数", value=m_data.get("multiplier", 1.0), step=0.05)

        # 【新增】：Tab 1 底部追加经验系数表单配置
        st.write("---")
        st.markdown("**经验系数配置**")
        new_exp_general = st.number_input("通用战斗经验系数 (general_combat)", value=st.session_state.edit_exp_general, step=0.1)
        
        st.caption("特定功法/内功经验加成 (specific_match)")
        eh1, eh2, eh3 = st.columns([4, 4, 1.2])
        eh1.caption("功法/技能/对抗名")
        eh2.caption("经验乘数")
        eh3.caption("操作")
        for i, exp_item in enumerate(st.session_state.edit_exp_specific):
            col1, col2, col3 = st.columns([4, 4, 1.2])
            exp_item["name"] = col1.text_input("经验名", value=exp_item["name"], key=f"exp_name_{i}", label_visibility="collapsed")
            exp_item["multiplier"] = col2.number_input("经验系数", value=exp_item["multiplier"], key=f"exp_mult_{i}", step=0.1, label_visibility="collapsed")
            col3.button("删除", key=f"exp_del_{i}", use_container_width=True, on_click=cb_del_exp, args=(i,))
        st.button("新增特定经验系数", type="secondary", on_click=cb_add_exp)

    with tab2:
        st.markdown("**初始能力定制**")
        h1, h2, h3, h4 = st.columns([3, 2, 4, 1.2])
        h1.caption("能力名字")
        h2.caption("基础威力")
        h3.caption("适用领域")
        h4.caption("操作")
        for i, cap in enumerate(st.session_state.edit_caps):
            col1, col2, col3, col4 = st.columns([3, 2, 4, 1.2])
            cap["name"] = col1.text_input("能力名", value=cap["name"], key=f"cap_name_{i}", label_visibility="collapsed")
            cap["base_power"] = col2.number_input("威力", value=cap["base_power"], key=f"cap_pow_{i}", step=5, label_visibility="collapsed")
            cap["domains"] = col3.text_input("领域", value=cap["domains"], key=f"cap_dom_{i}", label_visibility="collapsed")
            col4.button("删除", key=f"cap_del_{i}", use_container_width=True, on_click=cb_del_cap, args=(i,))
        st.button("新增能力", type="secondary", on_click=cb_add_cap)

    with tab3:
        st.markdown("**先天特质定制**")
        th1, th2, th3, th4 = st.columns([3, 2, 4, 1.2])
        th1.caption("特质名字")
        th2.caption("影响乘数")
        th3.caption("作用领域")
        th4.caption("操作")
        for i, trait in enumerate(st.session_state.edit_traits):
            col1, col2, col3, col4 = st.columns([3, 2, 4, 1.2])
            trait["name"] = col1.text_input("特质名", value=trait["name"], key=f"trait_name_{i}", label_visibility="collapsed")
            trait["multiplier"] = col2.number_input("特质乘数", value=trait["multiplier"], key=f"trait_mult_{i}", step=0.05, label_visibility="collapsed")
            trait["domains"] = col3.text_input("特质领域", value=trait["domains"], key=f"trait_dom_{i}", label_visibility="collapsed")
            col4.button("删除", key=f"trait_del_{i}", use_container_width=True, on_click=cb_del_trait, args=(i,))
        st.button("新增特质", type="secondary", on_click=cb_add_trait)

    with tab4:
        st.markdown("**初始背包物品**")
        ih1, ih2, ih3, ih4 = st.columns([3, 2, 4, 1.2])
        ih1.caption("物品名字")
        ih2.caption("加成乘数")
        ih3.caption("适用领域")
        ih4.caption("操作")
        for i, inv in enumerate(st.session_state.edit_inv):
            col1, col2, col3, col4 = st.columns([3, 2, 4, 1.2])
            inv["name"] = col1.text_input("物品名", value=inv["name"], key=f"inv_name_{i}", label_visibility="collapsed")
            inv["multiplier"] = col2.number_input("物品乘数", value=inv["multiplier"], key=f"inv_mult_{i}", step=0.05, label_visibility="collapsed")
            inv["domains"] = col3.text_input("物品领域", value=inv["domains"], key=f"inv_dom_{i}", label_visibility="collapsed")
            col4.button("删除", key=f"inv_del_{i}", use_container_width=True, on_click=cb_del_inv, args=(i,))
        st.button("新增物品", type="secondary", on_click=cb_add_inv)

    st.write("---")
    
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("保存设定 (新建会话生效)", type="primary", use_container_width=True):
            try:
                st.session_state.world_tier = new_tier
                st.session_state.pc_name = new_pc_name
                
                template = st.session_state.pc_template
                template["desc"] = new_desc
                template["tags"] = new_tags
                template["2_dynamic_status"]["physical"] = {"desc": p_desc, "multiplier": p_mult}
                template["2_dynamic_status"]["mental"] = {"desc": m_desc, "multiplier": m_mult}
                
                # 【新增】：重组并保存经验系数到全局模板
                template["4_experience_factors"] = {
                    "general_combat": float(new_exp_general),
                    "specific_match": {e["name"].strip(): float(e["multiplier"]) for e in st.session_state.edit_exp_specific if e["name"].strip()}
                }
                
                template["3_capabilities"] = {c["name"].strip(): {"domains": [d.strip() for d in c["domains"].split(",") if d.strip()], "base_power": int(c["base_power"]), "mastery_level": 1.0, "features": ["初始设定"]} for c in st.session_state.edit_caps if c["name"].strip()}
                template["5_traits"] = [{"name": t["name"].strip(), "target_domains": [d.strip() for d in t["domains"].split(",") if d.strip()], "multiplier": float(t["multiplier"])} for t in st.session_state.edit_traits if t["name"].strip()]
                template["6_inventory"] = {v["name"].strip(): {"tags": [d.strip() for d in v["domains"].split(",") if d.strip()], "multiplier": float(v["multiplier"])} for v in st.session_state.edit_inv if v["name"].strip()}
                
                st.session_state.settings_saved_status = True
                st.toast("设定已暂存至底层模板")
                st.rerun()
            except Exception as e:
                st.error(f"保存失败: {e}")

    with col_btn2:
        if st.button("关闭面板", use_container_width=True):
            st.session_state.show_settings = False
            if "dialog_initialized" in st.session_state:
                del st.session_state.dialog_initialized
            st.rerun()

    if st.session_state.get("settings_saved_status", False):
        st.success("设定保存成功，请点击下方按钮清空并重构当前会话")
        
        if st.button("立即新建会话并应用新设定", type="secondary", use_container_width=True):
            new_file = f"chat_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            st.session_state.current_file = new_file
            st.session_state.active_scene = []
            st.session_state.history_archive = []
            st.session_state.memory = ""
            st.session_state.minor_npcs = {}
            st.session_state.graveyard = {}
            st.session_state.director_directive = ""
            st.session_state.scene_index = 1
            st.session_state.tension_history = []
            st.session_state.current_location = "未知区域"
            st.session_state.mechanics_log = []
            st.session_state.sync_log = []
            st.session_state.gm_memory = []
            
            st.session_state.major_graph = {
                "entities": {st.session_state.pc_name: copy.deepcopy(st.session_state.pc_template)}, 
                "relations": []
            }
            
            trigger_save()
            
            st.session_state.settings_saved_status = False
            st.session_state.show_settings = False
            if "dialog_initialized" in st.session_state:
                del st.session_state.dialog_initialized
                
            st.toast("全新会话已开启")
            st.rerun()

# 包装存档功能（新增 scene_index）
def trigger_save():
    memory_manager.save_session(
        st.session_state.current_file, 
        st.session_state.memory, 
        st.session_state.history_archive,
        st.session_state.active_scene,
        st.session_state.minor_npcs,
        st.session_state.major_graph,
        st.session_state.graveyard,
        st.session_state.director_directive,
        st.session_state.scene_index,
        st.session_state.get("tension_history", []),
        st.session_state.get("current_location", "未知区域"),
        st.session_state.get("mechanics_log", []),
        st.session_state.get("sync_log", []),
        st.session_state.get("gm_memory", []),
        st.session_state.world_tier,
        st.session_state.pc_name
    )

def render_sidebar_panel(major_graph):
    """侧边栏六维数据实时可视化面板"""
    import streamlit as st
    
    with st.sidebar:
        # ==========================================
        # 🔑 新增：玩家 API 凭据配置箱 (必须置顶，防止被下方的 return 阻断)
        # ==========================================
        st.markdown("### 🔑 玩家 API 凭据")
        st.caption("💡 游戏已接入云端。请在下方配置您个人的 DeepSeek API Key。您的 Key 仅在当前浏览器生效，绝不上传服务器。")
        
        # 初始化 session_state
        if "user_api_key" not in st.session_state:
            st.session_state.user_api_key = ""
            
        user_key_input = st.text_input(
            "DeepSeek API Key:",
            value=st.session_state.user_api_key,
            type="password",
            placeholder="sk-...",
            help="请在此处粘贴您的 DeepSeek 官方 API 密钥"
        )
        
        # 强校验是否符合 DeepSeek 密钥特征
        if user_key_input:
            if not user_key_input.startswith("sk-"):
                st.error("⚠️ 警告：校验失败！请输入标准的 DeepSeek 官方 API 密钥 (以 sk- 开头)。")
            else:
                st.session_state.user_api_key = user_key_input
                st.success("✅ DeepSeek API 凭据已成功挂载！")
        else:
            st.warning("🛑 提示：未检测到个人 API Key，系统当前正处于未授权停机状态。")
            
        st.divider()
        # ==========================================
        
    with st.sidebar:
        st.header("实时状态与核心图谱")
        entities = major_graph.get("entities", {})
        if not entities:
            st.info("暂无核心角色数据")
            return

        # 1. 主角面板（置顶并强制展开）
        current_pc_name = st.session_state.get("pc_name", "主角")
        if current_pc_name in entities:
            pc = entities[current_pc_name]
            with st.expander(f"【{current_pc_name}】当前属性", expanded=True):
                # 身心状态
                status = pc.get("2_dynamic_status", {})
                p_obj = status.get("physical", {})
                m_obj = status.get("mental", {})
                st.markdown(f"**身体状态**: {p_obj.get('desc', '正常')} `x{p_obj.get('multiplier', 1.0)}`")
                st.markdown(f"**心理状态**: {m_obj.get('desc', '正常')} `x{m_obj.get('multiplier', 1.0)}`")
                
                # 【新增】：侧边栏实时渲染经验系数
                exp_data = pc.get("4_experience_factors", {})
                st.markdown(f"**通用战斗经验**: `x{exp_data.get('general_combat', 1.0)}`")
                spec_exp = exp_data.get("specific_match", {})
                if spec_exp:
                    spec_exp_str = ", ".join([f"{k}:x{v}" for k, v in spec_exp.items()])
                    st.markdown(f"**特定功法经验**: {spec_exp_str}")
                
                st.divider()
                
                # 能力
                caps = pc.get("3_capabilities", {})
                if caps:
                    st.markdown("**掌握能力**:")
                    for k, v in caps.items():
                        feats_str = f" [{', '.join(v.get('features', []))}]" if v.get("features") else ""
                        st.markdown(f"- {k} (基础:{v.get('base_power', 10)} 熟练:{v.get('mastery_level', 1.0)}){feats_str}")
                
                # 特质
                traits = pc.get("5_traits", [])
                if traits:
                    st.markdown("**固有特质**:")
                    for t in traits:
                        feats_str = f" [{', '.join(t.get('features', []))}]" if isinstance(t, dict) and t.get("features") else ""
                        st.markdown(f"- {t.get('name', '未定义')}(x{t.get('multiplier', 1.0)}){feats_str}")
                
                # 物品
                inv = pc.get("6_inventory", {})
                if inv:
                    st.markdown("**背包物品**:")
                    for k, v in inv.items():
                        mult = v.get("multiplier", 1.0) if isinstance(v, dict) else 1.0
                        feats_str = f" [{', '.join(v.get('features', []))}]" if isinstance(v, dict) and v.get("features") else ""
                        st.markdown(f"- {k}(x{mult}){feats_str}")

        # 2. 其他核心NPC面板（默认折叠）
        st.subheader("核心NPC名录")
        current_pc_name = st.session_state.get("pc_name", "主角")
        for name, data in entities.items():
            # 物理对齐动态更名，防止改名后的主角在这里重复暴露
            if name == current_pc_name:
                continue
            with st.expander(f"NPC: {name}", expanded=False):
                st.markdown(f"**设定**: {data.get('desc', '无基础设定')}")
                
                # NPC身心状态
                status = data.get("2_dynamic_status", {})
                p_mult = status.get("physical", {}).get("multiplier", 1.0)
                m_mult = status.get("mental", {}).get("multiplier", 1.0)
                st.markdown(f"**身心状态**: 体 `x{p_mult}` | 心 `x{m_mult}`")
                
                # NPC羁绊事实
                facts = data.get("1_relational_facts", {})
                if facts:
                    st.markdown("**人际羁绊**:")
                    for target, fact in facts.items():
                        f_str = f"x{fact.get('multiplier', 1.0)}" if isinstance(fact, dict) else str(fact)
                        st.markdown(f"- 对 {target}: {f_str}")
                        
                # 增补：NPC能力展示（含词条）
                caps = data.get("3_capabilities", {})
                if caps:
                    st.markdown("**掌握能力**:")
                    for k, v in caps.items():
                        feats_str = f" [{', '.join(v.get('features', []))}]" if v.get("features") else ""
                        st.markdown(f"- {k} (基础:{v.get('base_power', 10)} 熟练:{v.get('mastery_level', 1.0)}){feats_str}")
                
                # 增补：NPC特质展示（含词条）
                traits = data.get("5_traits", [])
                if traits:
                    st.markdown("**固有特质**:")
                    for t in traits:
                        feats_str = f" [{', '.join(t.get('features', []))}]" if isinstance(t, dict) and t.get("features") else ""
                        st.markdown(f"- {t.get('name', '未定义')}(x{t.get('multiplier', 1.0)}){feats_str}")
                
                # 增补：NPC物品展示（含词条）
                inv = data.get("6_inventory", {})
                if inv:
                    st.markdown("**背包物品**:")
                    for k, v in inv.items():
                        mult = v.get("multiplier", 1.0) if isinstance(v, dict) else 1.0
                        feats_str = f" [{', '.join(v.get('features', []))}]" if isinstance(v, dict) and v.get("features") else ""
                        st.markdown(f"- {k}(x{mult}){feats_str}")
                        
        # 替换侧边栏中的检定日志面板代码：
        st.divider()
        with st.expander("🛠️ 开发者：后台检定日志 (黑匣子)", expanded=False):
            logs = st.session_state.get("mechanics_log", [])
            if not logs:
                st.caption("暂无机制检定记录")
            else:
                for entry in reversed(logs[-10:]):
                    # 【核心修复】：增加字典类型强校验，防止历史脏数据引发崩溃
                    if isinstance(entry, dict) and "scene" in entry:
                        st.markdown(f"**[第{entry['scene']}幕] {entry.get('action', '未知')} -> {entry.get('target', '未知')}**")
                        st.text(entry.get('log', '').strip())
                        
                        # 【新增嵌入】：如果该条对撞日志中持久化了拦截器的原始快照，直接原地渲染 JSON 树
                        if "raw_intent" in entry:
                            st.caption("🤖 意图拦截器原始判定快照：")
                            st.json(entry["raw_intent"])
                            
                    else:
                        # 容错降级
                        st.caption(f"脏数据物理隔离 (检定): {str(entry)}")
                    st.write("---")
        
        st.divider()
        with st.expander("🧬 开发者：后台状态/资产变更日志", expanded=False):
            sync_logs = st.session_state.get("sync_log", [])
            if not sync_logs:
                st.caption("暂无状态或资产变更记录")
            else:
                for entry in reversed(sync_logs[-10:]):
                    # 【核心修复】：强校验 entry 是否为标准的日志字典，防止数据结构错乱引发闪退
                    if isinstance(entry, dict) and "scene" in entry:
                        st.markdown(f"**[第{entry['scene']}幕] 实体: {entry.get('target', '未知')}**")
                        st.json(entry.get('changes', {}))
                    else:
                        # 容错降级：如果旧档里残留了错乱的纯字符串/历史脏数据，安全打印
                        st.caption(f"脏数据物理隔离: {str(entry)}")
                    st.write("---")

# 2. 侧边栏 UI
with st.sidebar:
    st.subheader("会话控制")
    chat_files = memory_manager.get_chat_files()
    
    if st.button("🛠️ 游戏设定定制", type="primary", use_container_width=True):
        st.session_state.show_settings = True
        st.rerun()
    
    if st.button("新建会话", use_container_width=True):
        new_file = f"chat_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        st.session_state.current_file = new_file
        st.session_state.history_archive = []
        st.session_state.active_scene = []
        st.session_state.memory = ""
        st.session_state.minor_npcs = {}
        st.session_state.major_graph = {"entities": {"主角": copy.deepcopy(DEFAULT_PC)}, "relations": []}
        st.session_state.graveyard = {}
        st.session_state.director_directive = ""
        st.session_state.scene_index = 1 # 新建时重置幕次
        st.session_state.tension_history = []
        st.session_state.current_location = "未知区域"
        st.session_state.mechanics_log = []
        st.session_state.sync_log = []
        st.session_state.gm_memory = []
        trigger_save()
        st.rerun()

    if chat_files:
        if not st.session_state.current_file or st.session_state.current_file not in chat_files:
            st.session_state.current_file = chat_files[0]
            (st.session_state.memory, 
             st.session_state.history_archive, 
             st.session_state.active_scene,
             st.session_state.minor_npcs, 
             st.session_state.major_graph, 
             st.session_state.graveyard,
             st.session_state.director_directive, 
             st.session_state.scene_index,
             st.session_state.tension_history,      
             st.session_state.current_location,
             st.session_state.mechanics_log,
             st.session_state.sync_log,
             st.session_state.gm_memory,
             st.session_state.world_tier,
             st.session_state.pc_name
            ) = memory_manager.load_session(st.session_state.current_file)
            if st.session_state.pc_name != "主角":
                if "主角" in st.session_state.major_graph.get("entities", {}):
                    # 将旧的面板数据提取出来，赋予新的自定义名字，并删掉旧的 "主角"
                    st.session_state.major_graph["entities"][st.session_state.pc_name] = st.session_state.major_graph["entities"].pop("主角")
        selected_file = st.selectbox("切换历史会话", chat_files, index=chat_files.index(st.session_state.current_file))
        if selected_file != st.session_state.current_file:
            st.session_state.current_file = selected_file
            # 增加解包 scene_index
            (st.session_state.memory, 
             st.session_state.history_archive, 
             st.session_state.active_scene,
             st.session_state.minor_npcs, 
             st.session_state.major_graph, 
             st.session_state.graveyard,
             st.session_state.director_directive, 
             st.session_state.scene_index,
             st.session_state.tension_history,      
             st.session_state.current_location,
             st.session_state.mechanics_log,
             st.session_state.sync_log,
             st.session_state.gm_memory,
             st.session_state.world_tier,
             st.session_state.pc_name
            ) = memory_manager.load_session(st.session_state.current_file)
            if st.session_state.pc_name != "主角":
                if "主角" in st.session_state.major_graph.get("entities", {}):
                    # 将旧的面板数据提取出来，赋予新的自定义名字，并删掉旧的 "主角"
                    st.session_state.major_graph["entities"][st.session_state.pc_name] = st.session_state.major_graph["entities"].pop("主角")

    st.write("---")
    st.subheader("外置记忆库")
    new_memory = st.text_area("全局背景/长期设定", value=st.session_state.memory, height=300)
    if new_memory != st.session_state.memory:
        st.session_state.memory = new_memory
        trigger_save()
        
    st.write("---")
    st.subheader(f"导演系统与舞台控制 (当前第 {st.session_state.scene_index} 幕)")
    
    # 模式切换开关
    director_mode = st.radio("暗线选角模式", ["自动推演 (系统智能抽取)", "手动指定 (强制干预舞台)"], index=0)
    
    known_major_names = list(st.session_state.major_graph.get("entities", {}).keys())
    
    if director_mode == "手动指定 (强制干预舞台)":
        st.session_state.active_stage = st.multiselect(
            "选定【本幕常驻角色】（导演暗线将仅在这些人中产生）",
            options=known_major_names,
            default=st.session_state.get("active_stage", [])
        )
    else:
        st.session_state.active_stage = []
        st.caption("注：转场时系统将根据张力自动抽取NPC注入暗线。")
    
    # 🎬 核心按钮：结束当前幕并转场
# =============================================================================
#     if st.button("🎬 结束当前幕并转场", use_container_width=True):
#         if st.session_state.active_scene:
#             with st.spinner("结算本幕剧情与人物权重..."):
#                 try:
#                     # 1. 提炼当前幕
#                     extracted_data = core_engine.extract_memory_summary(st.session_state.active_scene, st.session_state.scene_index)
#                     
#                     # 2. 追加摘要，记录发生地点
#                     location = extracted_data.get("current_location", "未知区域")
#                     st.session_state.memory += f"\n\n[第{st.session_state.scene_index}幕摘要 | {location}]: {extracted_data['summary']}"
#                     
#                     # 3. 结算人物 (注意：这里必须传入完整的 extracted_data 和 scene_index)
#                     (st.session_state.minor_npcs, st.session_state.major_graph, 
#                      st.session_state.graveyard) = memory_manager.process_npc_updates(
#                         extracted_data, 
#                         st.session_state.minor_npcs,
#                         st.session_state.major_graph,
#                         st.session_state.graveyard,
#                         st.session_state.scene_index
#                     )
#                          
#                     # 生成下一幕暗线指令
#                     current_tension = extracted_data.get("current_tension", 5)
#                     st.session_state.director_directive = core_engine.generate_narrative_directive(
#                         current_tension, 
#                         st.session_state.major_graph,
#                         st.session_state.active_stage
#                     )
#                     
#                     # 4. 幕次自增与清空工作区 (向后推进的核心)
#                     st.session_state.scene_index += 1
#                     st.session_state.active_scene = []
#                     
#                     trigger_save() 
#                     st.success("转场完成！引擎上下文已清空，即将开启下一幕。")
#                 except Exception as e:
#                     st.error(f"提取结算失败: {e}")
#             st.rerun()
# =============================================================================

# 3. 主界面 UI
col_main, _ = st.columns([8, 2])

with col_main:
    for msg in st.session_state.history_archive:
        with st.chat_message(msg["role"]): 
            st.write(msg["content"])

user_input = st.chat_input("输入内容...")

is_transition = st.toggle("本轮输入作为【幕间结语】并触发转场结算", value=st.session_state.get("transition_active", False))

render_sidebar_panel(st.session_state.major_graph)

if user_input:
    if not st.session_state.current_file:
        st.error("请先新建或选择一个会话。")
        st.stop()

    with col_main:
        with st.chat_message("user"): 
            st.write(user_input)
            
    st.session_state.history_archive.append({"role": "user", "content": user_input})
    st.session_state.active_scene.append({"role": "user", "content": user_input})
    trigger_save()

    with col_main:
        with st.chat_message("assistant"):
            try:
                # ==========================================
                # 【最高优先级分流】：检测是否开启了转场开关
                # ==========================================
                if is_transition:
                    context_text = core_engine.build_context(
                        st.session_state.memory,
                        st.session_state.active_stage,
                        user_input,  
                        st.session_state.major_graph,
                        st.session_state.minor_npcs,
                        st.session_state.director_directive
                    )
                    # 强注入转场落幕指令
                    context_text += "\n【最高指令】：玩家已提供本幕最终结语。请以此结语为基础为本幕收尾，渲染一段客观的幕落、场景淡出或时空转场描写，为该阶段剧情正式画上句号。"
                    
                    # 使用 PRO 模型流式渲染最终演变
                    stream = core_engine.generate_chat_stream(context_text, st.session_state.active_scene)
                    text_placeholder = st.empty()
                    assistant_reply = ""
                    for chunk in stream:
                        assistant_reply += chunk
                        text_placeholder.markdown(assistant_reply + "▌")
                    text_placeholder.markdown(assistant_reply)
                    
                    # 记录最终回复
                    st.session_state.history_archive.append({"role": "assistant", "content": assistant_reply})
                    st.session_state.active_scene.append({"role": "assistant", "content": assistant_reply})
                    
            
                    # 幕落渲染完毕，执行后台静默数据更新
                    with st.spinner("正在清算本幕图谱数据..."):
                        summary_data = core_engine.extract_memory_summary(st.session_state.active_scene, st.session_state.scene_index)
                        
                        # 1. 更新地点
                        st.session_state.current_location = summary_data.get("current_location", "未知区域")
                        
                        # 2. 维护张力滑动窗口 (保留最近3幕的分数)
                        new_tension = summary_data.get("current_tension", 0)
                        if "tension_history" not in st.session_state:
                            st.session_state.tension_history = []
                        st.session_state.tension_history.append(new_tension)
                        if len(st.session_state.tension_history) > 3:
                            st.session_state.tension_history.pop(0) # 踢掉最老的分数
                        
                        history = st.session_state.tension_history
                        
                        # 3. 生成宏观导演指令
                        if len(history) == 3 and min(history) >= 7:
                            st.session_state.director_directive = "【剧本导演指令-宏观调和】：连续高强度冲突已使角色疲惫。下一幕强制进入低张力的喘息期，请放缓节奏，专注情报整理、伤情处理或温和的日常羁绊互动，绝对禁止新的致命威胁出现。"
                        elif len(history) == 3 and max(history) <= 3:
                            st.session_state.director_directive = "【剧本导演指令-宏观调和】：剧情已平淡过久。下一幕请强制撕裂平静，突然引入致命的物理威胁、暴露隐藏的内鬼或爆发激烈的阵营冲突，必须将戏剧张力拉满。"
                        else:
                            # 正常单步反馈
                            if new_tension >= 8:
                                st.session_state.director_directive = "【剧本导演指令-高危阶段】：当前处于冲突爆发点。请加快叙事节奏，着重刻画压迫感，逼迫玩家做出高风险决断。"
                            elif new_tension >= 5:
                                st.session_state.director_directive = "【剧本导演指令-暗流涌动】：维持悬疑与博弈感，通过NPC微表情或环境细节暗示危机，促使玩家谨慎布局。"
                            else:
                                st.session_state.director_directive = "【剧本导演指令-情报缓冲】：节奏放缓，侧重世界观铺垫与文戏互动，给玩家空间消化情报。"

                        # 4. 更新全局记忆
                        st.session_state.memory += f"\n[第{st.session_state.scene_index}幕摘要 | {st.session_state.current_location}]: {summary_data.get('summary', '')}"
                        
                        # 5. 融合图谱
                        st.session_state.minor_npcs, st.session_state.major_graph, st.session_state.graveyard = memory_manager.process_npc_updates(
                            summary_data,
                            st.session_state.minor_npcs,
                            st.session_state.major_graph,
                            st.session_state.graveyard,
                            st.session_state.scene_index
                        )
                    
                    # 步进时空，物理清空活跃场景
                    st.session_state.scene_index += 1
                    st.session_state.active_scene = st.session_state.active_scene[-3:]
                    st.session_state.transition_active = False
                    trigger_save()
                    st.toast("幕间转场成功，已进入新一幕！")
                    st.rerun()
                    
                # ==========================================
                # 【常规流程】：常规对话与动作拦截分流
                # ==========================================
                else:
                    with st.spinner("系统判定意图中..."):
                        intent = core_engine.detect_action_intent(
                            user_input, 
                            st.session_state.active_scene, 
                            st.session_state.pc_name,
                            st.session_state.major_graph  # 【新增传参】
                        )
                    
                    st.session_state.last_intent_json = intent
                    
                    if intent.get("is_action"):
                        action_type = intent.get("action_category")
                        initiator = intent.get("initiator_entity", "主角")
                        ability = intent.get("detected_ability")
                        target = intent.get("target_entity")
                        target_ongoing = intent.get("target_ongoing_action")
                        
                       
                        sync_target = target if (target and target != "None") else initiator
                        
                       # ----------------- 【核心修复：双轨能力雷达】 -----------------
                        init_ability_str = f"【{ability}】" if ability and ability != "None" else "【基础动作】"
                        target_ability_str = f"【{target_ongoing}】" if target_ongoing and target_ongoing != "None" else "【自然承受/基础防卫】"
                        
                        st.warning(
                            f"⚔️ 机制行为 ({action_type}) \n\n"
                            f"**发起方**：{initiator} ➔ 使用能力：{init_ability_str} \n\n"
                            f"**对抗方**：{target or '环境'} ➔ 应对招式：{target_ability_str}"
                        )
                        # ------------------------------------------------------------
                        
                        with st.spinner("战前雷达扫描与面板推演..."):
                            # 1. 扫描检测并初始化发起方实体
                            st.session_state.major_graph = core_engine.init_npc_combat_stats(
                                initiator, st.session_state.active_scene, st.session_state.major_graph, st.session_state.world_tier
                            )
                            # 2. 扫描检测并初始化对抗方实体
                            st.session_state.major_graph = core_engine.init_npc_combat_stats(
                                target, st.session_state.active_scene, st.session_state.major_graph, st.session_state.world_tier
                            )

                        system_injection = core_engine.resolve_action_mechanics(
                            action_type, 
                            ability, 
                            initiator, 
                            target, 
                            target_ongoing,
                            st.session_state.major_graph,
                            st.session_state.gm_memory,
                            st.session_state.world_tier,
                            intent.get("initiator_matched_assets", []),
                            intent.get("target_matched_assets", [])
                        )
                        
                    
                        
                        context_text = core_engine.build_context(
                            st.session_state.memory,
                            st.session_state.active_stage,
                            user_input,  
                            st.session_state.major_graph,
                            st.session_state.minor_npcs,
                            st.session_state.director_directive
                        )
                        context_text += system_injection
                    else:
                        context_text = core_engine.build_context(
                            st.session_state.memory,
                            st.session_state.active_stage,
                            user_input,  
                            st.session_state.major_graph,
                            st.session_state.minor_npcs,
                            st.session_state.director_directive
                        )
                    
                    stream = core_engine.generate_chat_stream(context_text, st.session_state.active_scene)
                    text_placeholder = st.empty()
                    assistant_reply = ""
                    for chunk in stream:
                        assistant_reply += chunk
                        text_placeholder.markdown(assistant_reply + "▌")
                    text_placeholder.markdown(assistant_reply)

                    status_match = re.search(r'<STATUS_UPDATE:\s*(.+?)>', assistant_reply)
                    if status_match:
                        sync_target = status_match.group(1).strip()
                        # 从文本中物理抹除标记，维护玩家沉浸感
                        assistant_reply = re.sub(r'<STATUS_UPDATE:\s*(.+?)>', '', assistant_reply).strip()
                        text_placeholder.markdown(assistant_reply)
                        
                        with st.spinner("系统感知到剧情突变，动态图谱落盘中..."):
                            # 【核心修改】：将用户输入作为前缀拼给算子，强行提醒大模型：玩家这回合说他学了新武功！
                            perceived_text = f"【玩家声明动作】：{user_input}\n【剧情演变结果】：{assistant_reply}"
                            st.session_state.major_graph, raw_json = core_engine.sync_dynamic_status(
                                perceived_text, sync_target, st.session_state.major_graph, st.session_state.pc_name # 【新增传参】
                            )
                            if raw_json:
                                st.session_state.sync_log.append({
                                    "scene": st.session_state.scene_index,
                                    "target": sync_target,
                                    "changes": raw_json
                                })
                        st.toast(f"角色 {sync_target} 身心状态已同步")

                    elif intent.get("is_action"):
                        with st.spinner("战后伤情与状态落盘中..."):
                            # 【核心修复】：必须用两个变量接收，防止 major_graph 变成元组
                            st.session_state.major_graph, raw_json_combat = core_engine.sync_dynamic_status(
                                    assistant_reply, target, st.session_state.major_graph, st.session_state.pc_name
                                )
                            # 顺手把战后状态也记入你的新日志系统
                            if raw_json_combat:
                                st.session_state.sync_log.append({
                                    "scene": st.session_state.scene_index,
                                    "target": target,
                                    "changes": raw_json_combat
                                })
                            
                            st.session_state.mechanics_log.append({
                                "scene": st.session_state.scene_index,
                                "action": action_type,
                                "target": f"{initiator} -> {target or '环境'}",
                                "log": system_injection,
                                "raw_intent": intent  # 【新增】：将意图拦截器的原始 JSON 成果永久落盘
                            })
                        st.toast("角色身心状态已根据战斗结果同步！")

                    st.session_state.history_archive.append({"role": "assistant", "content": assistant_reply})
                    st.session_state.active_scene.append({"role": "assistant", "content": assistant_reply})
                    trigger_save()
                    
            except Exception as e:
                # st.error(f"生成失败: {e}")
                st.exception(e)
                st.session_state.history_archive.pop()
                st.session_state.active_scene.pop()
                trigger_save()
# 确保在文件最底部追加此段代码，处理弹窗的根节点渲染
if st.session_state.get("show_settings", False):
    settings_dialog()