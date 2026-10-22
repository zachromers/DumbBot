from types import SimpleNamespace

from conftest import make_config
from dumbbot.claude_client import FALLBACK_BETA, REFUSAL_TEXT, ClaudeResponder
from dumbbot.config import DEFAULT_SYSTEM_PROMPT


def message(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, stop_details=None)


def text(t):
    return SimpleNamespace(type="text", text=t)


def thinking():
    return SimpleNamespace(type="thinking", thinking="", signature="sig")


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeAnthropic:
    def __init__(self, response):
        self.messages = FakeMessages(response)
        self.beta = SimpleNamespace(messages=FakeMessages(response))


HISTORY = [{"role": "user", "content": "hi"}]


def test_request_params_for_default_model():
    client = FakeAnthropic(message(text("Hello.")))
    responder = ClaudeResponder(make_config(claude_fallbacks=False), client=client)
    assert responder.reply(HISTORY) == "Hello."
    (call,) = client.messages.calls
    assert call["model"] == "claude-sonnet-5-5"
    assert call["max_tokens"] == 300
    assert call["system"] == DEFAULT_SYSTEM_PROMPT
    assert call["messages"] == HISTORY
    assert call["thinking"] == {"type": "between_tools"}
    assert call["output_config"] == {"effort": "low"}
    assert client.beta.messages.calls == []


def test_fallbacks_use_beta_endpoint():
    client = FakeAnthropic(message(text("Hello.")))
    ClaudeResponder(make_config(claude_fallbacks=True), client=client).reply(HISTORY)
    (call,) = client.beta.messages.calls
    assert call["betas"] == [FALLBACK_BETA]
    assert call["fallbacks"] == "default"
    assert client.messages.calls == []


def test_other_models_do_not_get_between_tools():
    client = FakeAnthropic(message(text("Hi.")))
    cfg = make_config(claude_model="claude-opus-5-5", claude_effort=None)
    ClaudeResponder(cfg, client=client).reply(HISTORY)
    (call,) = client.messages.calls
    assert call["model"] == "claude-opus-5-5"
    assert "thinking" not in call
    assert "output_config" not in call


def test_only_text_blocks_are_returned():
    client = FakeAnthropic(message(thinking(), text("Part one. "), text("Part two.")))
    assert ClaudeResponder(make_config(), client=client).reply(HISTORY) == "Part one. Part two."


def test_refusal_returns_polite_text():
    client = FakeAnthropic(message(stop_reason="refusal"))
    assert ClaudeResponder(make_config(), client=client).reply(HISTORY) == REFUSAL_TEXT


def test_max_tokens_trims_dangling_sentence():
    client = FakeAnthropic(message(text("First point. Second point is cut of"), stop_reason="max_tokens"))
    assert ClaudeResponder(make_config(), client=client).reply(HISTORY) == "First point."


def test_max_tokens_keeps_text_without_sentence_end():
    client = FakeAnthropic(message(text("no punctuation at all"), stop_reason="max_tokens"))
    assert ClaudeResponder(make_config(), client=client).reply(HISTORY) == "no punctuation at all"
