import pytest

from dumbbot.config import DEFAULT_SYSTEM_PROMPT, Config, ConfigError

BASE = {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "tok"}


def test_defaults():
    cfg = Config.from_env(BASE)
    assert cfg.claude_model == "claude-sonnet-5-5"
    assert cfg.claude_max_tokens == 300
    assert cfg.max_history_turns == 10
    assert cfg.history_ttl_hours == 12
    assert cfg.max_sms_chars == 600
    assert cfg.skip_twilio_validation is False
    assert cfg.allowed_numbers == frozenset()
    assert cfg.system_prompt == DEFAULT_SYSTEM_PROMPT


def test_overrides():
    cfg = Config.from_env(
        {
            **BASE,
            "ALLOWED_NUMBERS": "+15551112222, +1 555 333 4444,",
            "SKIP_TWILIO_VALIDATION": "1",
            "PUBLIC_BASE_URL": "https://x.example.com/",
            "CLAUDE_MODEL": "claude-haiku-5-5",
            "MAX_HISTORY_TURNS": "4",
            "HISTORY_TTL_HOURS": "1.5",
            "SYSTEM_PROMPT": "Be terse.",
            "CLAUDE_EFFORT": "none",
        }
    )
    assert cfg.allowed_numbers == {"+15551112222", "+15553334444"}
    assert cfg.skip_twilio_validation is True
    assert cfg.public_base_url == "https://x.example.com"
    assert cfg.claude_model == "claude-haiku-5-5"
    assert cfg.max_history_turns == 4
    assert cfg.history_ttl_hours == 1.5
    assert cfg.system_prompt == "Be terse."
    assert cfg.claude_effort is None


def test_skip_validation_requires_exact_truthy_value():
    assert Config.from_env({**BASE, "SKIP_TWILIO_VALIDATION": "0"}).skip_twilio_validation is False
    assert Config.from_env({**BASE, "SKIP_TWILIO_VALIDATION": ""}).skip_twilio_validation is False


def test_missing_twilio_credentials():
    with pytest.raises(ConfigError):
        Config.from_env({})


def test_bad_integer():
    with pytest.raises(ConfigError):
        Config.from_env({**BASE, "MAX_HISTORY_TURNS": "lots"})
