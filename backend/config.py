from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_model: str | None
    llm_api_key: str
    llm_timeout_seconds: float
    database_path: Path
    knowledge_top_k: int
    max_history_messages: int
    reasoning_enabled: bool

    @classmethod
    def from_env(cls) -> "Settings":
        db_raw = os.getenv("LEVIATHAN_DATABASE_PATH", "data/leviathan.db")
        db_path = Path(db_raw)
        if not db_path.is_absolute():
            db_path = ROOT / db_path

        model = os.getenv("LEVIATHAN_LLM_MODEL", "").strip() or None
        return cls(
            llm_base_url=os.getenv("LEVIATHAN_LLM_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/"),
            llm_model=model,
            llm_api_key=os.getenv("LEVIATHAN_LLM_API_KEY", "not-needed"),
            llm_timeout_seconds=float(os.getenv("LEVIATHAN_LLM_TIMEOUT_SECONDS", "90")),
            database_path=db_path,
            knowledge_top_k=max(1, int(os.getenv("LEVIATHAN_KNOWLEDGE_TOP_K", "5"))),
            max_history_messages=max(4, int(os.getenv("LEVIATHAN_MAX_HISTORY_MESSAGES", "24"))),
            reasoning_enabled=_env_bool("LEVIATHAN_REASONING_ENABLED", True),
        )


settings = Settings.from_env()
