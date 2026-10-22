"""Flask app exposing the Twilio SMS webhook."""

from __future__ import annotations

import logging
from concurrent.futures import Executor, ThreadPoolExecutor

from flask import Flask, Request, Response, abort, request
from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioClient
from twilio.twiml.messaging_response import MessagingResponse

from .bot import Bot, Responder, Sender, mask
from .config import Config
from .storage import HistoryStore

log = logging.getLogger(__name__)

SKIP_WARNING = (
    "!!! SKIP_TWILIO_VALIDATION is ON: /sms accepts unsigned requests. "
    "Anyone who finds this URL can spend your Claude and Twilio credit. "
    "Use only for local development. !!!"
)


class TwilioSender:
    def __init__(self, config: Config) -> None:
        self.client = TwilioClient(config.twilio_account_sid, config.twilio_auth_token)

    def send(self, to: str, from_: str, body: str) -> None:
        self.client.messages.create(to=to, from_=from_, body=body)


def public_url(req: Request, public_base_url: str | None) -> str:
    """The URL Twilio signed: what it called, not what the proxy forwarded to us."""
    path = req.script_root + req.path
    if req.query_string:
        path += "?" + req.query_string.decode()
    if public_base_url:
        return public_base_url.rstrip("/") + path

    def first(header: str) -> str | None:
        value = req.headers.get(header)
        return value.split(",")[0].strip() if value else None

    proto = first("X-Forwarded-Proto") or req.scheme
    host = first("X-Forwarded-Host") or req.host
    return f"{proto}://{host}{path}"


def empty_twiml() -> Response:
    return Response(str(MessagingResponse()), mimetype="text/xml")


def create_app(
    config: Config | None = None,
    *,
    store: HistoryStore | None = None,
    responder: Responder | None = None,
    sender: Sender | None = None,
    executor: Executor | None = None,
) -> Flask:
    config = config or Config.from_env()
    if responder is None:
        from .claude_client import ClaudeResponder

        responder = ClaudeResponder(config)

    store = store or HistoryStore(config.db_path, ttl_hours=config.history_ttl_hours)
    sender = sender or TwilioSender(config)
    executor = executor or ThreadPoolExecutor(
        max_workers=config.worker_threads, thread_name_prefix="sms-worker"
    )
    bot = Bot(config, store, responder, sender)
    validator = RequestValidator(config.twilio_auth_token)

    if config.skip_twilio_validation:
        log.warning(SKIP_WARNING)
    if not config.allowed_numbers:
        log.warning("ALLOWED_NUMBERS is empty: every incoming message will be ignored.")

    app = Flask(__name__)
    app.extensions["dumbbot"] = bot

    @app.post("/sms")
    def sms() -> Response:
        if config.skip_twilio_validation:
            log.warning("Twilio signature NOT checked (SKIP_TWILIO_VALIDATION=1)")
        else:
            signature = request.headers.get("X-Twilio-Signature", "")
            url = public_url(request, config.public_base_url)
            if not signature or not validator.validate(url, request.form.to_dict(), signature):
                log.warning("Rejected request with invalid Twilio signature (url=%s)", url)
                abort(403)

        from_number = request.form.get("From", "").strip()
        if from_number not in config.allowed_numbers:
            log.info("Ignoring message from non-allowlisted number %s", mask(from_number))
            return empty_twiml()

        to_number = config.twilio_from_number or request.form.get("To", "").strip()
        executor.submit(bot.handle, from_number, to_number, request.form.get("Body", ""))
        return empty_twiml()

    @app.get("/health")
    def health() -> tuple[str, int]:
        return "ok", 200

    return app
