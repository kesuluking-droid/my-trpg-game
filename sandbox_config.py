# -*- coding: utf-8 -*-
"""
sandbox_config.py — 沙盒版本配置

================================================================================
🔔 AI 助手维护提醒（每次修改前必读）
================================================================================

【沙盒版本绝对隔离原则】
- 本文件是 config.py 的 1:1 沙盒镜像副本
- 所有配置应与主版本保持一致，但可独立调整
- 沙盒修改不得污染主版本管线

【修改步骤】
1. 如需修改配置，先在此沙盒版本测试验证
2. 验证通过后，将修改实质迁移到主版本
3. 不要简单让主版本跳转到沙盒版本

【文件对应关系】
- sandbox_config.py ↔ config.py

================================================================================
"""

import os

# 目录配置
BASE_DIR = os.getcwd()

# API 与模型配置
MODEL_PRO = "deepseek-v4-pro"
MODEL_FLASH = "deepseek-v4-flash"
API_BASE_URL = "https://api.deepseek.com"

# 调试开关（核心！如果设为 True，将不消耗 Token，直接返回模拟文本）
DEBUG_MODE = False

# 账户与存档隔离配置
USER_DATA_FILE = os.path.join(BASE_DIR, "data", "users.json")
SAVE_DIR = os.path.join(BASE_DIR, "data", "saved_profiles")
