"""Turn a model reply into plain, GSM-7-friendly SMS text."""

from __future__ import annotations

import re
import textwrap
import unicodedata

# GSM 03.38 basic character set plus the extension table.
GSM7_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXTENSION = "^{}\\[~]|€"
GSM7_CHARS = frozenset(GSM7_BASIC + GSM7_EXTENSION)

SMART_PUNCTUATION = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "«": '"', "»": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "−": "-",
    "—": " - ", "―": " - ",
    "…": "...",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    "​": "", "‌": "", "‍": "", "﻿": "",
    "•": "-", "·": "-", "‣": "-",
    "→": "->", "←": "<-", "×": "x", "÷": "/",
    "≤": "<=", "≥": ">=", "≠": "!=", "°": " deg",
    "\t": " ",
}

_MARKDOWN_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"```[^\n]*\n?(.*?)```", re.S), r"\1"),          # fenced code
    (re.compile(r"`([^`\n]*)`"), r"\1"),                         # inline code
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"),              # images
    (re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)"), r"\1 (\2)"),      # links
    (re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*", re.M), ""),          # headings
    (re.compile(r"^[ \t]{0,3}>[ \t]?", re.M), ""),               # blockquotes
    (re.compile(r"^[ \t]*([-*_][ \t]*){3,}$", re.M), ""),        # horizontal rules
    (re.compile(r"^[ \t]*\|?[ \t:|-]*-[ \t:|-]*\|?[ \t]*$", re.M), ""),  # table separators
    (re.compile(r"^[ \t]*\|[ \t]*|[ \t]*\|[ \t]*$", re.M), ""),  # table outer pipes
    (re.compile(r"[ \t]*\|[ \t]*"), ", "),                       # table inner pipes
    (re.compile(r"^[ \t]*[-*+•][ \t]+", re.M), ""),         # bullets
    (re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1"), r"\2"),       # bold
    (re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])"), r"\1"),  # *italic*
    (re.compile(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])"), r"\1"),    # _italic_
    (re.compile(r"~~(.+?)~~"), r"\1"),                           # strikethrough
]


def strip_markdown(text: str) -> str:
    for pattern, replacement in _MARKDOWN_RULES:
        text = pattern.sub(replacement, text)
    return text


def to_gsm7(text: str) -> str:
    """Replace smart punctuation, then fold or drop anything outside GSM-7."""
    text = "".join(SMART_PUNCTUATION.get(ch, ch) for ch in text)
    out = []
    for ch in text:
        if ch in GSM7_CHARS:
            out.append(ch)
            continue
        # Accented letters outside GSM-7 (e.g. "á") fold to their base letter.
        folded = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
        out.append(folded)  # emoji and other symbols fold to "" and are dropped
    return "".join(out)


def clean_reply(text: str) -> str:
    text = strip_markdown(text.replace("\r\n", "\n"))
    text = to_gsm7(text)
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r"[ ]*\n[ ]*", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")


def split_sms(text: str, max_chars: int = 600, max_parts: int = 3) -> list[str]:
    """Split on sentence boundaries into at most `max_parts` numbered messages."""
    if len(text) <= max_chars:
        return [text]

    limit = max_chars - len(f"({max_parts}/{max_parts}) ")
    pieces: list[str] = []
    for sentence in filter(None, (s.strip() for s in _SENTENCE_BREAK.split(text))):
        if len(sentence) <= limit:
            pieces.append(sentence)
        else:
            pieces.extend(textwrap.wrap(sentence, limit, break_on_hyphens=False))

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}" if current else piece
        if len(candidate) <= limit:
            current = candidate
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)

    if len(chunks) > max_parts:
        chunks = chunks[:max_parts]
        last = chunks[-1]
        if len(last) + 3 > limit:
            last = textwrap.shorten(last, limit - 3, placeholder="")
        chunks[-1] = last.rstrip(" .") + "..."

    if len(chunks) == 1:
        return chunks
    total = len(chunks)
    return [f"({i}/{total}) {chunk}" for i, chunk in enumerate(chunks, start=1)]
