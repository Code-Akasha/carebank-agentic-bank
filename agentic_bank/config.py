from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    db_path: str
    banking_api_secret: str
    webhook_secret: str
    gemini_api_key: str
    gemini_model: str
    strict_mode: bool
    fallback_enabled: bool
    webhook_timeout_seconds: float
    webhook_max_attempts: int
    webhook_retry_backoff_seconds: float


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings(
            db_path=os.getenv("PROXY_DB_PATH", "./agentic_proxy.db"),
            banking_api_secret=os.getenv("BANKING_API_SECRET", ""),
            webhook_secret=os.getenv("PROXY_WEBHOOK_SECRET")
            or os.getenv("MOCKBANK_WEBHOOK_SECRET")
            or os.getenv("BANKING_API_SECRET", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            strict_mode=_get_bool("PROXY_STRICT_MODE", False),
            fallback_enabled=_get_bool("PROXY_FALLBACK_ENABLED", True),
            webhook_timeout_seconds=_get_float(
                "PROXY_WEBHOOK_TIMEOUT_SECONDS", 5.0
            ),
            webhook_max_attempts=_get_int("PROXY_WEBHOOK_MAX_ATTEMPTS", 3),
            webhook_retry_backoff_seconds=_get_float(
                "PROXY_WEBHOOK_RETRY_BACKOFF_SECONDS", 0.0
            ),
        )
    return _settings
