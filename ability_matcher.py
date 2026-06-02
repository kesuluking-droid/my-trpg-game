# -*- coding: utf-8 -*-

"""
ability_matcher.py — 招式语义匹配引擎 (沙盒版本)

使用 sentence-transformers 本地计算向量相似度，替代字符串匹配。
零额外 API 调用，白盒可解释。

【设计原则】
- Python 算相似度，LLM 只负责叙事
- 阈值 0.9：折中精度，避免漏匹配和误匹配
- 懒加载：首次调用时才加载模型，避免启动拖慢
"""

from __future__ import annotations

import os
import logging

_logger = logging.getLogger(__name__)

# 全局模型实例（懒加载）
_model = None
_tokenizer = None


def _load_model():
    """懒加载 sentence-transformers 模型"""
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer

    try:
        from sentence_transformers import SentenceTransformer
        # 使用多语言小模型，适合中文招式匹配
        # paraphrase-multilingual-MiniLM-L12-v2: 多语言、轻量、384维
        model_name = "paraphrase-multilingual-MiniLM-L12-v2"
        cache_dir = os.path.join(os.path.dirname(__file__), ".models")

        _logger.info(f"正在加载语义匹配模型: {model_name}")
        _model = SentenceTransformer(model_name, cache_folder=cache_dir)
        _tokenizer = _model.tokenizer
        _logger.info("语义匹配模型加载完成")
        return _model, _tokenizer
    except ImportError:
        _logger.warning("sentence-transformers 未安装，回退到字符串匹配")
        return None, None
    except Exception as e:
        _logger.warning(f"语义匹配模型加载失败: {e}，回退到字符串匹配")
        return None, None


def compute_similarity(text_a: str, text_b: str) -> float:
    """
    计算两段文本的语义相似度（0-1）。
    如果模型未加载，回退到简单的字符串包含匹配。
    """
    if not text_a or not text_b:
        return 0.0

    model, tokenizer = _load_model()
    if model is None:
        # 回退：字符串包含匹配
        if text_a in text_b or text_b in text_a:
            return 0.85  # 字符串匹配给一个略低于阈值的分数
        return 0.0

    try:
        embeddings = model.encode([text_a, text_b], convert_to_numpy=True)
        # 余弦相似度
        from numpy import dot
        from numpy.linalg import norm
        sim = float(dot(embeddings[0], embeddings[1]) / (norm(embeddings[0]) * norm(embeddings[1])))
        return max(0.0, min(1.0, sim))
    except Exception:
        return 0.0


def find_best_match(
    query: str,
    candidate_names: list[str],
    threshold: float = 0.9,
) -> tuple[str | None, float]:
    """
    从候选列表中找到与 query 最相似的名称。
    返回 (最佳匹配名, 相似度分数)。如果没有超过阈值的匹配，返回 (None, 0.0)。
    """
    if not query or not candidate_names:
        return None, 0.0

    best_name = None
    best_score = 0.0

    for name in candidate_names:
        score = compute_similarity(query, name)
        if score > best_score:
            best_score = score
            best_name = name

    if best_score >= threshold:
        return best_name, best_score
    return None, best_score


def match_ability_to_caps(
    ability_name: str | None,
    capabilities: dict,
    threshold: float = 0.9,
) -> tuple[str | None, float]:
    """
    将一个能力名匹配到 capabilities 字典中的最佳条目。
    返回 (匹配到的能力名, 相似度分数)。
    """
    if not ability_name or not capabilities:
        return None, 0.0

    return find_best_match(ability_name, list(capabilities.keys()), threshold)


def is_same_ability(name_a: str, name_b: str, threshold: float = 0.9) -> bool:
    """判断两个能力名是否语义相同。"""
    if name_a == name_b:
        return True
    score = compute_similarity(name_a, name_b)
    return score >= threshold
