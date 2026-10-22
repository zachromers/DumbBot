"""Message handling that runs in the background worker."""

from __future__ import annotations

import logging
from typing import Protocol

from .config import Config
from .storage import HistoryStore, KeyedLocks
from .textproc import clean_reply, split_sms

log = logging.getLogger(__name__)

SORRY_TEXT = "Sorry, something went wrong, try again."
CLEARED_TEXT = "Cleared."
HELP_TEXT = "Text any question for a short answer. MORE continues the last answer. RESET or NEW starts over."
NO_TEXT = "I can only read text messages."
NOTHING_TO_CONTINUE = "Nothing to continue yet. Ask me something first."
EMPTY_REPLY = "Sorry, I didn't get an answer. Try again."
MORE_PROMPT = (
    "Continue your previous answer with the next most important details. "
    "Same rules: plain text, short."
)


class Responder(Protocol):
    def reply(self, messages: list[dict[str, str]]) -> str: ...


class Sender(Protocol):
    def send(self, to: str, from_: str, body: str) -> None: ...


def mask(number: str) -> str:
    return f"...{number[-4:]}" if len(number) > 4 else "..."


class Bot:
    def __init__(
        self,
        config: Config,
        store: HistoryStore,
        responder: Responder,
        sender: Sender,
        locks: KeyedLocks | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.responder = responder
        self.sender = sender
        self.locks = locks or KeyedLocks()

    def handle(self, from_number: str, to_number: str, body: str) -> None:
        """Worker entry point. Never raises."""
        try:
            for part in self.respond(from_number, body):
                self.sender.send(to=from_number, from_=to_number, body=part)
        except Exception:
            log.exception("Failed handling message from %s", mask(from_number))
            try:
                self.sender.send(to=from_number, from_=to_number, body=SORRY_TEXT)
            except Exception:
                log.exception("Failed sending error reply to %s", mask(from_number))

    def respond(self, from_number: str, body: str) -> list[str]:
        text = (body or "").strip()
        command = text.upper()

        with self.locks.get(from_number):
            if not text:
                return [NO_TEXT]
            if command in {"RESET", "NEW"}:
                self.store.clear(from_number)
                return [CLEARED_TEXT]
            if command == "HELP":
                return [HELP_TEXT]

            history = self.store.recent(from_number, self.config.max_history_turns)
            if command == "MORE":
                if not history:
                    return [NOTHING_TO_CONTINUE]
                prompt = MORE_PROMPT
            else:
                prompt = text

            reply = clean_reply(self.responder.reply([*history, {"role": "user", "content": prompt}]))
            if not reply:
                return [EMPTY_REPLY]
            self.store.append_turn(from_number, prompt, reply)

        return split_sms(reply, self.config.max_sms_chars, max_parts=3)
