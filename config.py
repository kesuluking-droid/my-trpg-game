# -*- coding: utf-8 -*-
"""
Created on Mon May 25 15:34:11 2026

@author: kingbom
"""

import os

# 目录配置
BASE_DIR = os.getcwd()
HISTORY_DIR = os.path.join(BASE_DIR, "chat_history")

# API 与模型配置
MODEL_PRO = "deepseek-v4-pro"
MODEL_FLASH = "deepseek-v4-flash"
API_BASE_URL = "https://api.deepseek.com"

# 调试开关（核心！如果设为 True，将不消耗 Token，直接返回模拟文本）
DEBUG_MODE = False