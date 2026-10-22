"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_SYSTEM_PROMPT = (
    "The user is texting you from a basic flip phone over SMS. "
    "Answer in plain text only: no markdown, no bullet or numbered lists, no emoji, "
    "no special characters. Be direct and concise, ideally under 320 characters and "
    "never more than about 600. No preamble and no sign-off. If a question needs a "
    "long answer, give the key points and offer to continue with \"Text MORE for "
    "details\". Use only plain ASCII punctuation: straight quotes, a plain hyphen "
    "instead of dashes, three periods instead of an ellipsis. Avoid curly quotes, "
    "em dashes and other characters that force UCS-2 SMS encoding."
)


class ConfigError(RuntimeError):
    pass


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


def _float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc


@dataclass(frozen=True)
class Config:
    twilio_account_sid: str
    twilio_auth_token: str
    allowed_numbers: frozenset[str]
    twilio_from_number: str | None = None
    skip_twilio_validation: bool = False
    public_base_url: str | None = None
    claude_model: str = "claude-sonnet-5-5"
    claude_max_tokens: int = 300
    claude_effort: str | None = "low"
    claude_fallbacks: bool = True
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    db_path: str = "dumbbot.sqlite3"
    max_history_turns: int = 10
    history_ttl_hours: float = 12.0
    max_sms_chars: int = 600
    worker_threads: int = 4

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        env = os.environ if env is None else env

        sid = env.get("TWILIO_ACCOUNT_SID", "").strip()
        token = env.get("TWILIO_AUTH_TOKEN", "").strip()
        if not sid or not token:
            raise ConfigError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are required")

        allowed = frozenset(
            n.strip().replace(" ", "")
            for n in env.get("ALLOWED_NUMBERS", "").split(",")
            if n.strip()
        )

        effort = env.get("CLAUDE_EFFORT", "low").strip().lower() or None
        if effort in {"none", "off"}:
            effort = None

        return cls(
            twilio_account_sid=sid,
            twilio_auth_token=token,
            allowed_numbers=allowed,
            twilio_from_number=env.get("TWILIO_FROM_NUMBER", "").strip() or None,
            skip_twilio_validation=_bool(env.get("SKIP_TWILIO_VALIDATION")),
            public_base_url=env.get("PUBLIC_BASE_URL", "").strip().rstrip("/") or None,
            claude_model=env.get("CLAUDE_MODEL", "").strip() or "claude-sonnet-5-5",
            claude_max_tokens=_int(env, "CLAUDE_MAX_TOKENS", 300),
            claude_effort=effort,
            claude_fallbacks=_bool(env.get("CLAUDE_FALLBACKS", "1")),
            system_prompt=env.get("SYSTEM_PROMPT", "").strip() or DEFAULT_SYSTEM_PROMPT,
            db_path=env.get("DB_PATH", "").strip() or "dumbbot.sqlite3",
            max_history_turns=_int(env, "MAX_HISTORY_TURNS", 10),
            history_ttl_hours=_float(env, "HISTORY_TTL_HOURS", 12.0),
            max_sms_chars=_int(env, "MAX_SMS_CHARS", 600),
            worker_threads=_int(env, "WORKER_THREADS", 4),
        )
