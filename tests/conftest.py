from __future__ import annotations

import threading
from concurrent.futures import Executor, Future

import pytest

from dumbbot.app import create_app
from dumbbot.config import Config
from dumbbot.storage import HistoryStore

AUTH_TOKEN = "test-auth-token"
ME = "+15551230001"
STRANGER = "+15559990000"
TWILIO_NUMBER = "+15550001111"


class SyncExecutor(Executor):
    """Runs submitted work inline so tests can assert on the outcome."""

    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # pragma: no cover - Bot.handle never raises
            future.set_exception(exc)
        return future


class FakeResponder:
    def __init__(self, replies=None, error: Exception | None = None):
        self.replies = list(replies or ["Hello there."])
        self.error = error
        self.calls: list[list[dict[str, str]]] = []
        self._lock = threading.Lock()

    def reply(self, messages):
        with self._lock:
            self.calls.append([dict(m) for m in messages])
        if self.error:
            raise self.error
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


class FakeSender:
    def __init__(self, fail_times: int = 0):
        self.sent: list[dict[str, str]] = []
        self.fail_times = fail_times
        self._lock = threading.Lock()

    def send(self, to, from_, body):
        with self._lock:
            if self.fail_times:
                self.fail_times -= 1
                raise RuntimeError("twilio down")
            self.sent.append({"to": to, "from_": from_, "body": body})

    @property
    def bodies(self):
        return [m["body"] for m in self.sent]


def make_config(**overrides) -> Config:
    values = dict(
        twilio_account_sid="ACtest",
        twilio_auth_token=AUTH_TOKEN,
        allowed_numbers=frozenset({ME}),
        claude_fallbacks=False,
    )
    values.update(overrides)
    return Config(**values)


@pytest.fixture
def store(tmp_path):
    return HistoryStore(str(tmp_path / "test.sqlite3"))


@pytest.fixture
def responder():
    return FakeResponder()


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def make_client(store, responder, sender):
    def _make(**config_overrides):
        app = create_app(
            make_config(**config_overrides),
            store=store,
            responder=responder,
            sender=sender,
            executor=SyncExecutor(),
        )
        app.testing = True
        return app.test_client()

    return _make
