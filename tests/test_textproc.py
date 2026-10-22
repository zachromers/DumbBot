from dumbbot.textproc import GSM7_CHARS, clean_reply, split_sms, strip_markdown


def test_strip_markdown_basics():
    md = (
        "# Title\n"
        "Some **bold** and *italic* and __also bold__ and `code`.\n"
        "- first item\n"
        "* second item\n"
        "> quoted\n"
        "See [the docs](https://example.com).\n"
        "```python\nprint('hi')\n```"
    )
    out = strip_markdown(md)
    for token in ("#", "**", "__", "`", "- first", "* second", "> ", "]("):
        assert token not in out
    assert "Title" in out
    assert "bold" in out and "italic" in out and "code" in out
    assert "first item" in out and "second item" in out
    assert "the docs (https://example.com)" in out
    assert "print('hi')" in out


def test_strip_markdown_leaves_snake_case_and_math_alone():
    assert strip_markdown("use my_var_name here") == "use my_var_name here"
    assert strip_markdown("2 * 3 * 4 = 24") == "2 * 3 * 4 = 24"


def test_strip_markdown_tables():
    out = strip_markdown("| a | b |\n|---|---|\n| 1 | 2 |")
    assert "|" not in out
    assert "a, b" in out and "1, 2" in out


def test_clean_reply_replaces_smart_punctuation():
    out = clean_reply("“It’s fine” — really… 5–6 • ok")
    assert out == '"It\'s fine" - really... 5-6 - ok'


def test_clean_reply_output_is_gsm7_only():
    out = clean_reply("Cafá naïve \U0001F600 résumé ✓ done ™")
    assert all(ch in GSM7_CHARS for ch in out)
    assert "\U0001F600" not in out
    assert out.startswith("Cafa naive")
    assert "résumé" in out  # e-acute is valid GSM-7, kept as-is


def test_clean_reply_collapses_whitespace():
    assert clean_reply("  a   b \n\n\n c  ") == "a b\nc"


def test_split_short_text_is_untouched():
    assert split_sms("Short answer.", 600) == ["Short answer."]


def test_split_on_sentence_boundaries_with_numbering():
    sentences = [f"Sentence number {i} is here." for i in range(40)]
    text = " ".join(sentences)
    parts = split_sms(text, max_chars=300)
    assert len(parts) == 3  # capped
    assert parts[0].startswith("(1/3) ")
    assert parts[2].startswith("(3/3) ")
    for part in parts:
        assert len(part) <= 300
    # Sentences are not cut in half (except the truncated final part).
    for part in parts[:-1]:
        assert part.endswith(".")
    assert parts[-1].endswith("...")


def test_split_two_parts():
    text = ("A" * 50 + ". ") * 8  # ~416 chars
    parts = split_sms(text.strip(), max_chars=300)
    assert len(parts) == 2
    assert parts[0].startswith("(1/2) ") and parts[1].startswith("(2/2) ")
    assert all(len(p) <= 300 for p in parts)


def test_split_hard_wraps_a_giant_sentence():
    text = " ".join(["word"] * 200)  # ~1000 chars, no punctuation
    parts = split_sms(text, max_chars=600)
    assert len(parts) == 2
    assert all(len(p) <= 600 for p in parts)
