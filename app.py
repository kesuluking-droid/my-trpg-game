# =============================================================================
# 【沙盒版本】sandbox_app.py
# 基于 app.py 的沙盒分支版本
# 核心变更：常规回合的 else 分支已替换为 sandbox_core_engine 语义意图解析
# 转场逻辑、登录注册、设置面板、侧边栏等其余代码完全保持原样
# =============================================================================

import streamlit as st

st.set_page_config(page_title="kesuluking-RPG", layout="wide")
st.title("Kesuluking-RPG")


import datetime
import re
import memory_manager as memory_manager
import core_engine as core_engine
import undo_manager as undo_manager
from ui_feedback import get_friendly_status_text
import copy
import json
import base64
from pathlib import Path


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
    "3_capabilities": {
        "基础行动": {"base_power": 10, "mastery_level": 1.0, "domains": ["通用", "徒手", "本能"], "features": ["无需训练的本能动作"]},
        "本能闪避": {"base_power": 12, "mastery_level": 1.0, "domains": ["防御", "身法", "本能"], "features": ["下意识的躲闪反应"]}
    },
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
if "world_category" not in st.session_state:
    st.session_state.world_category = "异能" # 默认大类
if "world_tier" not in st.session_state:
    st.session_state.world_tier = DEFAULT_WORLD_TIER
if "last_scaled_tier" not in st.session_state:
    st.session_state.last_scaled_tier = st.session_state.get("world_tier", DEFAULT_WORLD_TIER)
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
if "next_scene_hook" not in st.session_state:
    st.session_state.next_scene_hook = ""
if "last_interlude_debug" not in st.session_state:
    st.session_state.last_interlude_debug = ""
if "transition_toggle_nonce" not in st.session_state:
    st.session_state.transition_toggle_nonce = 0
if "user_api_key" not in st.session_state:
    st.session_state.user_api_key = ""
if "show_control_settings" not in st.session_state:
    st.session_state.show_control_settings = False
if "api_intro_shown" not in st.session_state:
    st.session_state.api_intro_shown = False
if "dev_debug_mode" not in st.session_state:
    st.session_state.dev_debug_mode = False
if "dev_debug_confirming" not in st.session_state:
    st.session_state.dev_debug_confirming = False
if "active_stage" not in st.session_state:
    st.session_state.active_stage = []

if not st.session_state.user_api_key and not st.session_state.api_intro_shown:
    st.session_state.show_control_settings = True
    st.session_state.api_intro_shown = True

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

@st.dialog("🌍 新世界")
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
        st.session_state.edit_world_memory = st.session_state.memory
        st.session_state.dialog_initialized = True

    tab1, tab2, tab3, tab4 = st.tabs(["基本与状态", "初始能力", "先天特质", "初始背包"])

    with tab1:
        # 🟢 新增：7大类强制约束选单
        categories = ["修仙", "魔法", "武侠", "异能", "现实", "科幻", "其他"]
        cat_index = categories.index(st.session_state.world_category) if st.session_state.world_category in categories else 3
        new_category = st.selectbox("世界观大类", categories, index=cat_index)

        # 保留原有 tier 变量接收具体设定
        new_tier = st.text_input("具体世界观定调 (修改此项将触发跨界法则演算)", value=st.session_state.world_tier)
        new_pc_name = st.text_input("主角姓名", value=st.session_state.pc_name)
        new_desc = st.text_area("主角背景描述", value=st.session_state.pc_template.get("desc", "世界的变数"))
        st.text_area("📚 世界记忆", key="edit_world_memory", height=160, help="记录长期背景、世界规则、主角过往等。")

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

                # 只暂存新世界草稿，不写入当前世界，避免污染旧世界存档。
                template = copy.deepcopy(st.session_state.pc_template)
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

                st.session_state.pending_world_config = {
                    "world_category": new_category,
                    "world_tier": new_tier,
                    "pc_name": new_pc_name,
                    "memory": st.session_state.get("edit_world_memory", ""),
                    "pc_template": template,
                }

                st.session_state.settings_saved_status = True
                st.session_state.show_settings = True
                st.toast("新世界设定已暂存，尚未影响当前世界")
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
            pending_world = st.session_state.get("pending_world_config", {})
            applied_pc_template = copy.deepcopy(pending_world.get("pc_template", st.session_state.pc_template))

            st.session_state.world_category = pending_world.get("world_category", st.session_state.world_category)
            st.session_state.world_tier = pending_world.get("world_tier", st.session_state.world_tier)
            st.session_state.pc_name = pending_world.get("pc_name", st.session_state.pc_name)
            st.session_state.memory = pending_world.get("memory", "")
            st.session_state.pc_template = applied_pc_template

            new_file = f"chat_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            st.session_state.current_file = new_file
            st.session_state.active_scene = []
            st.session_state.history_archive = []
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
                "entities": {st.session_state.pc_name: copy.deepcopy(applied_pc_template)},
                "relations": []
            }

            trigger_save()

            st.session_state.settings_saved_status = False
            st.session_state.show_settings = False
            if "pending_world_config" in st.session_state:
                del st.session_state.pending_world_config
            if "dialog_initialized" in st.session_state:
                del st.session_state.dialog_initialized

            st.toast("全新会话已开启")
            st.rerun()


@st.dialog("⚙️ 设置")
def control_settings_dialog():
    st.markdown("### 🔑 DeepSeek API 设置")
    st.caption("本游戏使用玩家自己的 DeepSeek API Key 调用模型。Key 仅保存在当前浏览器会话中，本平台不进行任何收费。")
    st.markdown("- 官方平台：[platform.deepseek.com](https://platform.deepseek.com/)")
    st.markdown("- API Key 页面：[platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys)")
    st.info("参考消耗：100次对话≈1元RMB(仅用于API调用)。建议首次试水充值不超过10元。")
    st.markdown("- 项目仓库 / 本地部署：[github.com/kesuluking-droid/my-trpg-game](https://github.com/kesuluking-droid/my-trpg-game)")

    api_input = st.text_input(
        "DeepSeek API Key",
        value=st.session_state.get("user_api_key", ""),
        type="password",
        placeholder="sk-...",
        help="请在此处粘贴您的 DeepSeek 官方 API 密钥"
    )
    if api_input:
        if not api_input.startswith("sk-"):
            st.error("⚠️ 请输入标准 DeepSeek API Key（以 sk- 开头）。")
        else:
            st.session_state.user_api_key = api_input
            st.success("✅ DeepSeek API 已挂载。")
    else:
        st.warning("🛑 当前未检测到 API Key，游戏无法调用模型。")

    st.divider()
    st.markdown("### 🪽 上帝模式")
    if st.session_state.get("creative_mode", False):
        if st.button("🪽 关闭归还上帝权柄", use_container_width=True):
            st.session_state.creative_mode = False
            st.session_state.show_control_settings = True
            st.rerun()
    else:
        if st.button("🪽 开启获取上帝权柄", use_container_width=True):
            st.session_state.creative_mode = True
            st.session_state.show_control_settings = True
            st.rerun()

    st.divider()
    st.markdown("### 🧭 世界法则")
    st.caption("根据当前具体世界观重新生成或载入威力表，并可能自动匹配世界观大类。")
    if st.button("🧭 重载世界观威力表", type="secondary", use_container_width=True):
        with st.spinner("正在重载世界法则并重塑资产..."):
            success, anchor_data, updated_graph, msg = core_engine.sync_world_anchor_and_scale(
                category=st.session_state.get("world_category", "异能"),
                new_setting_name=st.session_state.world_tier,
                old_setting_name=st.session_state.get("last_scaled_tier"),
                major_graph=st.session_state.major_graph
            )
            if success:
                st.session_state.major_graph = updated_graph
                st.session_state.last_scaled_tier = st.session_state.world_tier
                trigger_save()
                st.success(f"重载成功: {msg}")
            else:
                st.error(f"重载失败: {msg}")

    st.divider()
    st.markdown("### 🧪 开发者调试模式")
    if st.session_state.get("dev_debug_mode", False):
        if st.button("🧪 关闭开发者调试模式", use_container_width=True):
            st.session_state.dev_debug_mode = False
            st.session_state.dev_debug_confirming = False
            st.session_state.show_control_settings = True
            st.rerun()
    else:
        if not st.session_state.get("dev_debug_confirming", False):
            if st.button("🧪 开启开发者调试模式", use_container_width=True):
                st.session_state.dev_debug_confirming = True
                st.session_state.show_control_settings = True
                st.rerun()
        else:
            st.warning("可能包含高度剧透风险，确定要开启吗？")
            c1, c2 = st.columns(2)
            if c1.button("确认开启", use_container_width=True):
                st.session_state.dev_debug_mode = True
                st.session_state.dev_debug_confirming = False
                st.session_state.show_control_settings = True
                st.rerun()
            if c2.button("取消", use_container_width=True):
                st.session_state.dev_debug_confirming = False
                st.session_state.show_control_settings = True
                st.rerun()

    st.divider()
    if st.button("关闭设置", use_container_width=True):
        st.session_state.show_control_settings = False
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
        st.session_state.pc_name,
        _get_undo_stack()
    )


def _get_undo_stack() -> list:
    """获取当前会话专属的撤回栈。"""
    key = f"undo_stack_{st.session_state.current_file}"
    return st.session_state.setdefault(key, [])

def _set_undo_stack(stack: list):
    """设置当前会话专属的撤回栈。"""
    key = f"undo_stack_{st.session_state.current_file}"
    st.session_state[key] = stack


def save_undo_snapshot():
    """捕获当前状态作为后悔药 before，不再写入全量快照。"""
    st.session_state["_undo_before_state"] = undo_manager.capture_undo_state(st.session_state)


def commit_undo_snapshot(label="后悔药"):
    """回合成功提交后，生成反向增量 patch 并写入撤回栈。"""
    before = st.session_state.pop("_undo_before_state", None)
    if before is None:
        return
    after = undo_manager.capture_undo_state(st.session_state)
    entry = undo_manager.build_inverse_patch(before, after, label=label)
    if not entry.get("patches"):
        return
    undo_stack = _get_undo_stack()
    undo_stack.append(entry)
    if len(undo_stack) > 20:
        del undo_stack[:len(undo_stack) - 20]
    _set_undo_stack(undo_stack)


def undo_last_turn():
    """撤回到上一步 AI 回复后的状态。"""
    undo_stack = _get_undo_stack()
    if not undo_stack:
        st.toast("没有可撤回的步骤")
        return False

    entry = undo_stack.pop()
    _set_undo_stack(undo_stack)
    if undo_manager.is_patch_undo(entry):
        undo_manager.apply_inverse_patch(st.session_state, entry)
    else:
        undo_manager.restore_legacy_snapshot(st.session_state, entry)
    trigger_save()
    return True


def _tier_label(value, table="generic"):
    """把内部乘数转换为普通玩家可读的五档描述。"""
    try:
        v = float(value)
    except Exception:
        v = 1.0

    if table == "experience":
        labels = ["生疏", "略有心得", "熟练可靠", "经验丰富", "登峰造极"]
    elif table == "rarity":
        labels = ["随处可见", "较为常见", "标准可靠", "稀有珍贵", "传说级"]
    else:
        labels = ["明显受限", "略显不足", "状态稳定", "表现突出", "超常发挥"]

    if v < 0.5:
        return labels[0]
    if v < 0.8:
        return labels[1]
    if v <= 1.25:
        return labels[2]
    if v <= 2.0:
        return labels[3]
    return labels[4]


def _format_features(data):
    features = data.get("features", []) if isinstance(data, dict) else []
    return f"：{'、'.join(features)}" if features else ""

def render_sidebar_panel(major_graph):
    """侧边栏六维数据实时可视化面板"""

    with st.sidebar:
        entities = major_graph.get("entities", {})
        if not entities:
            st.info("暂无核心角色数据")
            return
        dev_mode = st.session_state.get("dev_debug_mode", False)

        # 1. 主角面板（置顶并强制展开）
        current_pc_name = st.session_state.get("pc_name", "主角")
        if current_pc_name in entities:
            pc = entities[current_pc_name]
            with st.expander(f"{current_pc_name}状态", expanded=True):
                # 身心状态
                status = pc.get("2_dynamic_status", {})
                p_obj = status.get("physical", {})
                m_obj = status.get("mental", {})
                if dev_mode:
                    st.markdown(f"**身体状态**: {p_obj.get('desc', '正常')} `x{p_obj.get('multiplier', 1.0)}`")
                    st.markdown(f"**心理状态**: {m_obj.get('desc', '正常')} `x{m_obj.get('multiplier', 1.0)}`")
                else:
                    st.markdown(f"**身体状态**: {p_obj.get('desc', '正常')}（{_tier_label(p_obj.get('multiplier', 1.0))}）")
                    st.markdown(f"**心理状态**: {m_obj.get('desc', '正常')}（{_tier_label(m_obj.get('multiplier', 1.0))}）")

                # 【新增】：侧边栏实时渲染经验系数
                exp_data = pc.get("4_experience_factors", {})
                if dev_mode:
                    st.markdown(f"**通用战斗经验**: `x{exp_data.get('general_combat', 1.0)}`")
                else:
                    st.markdown(f"**经验值**: {_tier_label(exp_data.get('general_combat', 1.0), 'experience')}")
                spec_exp = exp_data.get("specific_match", {})
                if spec_exp:
                    spec_exp_str = ", ".join([f"{k}:x{v}" if dev_mode else f"{k}:{_tier_label(v, 'experience')}" for k, v in spec_exp.items()])
                    st.markdown(f"**特定功法经验**: {spec_exp_str}")

                st.divider()

                # 能力
                caps = pc.get("3_capabilities", {})
                if caps:
                    st.markdown("**掌握能力**:")
                    for k, v in caps.items():
                        if dev_mode:
                            feats_str = f" [{', '.join(v.get('features', []))}]" if v.get("features") else ""
                            st.markdown(f"- {k} (基础:{v.get('base_power', 10)} 熟练:{v.get('mastery_level', 1.0)}){feats_str}")
                        else:
                            st.markdown(f"- {k}{_format_features(v)}")

                # 特质
                traits = pc.get("5_traits", [])
                if traits:
                    st.markdown("**固有特质**:")
                    for t in traits:
                        if dev_mode:
                            feats_str = f" [{', '.join(t.get('features', []))}]" if isinstance(t, dict) and t.get("features") else ""
                            st.markdown(f"- {t.get('name', '未定义')}(x{t.get('multiplier', 1.0)}){feats_str}")
                        else:
                            st.markdown(f"- {t.get('name', '未定义')}（{_tier_label(t.get('multiplier', 1.0))}）{_format_features(t)}")

                # 物品
                inv = pc.get("6_inventory", {})
                if inv:
                    st.markdown("**背包物品**:")
                    for k, v in inv.items():
                        mult = v.get("multiplier", 1.0) if isinstance(v, dict) else 1.0
                        quantity = v.get("quantity") if isinstance(v, dict) else None
                        qty_str = f" ×{quantity}" if quantity is not None else ""
                        if dev_mode:
                            feats_str = f" [{', '.join(v.get('features', []))}]" if isinstance(v, dict) and v.get("features") else ""
                            st.markdown(f"- {k}{qty_str}(x{mult}){feats_str}")
                        else:
                            st.markdown(f"- {k}{qty_str}（稀有度：{_tier_label(mult, 'rarity')}）{_format_features(v) if isinstance(v, dict) else ''}")

        # 2. 其他核心NPC面板（默认折叠）
        st.subheader("遇到的人")
        current_pc_name = st.session_state.get("pc_name", "主角")
        for name, data in entities.items():
            # 物理对齐动态更名，防止改名后的主角在这里重复暴露
            if name == current_pc_name:
                continue
            with st.expander(f"{name}", expanded=False):
                note_key = f"npc_private_note_{st.session_state.current_file}_{name}"
                note_value = data.get("private_note", "")
                new_note = st.text_area("可以在这里记下我对其的印象：", value=note_value, key=note_key, height=100)
                if new_note != note_value:
                    data["private_note"] = new_note
                    trigger_save()

                if not dev_mode:
                    continue

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

        if st.session_state.get("dev_debug_mode", False):
            st.divider()
            with st.expander("🎬 开发者：幕间推进调试", expanded=False):
                st.text_area("最近一次幕间推进/下一幕钩子", value=st.session_state.get("last_interlude_debug", ""), height=160)

            with st.expander("🛠️ 开发者：后台检定日志 (黑匣子)", expanded=False):
                logs = st.session_state.get("mechanics_log", [])
                if not logs:
                    st.caption("暂无机制检定记录")
                else:
                    for entry in reversed(logs[-10:]):
                        if isinstance(entry, dict) and "scene" in entry:
                            st.markdown(f"**[第{entry['scene']}幕] {entry.get('action', '未知')} -> {entry.get('target', '未知')}**")
                            st.text(entry.get('log', '').strip())
                            if "raw_intent" in entry:
                                st.caption("🤖 意图拦截器原始判定快照：")
                                st.json(entry["raw_intent"])
                        else:
                            st.caption(f"脏数据物理隔离 (检定): {str(entry)}")
                        st.write("---")

            with st.expander("🧬 开发者：后台状态/资产变更日志", expanded=False):
                sync_logs = st.session_state.get("sync_log", [])
                if not sync_logs:
                    st.caption("暂无状态或资产变更记录")
                else:
                    for entry in reversed(sync_logs[-10:]):
                        if isinstance(entry, dict) and "scene" in entry:
                            st.markdown(f"**[第{entry['scene']}幕] 实体: {entry.get('target', '未知')}**")
                            st.json(entry.get('changes', {}))
                        else:
                            st.caption(f"脏数据物理隔离: {str(entry)}")
                        st.write("---")

# 2. 侧边栏 UI
with st.sidebar:
    solo_icon_path = Path(__file__).with_name("solo_icon.png")
    if solo_icon_path.exists():
        solo_icon_b64 = base64.b64encode(solo_icon_path.read_bytes()).decode("utf-8")
        st.markdown(f"""
        <style>
        .solo-line-wrap {{
            position: relative;
            display: inline-block;
            cursor: default;
        }}
        .solo-sign-card {{
            visibility: hidden;
            opacity: 0;
            position: absolute;
            z-index: 9999;
            left: 0;
            top: 1.8em;
            width: 230px;
            padding: 10px 12px;
            border-radius: 12px;
            background: rgba(35, 24, 58, 0.96);
            color: #f4edff;
            box-shadow: 0 8px 24px rgba(72, 38, 125, 0.35);
            transition: opacity 0.16s ease;
            font-size: 13px;
        }}
        .solo-line-wrap:hover .solo-sign-card {{
            visibility: visible;
            opacity: 1;
        }}
        .solo-sign-card img {{
            width: 24px;
            height: 24px;
            border-radius: 50%;
            vertical-align: middle;
            margin-right: 6px;
        }}
        </style>
        <div class="solo-line-wrap">
            🕯️ 在这里，世界线会记住你的选择。
            <div class="solo-sign-card">
                <img src="data:image/png;base64,{solo_icon_b64}" />
                <strong>—— SOLO</strong><br />
                于世界线旁
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("<span title='🟣 SOLO留：愿每条世界线都有回响' style='text-decoration: none; cursor: default;'>🕯️ 在这里，世界线会记住你的选择。</span>", unsafe_allow_html=True)
    chat_files = memory_manager.get_chat_files()

    if st.button("🌍 新世界", type="primary", use_container_width=True, help="创建或重塑一个新的世界线，设定世界观、主角身份、初始能力与背包。"):
        st.session_state.show_settings = True
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
             st.session_state.pc_name,
             loaded_undo_stack
            ) = memory_manager.load_session(st.session_state.current_file)
            _set_undo_stack(loaded_undo_stack)
            if st.session_state.pc_name != "主角":
                if "主角" in st.session_state.major_graph.get("entities", {}):
                    # 将旧的面板数据提取出来，赋予新的自定义名字，并删掉旧的 "主角"
                    st.session_state.major_graph["entities"][st.session_state.pc_name] = st.session_state.major_graph["entities"].pop("主角")

        with st.expander("📝 世界赐名"):
            st.caption("修改世界的名字")
            current_pure_name = st.session_state.current_file.replace(".json", "")
            new_session_name = st.text_input("输入新的世界名", value=current_pure_name, key="rename_input")

            if st.button("📝 确认赐名", use_container_width=True):
                if new_session_name.strip() != current_pure_name:
                    old_file = st.session_state.current_file
                    success, result = core_engine.rename_user_session(old_file, new_session_name)
                    if success:
                        # 迁移 undo_stack 到新的 key
                        old_key = f"undo_stack_{old_file}"
                        new_key = f"undo_stack_{result}"
                        if old_key in st.session_state:
                            st.session_state[new_key] = st.session_state.pop(old_key)
                        st.session_state.current_file = result # 指针切到新文件
                        st.success("重命名成功！")
                        st.rerun()
                    else:
                        st.error(result)

        with st.expander("🗺️ 世界线变动"):
            st.caption("切换历史世界线")
            selected_file = st.selectbox("选择世界线", chat_files, index=chat_files.index(st.session_state.current_file))
            if selected_file != st.session_state.current_file:
                st.session_state.current_file = selected_file
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
                 st.session_state.pc_name,
                 loaded_undo_stack
                ) = memory_manager.load_session(st.session_state.current_file)
                _set_undo_stack(loaded_undo_stack)
                if st.session_state.pc_name != "主角" and "主角" in st.session_state.major_graph.get("entities", {}):
                    st.session_state.major_graph["entities"][st.session_state.pc_name] = st.session_state.major_graph["entities"].pop("主角")
                st.rerun()

        with st.expander("💥 世界线坍塌！"):
            st.caption("删除这条世界线。")
            st.warning("⚠️ 坍塌后，该世界线将永久消失，无法恢复！即使后悔药也无法挽回！")
            confirm_delete = st.checkbox("我已熟知风险，确认坍塌", key="del_confirm_check")

            if st.button("💥 确认世界线坍塌", use_container_width=True, disabled=not confirm_delete):
                success, msg = core_engine.delete_user_session(st.session_state.current_file)
                if success:
                    # 删除成功后，彻底清空当前内存，逼迫网页刷新后自动重新创建一个空剧本
                    st.session_state.current_file = ""
                    st.session_state.history_archive = []
                    st.session_state.active_scene = []
                    st.session_state.memory = ""
                    st.session_state.minor_npcs = {}
                    st.session_state.graveyard = {}
                    st.session_state.scene_index = 1
                    st.session_state.major_graph = {"entities": {st.session_state.pc_name: copy.deepcopy(DEFAULT_PC)}, "relations": []}
                    st.success("该世界线已被抹除！")
                    st.rerun()
                else:
                    st.error(msg)

    undo_count = len(_get_undo_stack())
    if st.button(f"💊 后悔药 ({undo_count})", use_container_width=True, disabled=undo_count == 0, help="撤回上一步"):
        if undo_last_turn():
            st.toast("已撤回到上一步")
            st.rerun()

    if st.button("⚙️ 设置", use_container_width=True):
        st.session_state.show_control_settings = True
        st.rerun()

    # 导演系统与舞台控制 UI 已隐藏。保留 active_stage 底层变量，默认不强制抓取角色。
    st.session_state.active_stage = []


# 3. 主界面 UI
col_main, _ = st.columns([8, 2])

with col_main:
    for msg in st.session_state.history_archive:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

user_input = st.chat_input("输入内容...")

# 幕间结语和 AI 建议在同一行，幕间结语占 1/5
_row = st.container()
with _row:
    _c1, _c2 = st.columns([1, 4])
    with _c1:
        is_transition = st.toggle("幕间结语", value=False, key=f"transition_active_{st.session_state.transition_toggle_nonce}", help="开启后本轮输入将作为幕间结语并触发转场结算")
    with _c2:
        if "ai_suggest_enabled" not in st.session_state:
            st.session_state.ai_suggest_enabled = False
        if "ai_suggestions" not in st.session_state:
            st.session_state.ai_suggestions = []
        st.session_state.ai_suggest_enabled = st.toggle("💡建议", value=st.session_state.ai_suggest_enabled, key="ai_suggest_toggle_persist_sandbox", help="开启后每轮生成行动建议")

# AI 建议气泡（紧凑）
if st.session_state.ai_suggest_enabled and st.session_state.ai_suggestions:
    cols = st.columns(len(st.session_state.ai_suggestions))
    for i, (summary, full_text) in enumerate(st.session_state.ai_suggestions):
        with cols[i]:
            if st.button(summary, key=f"suggest_sandbox_{i}", use_container_width=True):
                st.session_state._preview_suggestion = full_text

# 建议预览区（点击后显示，不直接发送）
if hasattr(st.session_state, '_preview_suggestion') and st.session_state._preview_suggestion:
    preview_text = st.session_state._preview_suggestion
    col_preview, col_copy, col_cancel, col_send = st.columns([5, 1, 1, 1])
    with col_preview:
        st.info(f"📝 {preview_text}")
    with col_copy:
        if st.button("📋", key="copy_preview_sandbox", help="复制到剪贴板"):
            import streamlit.components.v1 as components
            _escaped = preview_text.replace("\\", "\\\\").replace("`", "\\`")
            components.html(f"<script>navigator.clipboard.writeText(`{_escaped}`);</script>", height=0)
            st.toast("已复制到剪贴板")
    with col_cancel:
        if st.button("✖", key="cancel_preview_sandbox"):
            del st.session_state._preview_suggestion
            st.rerun()
    with col_send:
        if st.button("发送", key="send_preview_sandbox"):
            user_input = preview_text
            del st.session_state._preview_suggestion

render_sidebar_panel(st.session_state.major_graph)

if user_input:
    if not st.session_state.current_file:
        st.error("请先新建或选择一个会话。")
        st.stop()

    with col_main:
        with st.chat_message("user"):
            st.write(user_input)

    # 在玩家输入写入之前保存快照（撤回时恢复到此状态，即上一步 AI 回复后）
    save_undo_snapshot()

    st.session_state.history_archive.append({"role": "user", "content": user_input})
    st.session_state.active_scene.append({"role": "user", "content": user_input})
    trigger_save()

    with col_main:
        with st.chat_message("assistant"):
            try:
                status_box = st.empty()

                def show_turn_status(stage):
                    status_box.info(get_friendly_status_text(stage))

                # ==========================================
                # 【最高优先级分流】：检测是否开启了转场开关
                # ==========================================
                if is_transition:
                    # 转场叙事生成前先完成世界法则同步。
                    # 否则 PRO 叙事会使用旧世界观，而 FLASH 建表/跨界缩放在叙事后才生效，造成时序污染。
                    if st.session_state.world_tier != st.session_state.get("last_scaled_tier"):
                        with st.spinner("正在预同步新世界法则..."):
                            success, anchor_data, updated_graph, msg = core_engine.sync_world_anchor_and_scale(
                                category=st.session_state.get("world_category", "异能"),
                                new_setting_name=st.session_state.world_tier,
                                old_setting_name=st.session_state.get("last_scaled_tier"),
                                major_graph=st.session_state.major_graph
                            )
                            if success:
                                st.session_state.major_graph = updated_graph
                                st.session_state.last_scaled_tier = st.session_state.world_tier
                                st.toast(f"新世界法则预同步完成: {msg}")
                            else:
                                st.error(f"世界重塑失败，请稍后手动点击重载按钮。原因: {msg}")
                    context_text = core_engine.build_context(
                        st.session_state.memory,
                        st.session_state.active_stage,
                        user_input,
                        st.session_state.major_graph,
                        st.session_state.minor_npcs,
                        st.session_state.director_directive
                    )
                    if st.session_state.get("next_scene_hook"):
                        context_text += f"\n【下一幕开场钩子】{st.session_state.next_scene_hook}\n请自然承接该钩子推进剧情，不要直接宣告这是系统钩子。"
                        st.session_state.next_scene_hook = ""
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

                    # AI 建议：每轮对话后生成新建议
                    if st.session_state.ai_suggest_enabled:
                        st.session_state.ai_suggestions = core_engine.generate_ai_suggestions(
                            st.session_state.active_scene,
                            st.session_state.major_graph,
                            st.session_state.pc_name,
                        )


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

                        # 4.5 幕间推进器 V1：复用幕间摘要 LLM 的结构化输出，不额外增加 API 调用。
                        interlude = summary_data.get("interlude_progression", {}) or {}
                        time_skip = str(interlude.get("time_skip", "")).strip()
                        progression = str(interlude.get("progression", "")).strip()
                        npc_moves = interlude.get("npc_moves", []) or []
                        next_hook = str(interlude.get("next_hook", "")).strip()
                        recommended_location = str(interlude.get("recommended_location", "")).strip()
                        tone = str(interlude.get("tone", "")).strip()

                        interlude_lines = []
                        if progression:
                            interlude_lines.append(progression)
                        if npc_moves:
                            interlude_lines.append("NPC幕间动作：" + "；".join([str(x) for x in npc_moves if str(x).strip()]))
                        if next_hook:
                            interlude_lines.append("下一幕钩子：" + next_hook)

                        if interlude_lines:
                            loc_for_interlude = recommended_location or st.session_state.current_location
                            interlude_debug_text = f"[第{st.session_state.scene_index}幕幕间推进 | {time_skip or '时间自然流逝'} | {loc_for_interlude} | {tone or '未定调'}]: " + " ".join(interlude_lines)
                            st.session_state.memory += "\n" + interlude_debug_text
                            st.session_state.last_interlude_debug = interlude_debug_text
                        if recommended_location:
                            st.session_state.current_location = recommended_location
                        if next_hook:
                            st.session_state.next_scene_hook = next_hook

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
                    st.session_state.transition_toggle_nonce += 1
                    commit_undo_snapshot(label=f"撤回第{st.session_state.scene_index}幕转场")
                    trigger_save()
                    st.toast("幕间转场成功，已进入新一幕！")
                    st.rerun()

                # ==========================================
                # 【常规流程】：常规对话与动作拦截分流
                # ==========================================
                else:
                    # ==========================================
                    # 【沙盒系统】：LLM 语义意图解析 + 旧系统多乘区检定
                    # ==========================================
                    context_text = core_engine.build_context(
                        st.session_state.memory,
                        st.session_state.active_stage,
                        user_input,
                        st.session_state.major_graph,
                        st.session_state.minor_npcs,
                        st.session_state.director_directive
                    )
                    if st.session_state.get("next_scene_hook"):
                        context_text += f"\n【下一幕开场钩子】{st.session_state.next_scene_hook}\n请自然承接该钩子推进剧情，不要直接宣告这是系统钩子。"
                        st.session_state.next_scene_hook = ""

                    st.session_state._last_user_input = user_input

                    result = core_engine.execute_sandbox_turn(
                        user_input,
                        st.session_state.active_scene,
                        context_text=context_text,
                        status_callback=show_turn_status,
                    )

                    # render_stream_and_commit 返回 (reply_text, need_rerun)
                    if isinstance(result, tuple):
                        assistant_reply, need_rerun = result
                    else:
                        assistant_reply, need_rerun = result, False

                    if assistant_reply:
                        st.session_state.history_archive.append({"role": "assistant", "content": assistant_reply})
                        st.session_state.active_scene.append({"role": "assistant", "content": assistant_reply})
                        show_turn_status("undo_commit")
                        commit_undo_snapshot(label=f"撤回第{st.session_state.scene_index}幕回合")
                        status_box.empty()
                        trigger_save()
                        # 每次成功回合后刷新，确保侧边栏/图谱用最新数据重绘
                        st.rerun()
                    else:
                        # 回滚玩家本条输入
                        if st.session_state.history_archive and st.session_state.history_archive[-1]["role"] == "user":
                            st.session_state.history_archive.pop()
                        if st.session_state.active_scene and st.session_state.active_scene[-1]["role"] == "user":
                            st.session_state.active_scene.pop()
                        st.session_state.pop("_undo_before_state", None)
                        status_box.empty()
                        trigger_save()

            except Exception as e:
                # st.error(f"生成失败: {e}")
                st.exception(e)

                # 🛡️ 【核心修复 3】：极其危险的物理 pop 阻断！
                # 以前这里无脑 pop，如果报错就会直接把玩家刚刚输入的对话给删掉，导致"莫名消失"！
                # 现在强行校验：只有最后一条明确是 user，且 assistant 还没加进去时，才能安全回退。
                if st.session_state.history_archive and st.session_state.history_archive[-1]["role"] == "user":
                    st.session_state.history_archive.pop()
                if st.session_state.active_scene and st.session_state.active_scene[-1]["role"] == "user":
                    st.session_state.active_scene.pop()

                st.session_state.pop("_undo_before_state", None)
                try:
                    status_box.empty()
                except Exception:
                    pass
                trigger_save()

# 确保在文件最底部追加此段代码，处理弹窗的根节点渲染
# 注意：st.dialog 关闭按钮不会触发我们的“关闭面板”按钮逻辑。
# 因此这里采用一次性消费 show_settings，避免每次 st.rerun 后自动重弹。
if st.session_state.get("show_settings", False):
    st.session_state.show_settings = False
    settings_dialog()

if st.session_state.get("show_control_settings", False):
    st.session_state.show_control_settings = False
    control_settings_dialog()
