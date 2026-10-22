import threading
import time

from twilio.request_validator import RequestValidator

from conftest import AUTH_TOKEN, ME, STRANGER, TWILIO_NUMBER, FakeResponder, FakeSender, SyncExecutor, make_config
from dumbbot.app import create_app
from dumbbot.bot import CLEARED_TEXT, HELP_TEXT, MORE_PROMPT, NO_TEXT, NOTHING_TO_CONTINUE, SORRY_TEXT

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response />'


def sign(url, params):
    return RequestValidator(AUTH_TOKEN).compute_signature(url, params)


def form(body, sender=ME):
    return {"From": sender, "To": TWILIO_NUMBER, "Body": body, "MessageSid": "SM123"}


def post_signed(client, params, url="http://localhost/sms", headers=None, **kwargs):
    headers = dict(headers or {})
    headers["X-Twilio-Signature"] = sign(url, params)
    return client.post("/sms", data=params, headers=headers, **kwargs)


# --- signature validation -------------------------------------------------


def test_missing_signature_is_rejected(make_client, responder, sender):
    resp = make_client().post("/sms", data=form("hi"))
    assert resp.status_code == 403
    assert responder.calls == [] and sender.sent == []


def test_bad_signature_is_rejected(make_client, sender):
    resp = make_client().post("/sms", data=form("hi"), headers={"X-Twilio-Signature": "bogus"})
    assert resp.status_code == 403
    assert sender.sent == []


def test_signature_for_tampered_body_is_rejected(make_client, sender):
    params = form("hi")
    sig = sign("http://localhost/sms", params)
    resp = make_client().post("/sms", data=form("something else"), headers={"X-Twilio-Signature": sig})
    assert resp.status_code == 403


def test_valid_signature_returns_empty_twiml_and_replies(make_client, responder, sender):
    resp = post_signed(make_client(), form("What is 2+2?"))
    assert resp.status_code == 200
    assert resp.mimetype == "text/xml"
    assert resp.get_data(as_text=True) == EMPTY_TWIML
    assert responder.calls == [[{"role": "user", "content": "What is 2+2?"}]]
    assert sender.sent == [{"to": ME, "from_": TWILIO_NUMBER, "body": "Hello there."}]


def test_forwarded_headers_are_honored(make_client, sender):
    params = form("hi")
    resp = post_signed(
        make_client(),
        params,
        url="https://bot.example.com/sms",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "bot.example.com"},
    )
    assert resp.status_code == 200
    assert len(sender.sent) == 1


def test_forwarded_url_mismatch_is_rejected(make_client):
    # Signed for the public https URL, but no proxy headers: reconstructed URL is http://localhost.
    resp = post_signed(make_client(), form("hi"), url="https://bot.example.com/sms", headers={})
    assert resp.status_code == 403


def test_public_base_url_is_used(make_client, sender):
    client = make_client(public_base_url="https://bot.example.com")
    resp = post_signed(client, form("hi"), url="https://bot.example.com/sms")
    assert resp.status_code == 200
    assert len(sender.sent) == 1


def test_query_string_is_part_of_signed_url(make_client):
    client = make_client()
    params = form("hi")
    url = "http://localhost/sms?x=1"
    resp = client.post("/sms?x=1", data=params, headers={"X-Twilio-Signature": sign(url, params)})
    assert resp.status_code == 200


def test_skip_validation_allows_unsigned(make_client, sender, caplog):
    client = make_client(skip_twilio_validation=True)
    resp = client.post("/sms", data=form("hi"))
    assert resp.status_code == 200
    assert len(sender.sent) == 1
    assert any("SKIP_TWILIO_VALIDATION" in r.message for r in caplog.records)


# --- allowlist ------------------------------------------------------------


def test_non_allowlisted_number_gets_empty_twiml_and_nothing_sent(make_client, responder, sender):
    resp = post_signed(make_client(), form("hi", sender=STRANGER))
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == EMPTY_TWIML
    assert responder.calls == []
    assert sender.sent == []


def test_allowlist_check_still_requires_valid_signature(make_client):
    resp = make_client().post("/sms", data=form("hi", sender=STRANGER))
    assert resp.status_code == 403


def test_from_number_override(make_client, sender):
    post_signed(make_client(twilio_from_number="+15557778888"), form("hi"))
    assert sender.sent[0]["from_"] == "+15557778888"


# --- commands -------------------------------------------------------------


def test_reset_clears_history(make_client, store, responder, sender):
    client = make_client()
    post_signed(client, form("first question"))
    assert store.recent(ME, 10)
    post_signed(client, form("  reset "))
    assert store.recent(ME, 10) == []
    assert sender.bodies[-1] == CLEARED_TEXT
    assert len(responder.calls) == 1  # RESET did not hit Claude


def test_new_is_alias_for_reset(make_client, store, sender):
    client = make_client()
    post_signed(client, form("question"))
    post_signed(client, form("New"))
    assert store.recent(ME, 10) == []
    assert sender.bodies[-1] == CLEARED_TEXT


def test_help(make_client, responder, sender):
    post_signed(make_client(), form("help"))
    assert sender.bodies == [HELP_TEXT]
    assert responder.calls == []
    assert "\n" not in HELP_TEXT


def test_commands_only_match_whole_message(make_client, responder):
    post_signed(make_client(), form("help me with my taxes"))
    assert responder.calls[0][-1]["content"] == "help me with my taxes"


def test_more_without_history(make_client, responder, sender):
    post_signed(make_client(), form("MORE"))
    assert sender.bodies == [NOTHING_TO_CONTINUE]
    assert responder.calls == []


def test_more_continues_with_history(make_client, responder, sender):
    responder.replies = ["Short version. Text MORE for details.", "Here are the details."]
    client = make_client()
    post_signed(client, form("Explain tides"))
    post_signed(client, form("more"))
    assert responder.calls[1] == [
        {"role": "user", "content": "Explain tides"},
        {"role": "assistant", "content": "Short version. Text MORE for details."},
        {"role": "user", "content": MORE_PROMPT},
    ]
    assert sender.bodies[-1] == "Here are the details."


def test_empty_body(make_client, responder, sender):
    post_signed(make_client(), form(""))
    assert sender.bodies == [NO_TEXT]
    assert responder.calls == []


# --- conversation flow ----------------------------------------------------


def test_history_is_sent_on_followups(make_client, responder, store):
    responder.replies = ["Paris.", "About 2.1 million."]
    client = make_client()
    post_signed(client, form("Capital of France?"))
    post_signed(client, form("Population?"))
    assert responder.calls[1] == [
        {"role": "user", "content": "Capital of France?"},
        {"role": "assistant", "content": "Paris."},
        {"role": "user", "content": "Population?"},
    ]
    assert len(store.recent(ME, 10)) == 4


def test_max_history_turns_is_respected(make_client, responder):
    client = make_client(max_history_turns=2)
    for i in range(5):
        post_signed(client, form(f"q{i}"))
    last_call = responder.calls[-1]
    assert [m["content"] for m in last_call] == ["q2", "Hello there.", "q3", "Hello there.", "q4"]


def test_reply_is_cleaned_before_sending_and_storing(make_client, responder, sender, store):
    responder.replies = ["**Yes** — it’s “fine” \U0001F44D"]
    post_signed(make_client(), form("ok?"))
    assert sender.bodies == ['Yes - it\'s "fine"']
    assert store.recent(ME, 10)[-1]["content"] == 'Yes - it\'s "fine"'


def test_long_reply_is_split_into_numbered_parts(make_client, responder, sender):
    responder.replies = [" ".join(f"This is sentence {i}." for i in range(60))]
    post_signed(make_client(max_sms_chars=300), form("long please"))
    assert len(sender.sent) == 3
    assert [b[:6] for b in sender.bodies] == ["(1/3) ", "(2/3) ", "(3/3) "]
    assert all(len(b) <= 300 for b in sender.bodies)


# --- failure handling -----------------------------------------------------


def test_claude_failure_sends_sorry_and_stores_nothing(store, sender):
    responder = FakeResponder(error=RuntimeError("API down"))
    app = create_app(make_config(), store=store, responder=responder, sender=sender, executor=SyncExecutor())
    resp = post_signed(app.test_client(), form("hi"))
    assert resp.status_code == 200
    assert sender.bodies == [SORRY_TEXT]
    assert store.recent(ME, 10) == []


def test_send_failure_falls_back_to_sorry(store, responder):
    sender = FakeSender(fail_times=1)
    app = create_app(make_config(), store=store, responder=responder, sender=sender, executor=SyncExecutor())
    post_signed(app.test_client(), form("hi"))
    assert sender.bodies == [SORRY_TEXT]


def test_worker_never_raises_even_if_sorry_fails(store, responder):
    sender = FakeSender(fail_times=5)
    app = create_app(make_config(), store=store, responder=responder, sender=sender, executor=SyncExecutor())
    resp = post_signed(app.test_client(), form("hi"))
    assert resp.status_code == 200
    assert sender.sent == []


def test_webhook_returns_before_claude_finishes(store, sender):
    """With the real thread pool, the response must not wait on Claude."""
    release = threading.Event()

    class SlowResponder:
        def reply(self, messages):
            release.wait(5)
            return "done"

    app = create_app(make_config(), store=store, responder=SlowResponder(), sender=sender)
    start = time.monotonic()
    resp = post_signed(app.test_client(), form("hi"))
    elapsed = time.monotonic() - start
    assert resp.status_code == 200
    assert elapsed < 1.0
    assert sender.sent == []
    release.set()
    deadline = time.monotonic() + 5
    while not sender.sent and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sender.bodies == ["done"]


def test_concurrent_messages_from_one_number_are_serialized(store, sender):
    """Two overlapping messages must not interleave their history writes."""
    active = 0
    max_active = 0
    guard = threading.Lock()

    class TrackingResponder:
        def __init__(self):
            self.calls = []

        def reply(self, messages):
            nonlocal active, max_active
            with guard:
                active += 1
                max_active = max(max_active, active)
                self.calls.append(list(messages))
            time.sleep(0.05)
            with guard:
                active -= 1
            return f"answer to {messages[-1]['content']}"

    responder = TrackingResponder()
    app = create_app(make_config(worker_threads=4), store=store, responder=responder, sender=sender)
    client = app.test_client()
    for i in range(4):
        post_signed(client, form(f"q{i}"))

    deadline = time.monotonic() + 5
    while len(sender.sent) < 4 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert len(sender.sent) == 4
    assert max_active == 1
    history = store.recent(ME, 10)
    assert len(history) == 8
    roles = [m["role"] for m in history]
    assert roles == ["user", "assistant"] * 4
    for user, assistant in zip(history[::2], history[1::2]):
        assert assistant["content"] == f"answer to {user['content']}"
    # Each call saw all previously completed turns.
    assert [len(c) for c in sorted(responder.calls, key=len)] == [1, 3, 5, 7]


def test_health(make_client):
    assert make_client().get("/health").status_code == 200
