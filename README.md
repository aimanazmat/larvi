# Larvi — Autonomous Email & Calendar AI Agent

Larvi understands a natural-language request, routes it to the right
specialized agent, calls real tools/APIs, and returns a grounded result.

```
User -> Larvi Master Agent -> Email Agent / Calendar Agent -> Tool/API -> Result -> Larvi -> User
```

## 1. Quickstart — free / local (Ollama, no API key, no cost)

```bash
python -m venv .venv && source .venv/bin/activate      # or your preferred venv tool
pip install -r requirements.txt
cp .env.example .env        # LLM_BACKEND=ollama is already the default
```

Then install Ollama and pull a tool-calling-capable model (one-time setup):
1. Download & install Ollama: https://ollama.com/download
2. `ollama pull llama3.1` (or `qwen2.5`, `mistral-nemo` — any tool-calling model)
3. Make sure the Ollama server is running (it auto-starts after install; if
   not, run `ollama serve` in a separate terminal)

```bash
python scripts/demo_ollama.py            # runs 4 scripted multi-step workflows
python scripts/demo_ollama.py --chat     # interactive REPL
```

## 1b. Alternative — Claude via Anthropic API (paid)

```bash
cp .env.example .env
# edit .env: set LLM_BACKEND=anthropic and ANTHROPIC_API_KEY=sk-ant-...
python scripts/demo.py            # runs 4 scripted multi-step workflows
python scripts/demo.py --chat     # interactive REPL
# or run the API:
uvicorn app.main:app --reload
```

Both backends share the exact same Email Agent, Calendar Agent, tools,
and context/confirmation logic — only the "brain" doing intent
understanding and tool selection differs (`app/master_agent_ollama.py`
vs `app/master_agent.py`). `app/main.py` picks whichever backend
`LLM_BACKEND` in `.env` points to.

With `MOCK_MODE=true` (the default), Email/Calendar tools operate on an
in-memory mock mailbox/calendar (`app/tools/mock_data.py`) instead of real
Gmail/Calendar — so the full Master Agent -> Agent -> Tool -> Result loop
is demonstrable immediately, with zero Google Cloud setup.

## 2. Switching to real Gmail + Google Calendar

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project, then enable the **Gmail API** and **Google Calendar API**.
2. Under *APIs & Services -> Credentials*, create an **OAuth client ID**
   of type **Desktop app**. Download the JSON.
3. Save it as `storage/credentials.json` (never commit this file — it's
   already covered by `.gitignore`).
4. In `.env`, set `MOCK_MODE=false`.
5. First request triggers a local browser consent screen; the resulting
   token is cached at `storage/token.json` and silently refreshed after
   that (see `app/auth/google_auth.py`).

No API keys or secrets are hard-coded anywhere in source — everything
comes from `.env` / `storage/credentials.json`, both git-ignored.

## 3. Architecture

| Component | File | Responsibility |
|---|---|---|
| Master Agent (Ollama, free/default) | `app/master_agent_ollama.py` | Same responsibilities as below, powered by a local model via Ollama — no API key or cost |
| Master Agent (Claude, paid) | `app/master_agent.py` | Understands intent, runs the Claude tool-calling loop, routes to the right agent, enforces confirmation on sensitive actions, keeps the "only report real success" guarantee |
| Email Agent | `app/agents/email_agent.py` | Exposes `email_*` tool schemas, dispatches to `email_tools.py` |
| Calendar Agent | `app/agents/calendar_agent.py` | Exposes `calendar_*` tool schemas, dispatches to `calendar_tools.py` |
| Tools | `app/tools/email_tools.py`, `calendar_tools.py` | Real Gmail/Calendar API calls (or mock, by flag) — the only place that talks to Google |
| Context | `app/core/context.py` | Per-session history, last-referenced email/event (for follow-ups), pending confirmation state — persisted to `storage/sessions.json` |
| Auth | `app/auth/google_auth.py` | OAuth2 flow, token cache + refresh |
| API | `app/main.py` | FastAPI `POST /chat` endpoint |

### How agent routing works
Every tool given to Claude is namespaced (`email_search_emails`,
`calendar_create_event`, ...). Claude's native tool-use decision *is* the
"select the correct specialized agent" step — when Claude picks
`calendar_create_event`, it has implicitly picked the Calendar Agent. The
Master Agent reads the prefix to log which agent handled each step into
`workflow_trace`, and dispatches the call to that agent's `dispatch()`.

### How multi-step workflows work
The Master Agent runs a loop: send the conversation to Claude -> if Claude
requests a tool call, execute it and feed the real result back -> repeat.
Because *all* tools (both agents') are available in every round, Claude can
call an `email_*` tool, read what came back, and then call a `calendar_*`
tool with details it just extracted — all before producing one final
answer. This is what makes
*"find the email from Ahmed about the meeting and add it to my calendar"*
work as a single request (see Workflow 3 in `scripts/demo.py`).

### How context/follow-ups work
After any successful lookup that resolves to a single email or event,
`master_agent._remember_entities()` stores it in the session's
`last_entities`. It's also kept as plain conversation history sent back to
Claude on the next turn, so "move **it** to 5 PM" is resolved by Claude
reading back what "it" was in the prior turns — the same mechanism a human
assistant would use.

### How safety/confirmation works
`send_email`, `reply_email`, and `delete_event` are marked as
**sensitive tools**. When Claude requests one of them, the Master Agent
does **not** execute it — it stores the pending call in session context
and asks the user to confirm. Only a follow-up request with
`confirm: true` actually runs the tool (see Workflow 4 in
`scripts/demo.py`, and `POST /chat` with `"confirm": true`).

### How "never claim success falsely" is enforced
Every tool returns `{"success": bool, "data": ..., "error": ...}`. That
exact JSON — not a paraphrase — is what gets fed back to Claude as the
`tool_result`, and the system prompt explicitly instructs Claude to only
report success when `success == true`. There is no code path where the
Master Agent fabricates a result.

### Error handling
Every tool function wraps its Google API call in `try/except` and returns
`{"success": false, "error": "..."}` on failure (auth failure, not found,
invalid recipient, API error, etc.) instead of raising — so a failure
becomes a normal conversational turn ("I couldn't find that email...")
rather than a crash. `google_auth.py` raises a clear `GoogleAuthError`
with setup instructions if `storage/credentials.json` is missing.

## 4. Demonstrated workflows (`scripts/demo.py`)

1. **Single-agent**: "Find the email from Ahmed about the project meeting."
2. **Context follow-up**: "What meetings do I have coming up?" -> "Move
   the Weekly Sync to 6 PM instead."
3. **Multi-agent chain**: "Check whether I received an email from Ahmed
   about tomorrow's project meeting. If you find the meeting time, check
   whether I'm free and add it to my calendar."
4. **Confirmation-gated action**: "Send Ali an email letting him know the
   project update is ready" -> Larvi asks to confirm -> "yes, send it".

## 5. API

```
POST /chat
{
  "session_id": "abc123",
  "message": "What meetings do I have tomorrow?",
  "confirm": null            // set true/false only when replying to a pending confirmation
}
```

Response includes `reply`, `tool_calls` (what actually ran and whether it
succeeded), `pending_confirmation` (non-null when Larvi is waiting on
you), and `workflow_trace` (which agent/tool handled each step).

```
POST /session/{session_id}/reset   # clear a session's context
GET  /health
```

## 6. Project layout

```
larvi/
  app/
    main.py                 FastAPI app
    master_agent.py         Master Agent (routing, tool loop, confirmation)
    config.py                Settings from .env
    agents/
      email_agent.py         Email Agent: tool schemas + dispatch
      calendar_agent.py      Calendar Agent: tool schemas + dispatch
    tools/
      email_tools.py         Gmail API (+ mock) implementations
      calendar_tools.py      Google Calendar API (+ mock) implementations
      mock_data.py            In-memory demo data
    auth/
      google_auth.py          OAuth2 flow, token cache/refresh
    core/
      context.py               Session state persistence
      schemas.py                Pydantic request/response models
  scripts/
    demo.py                    Scripted multi-step workflow demos + REPL
  storage/                     credentials.json / token.json / sessions.json (git-ignored)
  requirements.txt
  .env.example
```

## 7. Notes on the AI development tools used

This project was scaffolded and iterated on with Claude (Anthropic),
following the recommended workflow of using an AI coding assistant for
planning, code generation, and debugging while keeping the resulting
architecture simple enough to explain end-to-end (see the table in
Section 3) — every file maps to exactly one part of the required
`User -> Master Agent -> Email/Calendar Agent -> Tool -> Result -> User`
pipeline.
