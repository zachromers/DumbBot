# DumbBot

Text a Twilio number from a flip phone and get a short, plain-text reply from Claude.

## How it works

1. Twilio POSTs each incoming text to `/sms`.
2. The app checks the `X-Twilio-Signature` header (403 if it doesn't match), then the
   sender allowlist. Numbers that aren't on the list get an empty `<Response/>`, so
   nothing is sent and nothing is billed.
3. It returns empty TwiML right away, well inside Twilio's 15 second limit, and handles
   the message on a background thread: Claude call, cleanup, then replies sent through the
   Twilio REST API.
4. The reply has markdown stripped and smart punctuation and emoji folded to GSM-7, so
   each segment holds 160 characters rather than 70. Anything over `MAX_SMS_CHARS` is
   split on sentence boundaries into at most 3 texts numbered `(1/3)`.
5. History is kept per number in SQLite: the last `MAX_HISTORY_TURNS` turns are sent to
   Claude, and a conversation is forgotten after `HISTORY_TTL_HOURS` of inactivity.
   Messages from one number are handled one at a time, so they don't overlap.
   If a step fails, the sender gets "Sorry, something went wrong, try again." and that
   turn isn't saved.

## Commands

The whole message must be the command. Case doesn't matter.

| Text | Effect |
|---|---|
| `RESET` or `NEW` | Clears history, replies "Cleared." |
| `HELP` | One-line usage note |
| `MORE` | Continues the previous answer |

STOP/START are handled by Twilio itself.

## Local setup

```bash
py -3.12 -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
cp .env.example .env   # then fill it in
.venv/Scripts/python -m pytest
.venv/Scripts/python wsgi.py
```

To try it end to end from your phone, expose the port with a tunnel, for example
`ngrok http 5000`. In the Twilio console, set the number's **A message comes in** webhook
to `https://<tunnel-host>/sms` (HTTP POST). ngrok sends `X-Forwarded-Proto` and
`X-Forwarded-Host`, so signature checks work without `SKIP_TWILIO_VALIDATION`. If they
fail anyway, set `PUBLIC_BASE_URL=https://<tunnel-host>`.

## Production

```bash
gunicorn -c gunicorn.conf.py wsgi:app
```

`gunicorn.conf.py` runs **one worker process with threads** on purpose. The per-number
locks and the reply thread pool live in memory, and a second process wouldn't see the
first one's locks. One process is plenty for personal use. Gunicorn doesn't run on
Windows natively, so use WSL, Docker, or a Linux host. A `Procfile` is included for
Heroku-style platforms.

The SQLite file needs persistent storage (`DB_PATH`). On platforms with ephemeral disks,
point it at a mounted volume.

Behind a reverse proxy, either make sure it forwards `X-Forwarded-Proto` and
`X-Forwarded-Host`, or set `PUBLIC_BASE_URL` to the URL Twilio calls, without `/sms`.

## Claude settings

- `CLAUDE_MODEL` defaults to `claude-sonnet-5-5`, with `max_tokens` 300 and effort `low`.
- On Sonnet 5.5 the request sends `thinking: {"type": "between_tools"}`, its lowest
  thinking setting, so the small token budget goes to the answer. Other models don't get
  this field because it's Sonnet 5.5 only. Opus 5.5, for one, can't turn thinking off,
  so raise `CLAUDE_MAX_TOKENS` if you switch models and replies come back truncated.
- `CLAUDE_FALLBACKS=1` (the default) turns on the API's server-side refusal fallback
  (`fallbacks: "default"`). If a safety classifier declines a benign question, it's
  retried on a fallback model. This works on the Claude API only, so set it to `0` if you
  use Bedrock, Vertex, or Foundry. Refusals that aren't retried get "Sorry, I can't help
  with that one."
- If a reply hits `max_tokens`, the unfinished last sentence is dropped.
- The system prompt is `DEFAULT_SYSTEM_PROMPT` in `dumbbot/config.py`. Set
  `SYSTEM_PROMPT` to override it.

See `.env.example` for every setting.

## Layout

```
dumbbot/
  app.py            Flask app, webhook, signature and URL reconstruction, Twilio sender
  bot.py            Commands, history, Claude call, error handling (background worker)
  claude_client.py  Messages API request and response handling
  storage.py        SQLite history and per-number locks
  textproc.py       Markdown stripping, GSM-7 folding, SMS splitting
  config.py         Environment configuration and the default system prompt
tests/              pytest suite (Claude and Twilio are faked, so no network calls)
wsgi.py             Entry point; loads .env
```
