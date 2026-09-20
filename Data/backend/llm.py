"""Compatibility shim — ownership lives in ``Data.modules.model_runtime``."""

from Data.modules.model_runtime import LLMUnavailable, OpenAICompatibleLLM

__all__ = ["LLMUnavailable", "OpenAICompatibleLLM"]
