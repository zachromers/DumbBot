"""Thin wrapper around the Anthropic Messages API."""

from __future__ import annotations

import logging
import re
from typing import Any

import anthropic

from .config import Config

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
REFUSAL_TEXT = "Sorry, I can't help with that one."

_LAST_SENTENCE_END = re.compile(r"^(.*[.!?])(?:\s|$)", re.S)


class ClaudeResponder:
    def __init__(self, config: Config, client: Any = None) -> None:
        self.config = config
        self.client = client or anthropic.Anthropic(timeout=45.0, max_retries=2)

    def build_params(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        cfg = self.config
        params: dict[str, Any] = {
            "model": cfg.claude_model,
            "max_tokens": cfg.claude_max_tokens,
            "system": cfg.system_prompt,
            "messages": messages,
        }
        if cfg.claude_effort:
            params["output_config"] = {"effort": cfg.claude_effort}
        if cfg.claude_model.startswith("claude-sonnet-5-5"):
            # Lowest thinking setting on Sonnet 5.5, so the small max_tokens budget
            # goes to the answer rather than to reasoning.
            params["thinking"] = {"type": "between_tools"}
        return params

    def reply(self, messages: list[dict[str, str]]) -> str:
        params = self.build_params(messages)
        if self.config.claude_fallbacks:
            # Retry classifier refusals on a fallback model server-side.
            response = self.client.beta.messages.create(
                **params, betas=[FALLBACK_BETA], fallbacks="default"
            )
        else:
            response = self.client.messages.create(**params)

        if response.stop_reason == "refusal":
            log.info("Claude declined: %s", getattr(response, "stop_details", None))
            return REFUSAL_TEXT

        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()

        if response.stop_reason == "max_tokens":
            # Drop a half-finished trailing sentence if there's a complete one before it.
            match = _LAST_SENTENCE_END.match(text)
            if match:
                text = match.group(1)
        return text
