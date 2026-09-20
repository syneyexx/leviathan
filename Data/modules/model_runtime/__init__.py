"""Model runtime — canonical provider-facing model access."""

from .openai_compatible import LLMUnavailable, OpenAICompatibleLLM

__all__ = ["LLMUnavailable", "OpenAICompatibleLLM"]
