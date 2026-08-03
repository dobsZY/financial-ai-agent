"""Analiz modulleri. Import edildiginde analizciler REGISTRY'ye kaydolur (K-04)."""

from ai_modules import pattern_rules as pattern_rules  # noqa: F401
from ai_modules import vision_model as vision_model  # noqa: F401
from ai_modules.base import REGISTRY, available_analyzers, get_analyzer

__all__ = ["REGISTRY", "available_analyzers", "get_analyzer"]
