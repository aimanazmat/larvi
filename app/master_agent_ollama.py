"""
Larvi Master Agent — Ollama backend.

Identical responsibilities to app/master_agent.py (understand intent,
route to Email/Calendar Agent, run the tool-calling loop, gate sensitive
actions behind confirmation, never claim false success) but powered by a
LOCAL, FREE model via Ollama instead of the paid Anthropic API.

Requirements:
  1. Install Ollama: https://ollama.com/download
  2. Pull a tool-calling-capable model, e.g.:
       ollama pull llama3.1
  3. Make sure the Ollama server is running (it starts automatically after
     install, or run `ollama serve`).
  4. In .env set: OLLAMA_MODEL=llama3.1  (and LLM_BACKEND=ollama, though
     this module can just be imported directly regardless of that flag)

No API key, no billing, no internet call to Anthropic — everything runs
on your machine.
"""
from __future__ import annotations
import json
from typing import Any

import ollama

from app.config import settings
from app.core.context import ContextStore, SessionContext
from app.core.schemas import ChatResponse, ToolCallRecord
from app.agents import email_agent, calendar_agent
from app.tool_schemas_openai import get_ollama_tools

SYSTEM_PROMPT_TEMPLATE = """\
You are Larvi, an autonomous Email and Calendar assistant.

The current date and time is: {now}. Use this to resolve relative dates \
like "today", "tomorrow", "next Monday" into real ISO-8601 datetimes \
(e.g. "2026-08-25T15:00:00") before calling any tool. NEVER pass words \
like "now", "today", or "tomorrow" directly as a start/end argument — \
always convert them to a concrete ISO-8601 datetime yourself first.

You have tools from two specialized agents:
  - email_* tools (Email Agent): search, read, list, draft, send, reply
  - calendar_* tools (Calendar Agent): list, search, check availability, \
create, update/reschedule, delete events

Rules you must follow:
1. Understand the user's intent and extract the concrete parameters needed \
(dates/times, recipients, senders, subjects) before calling a tool. If a \
required detail is missing (e.g. no date/time given), ask the user instead \
of guessing.
2. For multi-step requests (e.g. "find the email about X and add it to my \
calendar"), chain tool calls yourself: call the email tool, read what it \
returns, then call the calendar tool with the extracted details, without \
waiting for the user in between.
3. NEVER state that an email was sent, a draft was created, or an event was \
created/updated/deleted unless the corresponding tool result says \
success=true. If a tool fails, explain what went wrong in plain language.
4. Use conversation context to resolve follow-up references like "it" or \
"that meeting" to the most recently discussed email or event.
5. Be concise and concrete in your final answer: state what you found or \
did, using real details from tool results (names, times, subjects) — never \
invented ones.
6. When you decide to call a tool, call it — don't describe that you are \
going to call it in plain text.
7. Every calendar/email item has a real internal id (e.g. "event-1001", \
"email-3"). You do NOT know these ids in advance — a title like "Weekly \
Sync" is NOT a valid id. Before calling calendar_update_event, \
calendar_delete_event, email_read_email, or email_reply_email, you MUST \
first call a search/list tool (calendar_get_events, calendar_search_events, \
email_search_emails, email_get_recent_emails) to find the item and read its \
real id from the tool result, then use THAT id — never the title/subject. \
NEVER invent or guess an id.
8. "Send" and "draft" are different actions: if the user asks to SEND an \
email, call email_send_email (not email_create_draft). Only call \
email_create_draft if the user explicitly asks for a draft they can review \
later, not to send it now. Example: "send Ali an email about X" -> call \
email_send_email. "draft an email to Ali about X" -> call email_create_draft. \
If in doubt whether the user wants it sent, default to email_send_email \
since "send"/"let them know"/"tell them" all mean send, not draft.
9. When the user asks for "upcoming" events / "what's coming up" without a \
specific date, call calendar_get_events with NO start/end arguments at all \
so all future events are considered — do not restrict the search to just \
today.
10. When searching emails from a specific named person, put their name in \
the 'sender' parameter of email_search_emails — never cram a name into \
'query' or 'subject_contains'.
11. Do not describe an action as done in your final answer unless you \
actually called the corresponding tool THIS turn and its result said \
success=true. If you did not call a tool, say so plainly instead of \
guessing what the outcome would be.
12. Do NOT produce a final text-only answer until every action the user \
asked for has either been completed via a successful tool call, or you \
have hit a real blocker (missing info, a tool failure, or something \
requiring the user's confirmation). If the user's request has multiple \
parts (e.g. "check email AND check availability AND add to calendar"), \
keep calling tools — one after another in this same turn — until all \
parts are done. Stopping after only the first tool call when more steps \
remain is wrong.
"""

TOOLS = get_ollama_tools()
SENSITIVE_TOOLS = email_agent.SENSITIVE_TOOLS | calendar_agent.SENSITIVE_TOOLS

_ollama_client = ollama.Client(host=settings.ollama_host)


def _agent_for(tool_name: str) -> str:
    if tool_name.startswith("email_"):
        return email_agent.AGENT_NAME
    if tool_name.startswith("calendar_"):
        return calendar_agent.AGENT_NAME
    return "unknown_agent"


def _dispatch(tool_name: str, tool_input: dict) -> dict:
    if tool_name.startswith("email_"):
        return email_agent.dispatch(tool_name, tool_input)
    if tool_name.startswith("calendar_"):
        return calendar_agent.dispatch(tool_name, tool_input)
    return {"success": False, "data": None, "error": f"No agent handles tool '{tool_name}'"}


def _remember_entities(ctx: SessionContext, tool_name: str, result: dict) -> None:
    if not result.get("success"):
        return
    data = result.get("data") or {}
    if tool_name in ("email_read_email",):
        ctx.remember_entity("email", data)
    elif tool_name in ("email_search_emails", "email_get_recent_emails"):
        emails = data.get("emails") or []
        if len(emails) == 1:
            ctx.remember_entity("email", emails[0])
    elif tool_name in ("calendar_create_event", "calendar_update_event"):
        ctx.remember_entity("event", data)
    elif tool_name in ("calendar_search_events", "calendar_get_events"):
        events = data.get("events") or []
        if len(events) == 1:
            ctx.remember_entity("event", events[0])


def _describe_action(tool_name: str, tool_input: dict) -> str:
    if tool_name == "email_send_email":
        return f"send an email to {tool_input.get('to')} with subject '{tool_input.get('subject')}'"
    if tool_name == "email_reply_email":
        return f"send a reply (email id {tool_input.get('email_id')})"
    if tool_name == "calendar_delete_event":
        return f"cancel/delete event {tool_input.get('event_id')}"
    return f"execute {tool_name} with {tool_input}"


# Grounding safety-net: local models sometimes claim an action succeeded
# in plain text without actually having called (or having failed to call)
# the corresponding tool. This maps suspicious claim phrases to the tool(s)
# that would have to appear as a SUCCESSFUL call this turn to back them up.
_CLAIM_TO_REQUIRED_TOOLS = {
    "i sent": ("email_send_email", "email_reply_email"),
    "i have sent": ("email_send_email", "email_reply_email"),
    "email has been sent": ("email_send_email", "email_reply_email"),
    "i replied": ("email_reply_email",),
    "added it to your calendar": ("calendar_create_event",),
    "added the meeting to your calendar": ("calendar_create_event",),
    "i created the event": ("calendar_create_event",),
    "i've scheduled": ("calendar_create_event",),
    "i scheduled": ("calendar_create_event",),
    "i rescheduled": ("calendar_update_event",),
    "i moved the": ("calendar_update_event",),
    "i updated the event": ("calendar_update_event",),
    "i deleted": ("calendar_delete_event",),
    "i cancelled": ("calendar_delete_event",),
    "i canceled": ("calendar_delete_event",),
}


def _verify_grounding(text: str, tool_records: list[ToolCallRecord]) -> str:
    """If the model's final answer claims it performed an action but no
    matching tool call actually succeeded this turn, replace the false
    claim with an honest correction. This is the code-level guarantee
    behind rule 3/11 of the system prompt — it does not rely on the model
    reliably following instructions."""
    lowered = text.lower()
    succeeded_tools = {tr.tool_name for tr in tool_records if tr.success}

    for phrase, required_tools in _CLAIM_TO_REQUIRED_TOOLS.items():
        if phrase in lowered and not any(t in succeeded_tools for t in required_tools):
            return (
                "I need to correct myself: I did not actually confirm that action "
                "succeeded (no successful tool call backs it up), so please don't "
                "treat it as done. Here's what actually happened this turn: "
                + (
                    "; ".join(
                        f"{tr.tool_name} -> {'succeeded' if tr.success else f'failed ({tr.error})'}"
                        for tr in tool_records
                    ) or "no tools were called."
                )
            )
    return text


def _call_ollama(messages: list[dict]) -> Any:
    try:
        return _ollama_client.chat(
            model=settings.ollama_model,
            messages=messages,
            tools=TOOLS,
            options={"temperature": 0},
        )
    except Exception as e:
        raise RuntimeError(
            f"Could not reach Ollama at {settings.ollama_host} (model '{settings.ollama_model}'). "
            f"Make sure Ollama is installed and running (`ollama serve`) and the model is pulled "
            f"(`ollama pull {settings.ollama_model}`). Original error: {e}"
        ) from e


def _extract_tool_calls(message: Any) -> list[dict]:
    """Normalizes ollama's tool_calls (attribute or dict access) into
    plain [{"name": ..., "arguments": {...}}, ...]."""
    raw_calls = getattr(message, "tool_calls", None)
    if raw_calls is None and isinstance(message, dict):
        raw_calls = message.get("tool_calls")
    if not raw_calls:
        return []

    calls = []
    for c in raw_calls:
        fn = getattr(c, "function", None) or (c.get("function") if isinstance(c, dict) else None)
        name = getattr(fn, "name", None) or (fn.get("name") if isinstance(fn, dict) else None)
        arguments = getattr(fn, "arguments", None) or (fn.get("arguments") if isinstance(fn, dict) else None)
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        calls.append({"name": name, "arguments": arguments or {}})
    return calls


def _message_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return content or ""


def _run_agent_loop(ctx: SessionContext, trace: list[str], tool_records: list[ToolCallRecord],
                     max_rounds: int = 6) -> tuple[str, dict | None]:
    for _ in range(max_rounds):
        response = _call_ollama(ctx.history)
        message = response.message if hasattr(response, "message") else response["message"]

        tool_calls = _extract_tool_calls(message)

        if not tool_calls:
            text = _message_text(message)
            ctx.history.append({"role": "assistant", "content": text})
            return text, None

        # Record the assistant's tool-call turn in history (no tool_call_id
        # needed for Ollama's simplified protocol).
        ctx.history.append({"role": "assistant", "content": _message_text(message) or ""})

        halted_for_confirmation = None
        for call in tool_calls:
            tool_name, tool_input = call["name"], call["arguments"]
            trace.append(f"Master Agent -> {_agent_for(tool_name)} -> {tool_name}({tool_input})")

            if tool_name in SENSITIVE_TOOLS:
                halted_for_confirmation = {"tool_name": tool_name, "tool_input": tool_input}
                ctx.history.append({
                    "role": "tool",
                    "name": tool_name,
                    "content": json.dumps({
                        "success": False,
                        "error": "Awaiting explicit user confirmation before executing this action.",
                    }),
                })
                continue

            result = _dispatch(tool_name, tool_input)
            _remember_entities(ctx, tool_name, result)
            tool_records.append(ToolCallRecord(
                tool_name=tool_name, tool_input=tool_input,
                tool_result=result.get("data"), success=result.get("success"),
                error=result.get("error"),
            ))
            ctx.history.append({
                "role": "tool",
                "name": tool_name,
                "content": json.dumps(result),
            })

        if halted_for_confirmation:
            ctx.set_pending(halted_for_confirmation)
            desc = _describe_action(halted_for_confirmation["tool_name"], halted_for_confirmation["tool_input"])
            return (
                f"Before I do that: {desc}. Should I go ahead? (yes/no)",
                halted_for_confirmation,
            )

    return "I wasn't able to complete this within the allowed number of steps. Could you rephrase or simplify the request?", None


def _report_confirmed_result(tool_name: str, tool_input: dict, result: dict) -> str:
    """Deterministically report the outcome of a confirmed sensitive action,
    without asking the (unreliable, local) model to summarize it — this
    avoids the model re-attempting the same sensitive tool call or
    inventing wording that doesn't match what actually happened."""
    if result.get("success"):
        if tool_name == "email_send_email":
            return f"Done — the email to {tool_input.get('to')} with subject '{tool_input.get('subject')}' was sent successfully."
        if tool_name == "email_reply_email":
            return "Done — the reply was sent successfully."
        if tool_name == "calendar_delete_event":
            return f"Done — the event ({tool_input.get('event_id')}) was cancelled/deleted successfully."
        return f"Done — {tool_name} completed successfully."
    else:
        return f"That action failed: {result.get('error')}"


def handle_message(session_id: str, message: str, confirm: bool | None = None) -> ChatResponse:
    ctx = ContextStore.get(session_id)
    if not ctx.history:
        from datetime import datetime
        now_str = datetime.now().strftime("%A, %Y-%m-%d %H:%M:%S")
        ctx.history.append({"role": "system", "content": SYSTEM_PROMPT_TEMPLATE.format(now=now_str)})

    trace: list[str] = []
    tool_records: list[ToolCallRecord] = []

    if ctx.pending_action and confirm is not None:
        pending = ctx.pending_action
        ctx.set_pending(None)

        if not confirm:
            ctx.history.append({"role": "user", "content": "The user declined to confirm that action. It was NOT performed."})
            ctx.history.append({"role": "assistant", "content": "Understood, I won't do that."})
            ContextStore.save(ctx)
            return ChatResponse(session_id=session_id, reply="Okay, I won't do that.", tool_calls=[],
                                 pending_confirmation=None, workflow_trace=[])

        result = _dispatch(pending["tool_name"], pending["tool_input"])
        _remember_entities(ctx, pending["tool_name"], result)
        tool_records.append(ToolCallRecord(
            tool_name=pending["tool_name"], tool_input=pending["tool_input"],
            tool_result=result.get("data"), success=result.get("success"), error=result.get("error"),
        ))
        trace.append(f"Master Agent -> {_agent_for(pending['tool_name'])} -> {pending['tool_name']} (confirmed)")

        final_text = _report_confirmed_result(pending["tool_name"], pending["tool_input"], result)
        # Record the real outcome in history (not asking the model to
        # re-decide anything) so future turns have accurate context.
        ctx.history.append({
            "role": "user",
            "content": f"[System note] The user confirmed the pending action. Actual tool result: "
                        f"{json.dumps(result)}. This has already been reported to the user verbatim — "
                        f"do not repeat or re-attempt it.",
        })
        ctx.history.append({"role": "assistant", "content": final_text})

        ContextStore.save(ctx)
        return ChatResponse(session_id=session_id, reply=final_text, tool_calls=tool_records,
                             pending_confirmation=None, workflow_trace=trace)

    ctx.history.append({"role": "user", "content": message})
    final_text, pending_confirmation = _run_agent_loop(ctx, trace, tool_records)
    final_text = _verify_grounding(final_text, tool_records)
    ContextStore.save(ctx)
    return ChatResponse(session_id=session_id, reply=final_text, tool_calls=tool_records,
                         pending_confirmation=pending_confirmation, workflow_trace=trace)
