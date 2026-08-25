"""
Larvi Master Agent.

Flow:  User -> Master Agent -> (Email Agent | Calendar Agent) -> Tool/API -> Result -> Master Agent -> User

Implementation notes:
  - Claude's native tool-use IS the "select the correct specialized agent"
    step: every tool is namespaced (`email_*` / `calendar_*`), so when
    Claude picks a tool it has implicitly picked an agent. We log that
    choice into `workflow_trace` for transparency/debugging.
  - Multi-step workflows (e.g. "find Ahmed's email about the meeting and
    add it to my calendar") fall out naturally: Claude can call an
    email_* tool, read the result, then decide to call a calendar_* tool
    in the same turn, before producing a final answer.
  - Sensitive actions (send_email, reply_email, delete_event) are
    intercepted BEFORE execution: instead of running them, Larvi stores
    the pending tool call in session context and asks the user to
    confirm. Only on an explicit confirm=True does the tool actually run.
  - Larvi never claims success unless the tool's own `success` field says
    so — the final-answer prompt instructs Claude accordingly, and the
    tool results (ground truth) are what get fed back to Claude.
"""
from __future__ import annotations
import json
from typing import Any

import anthropic

from app.config import settings
from app.core.context import ContextStore, SessionContext
from app.core.schemas import ChatResponse, ToolCallRecord
from app.agents import email_agent, calendar_agent

SYSTEM_PROMPT = """\
You are Larvi, an autonomous Email and Calendar assistant.

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
"""

ALL_TOOLS = email_agent.TOOL_SCHEMAS + calendar_agent.TOOL_SCHEMAS
SENSITIVE_TOOLS = email_agent.SENSITIVE_TOOLS | calendar_agent.SENSITIVE_TOOLS

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None


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
    """After a successful lookup, remember the single most-relevant entity
    so follow-ups ('move it to 5pm') resolve correctly."""
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


def _call_claude(messages: list[dict]) -> Any:
    if _client is None:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to your .env file (see .env.example)."
        )
    return _client.messages.create(
        model=settings.claude_model,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        tools=ALL_TOOLS,
        messages=messages,
    )


def _run_agent_loop(ctx: SessionContext, trace: list[str], tool_records: list[ToolCallRecord],
                     max_rounds: int = 6) -> tuple[str, dict | None]:
    """Runs the Claude tool-use loop. Returns (final_text, pending_confirmation_or_None).
    If a sensitive tool is requested, execution stops there and a pending
    confirmation dict is returned instead of a final answer."""
    for _ in range(max_rounds):
        response = _call_claude(ctx.history)
        assistant_content = [block.model_dump() for block in response.content]
        ctx.history.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text")
            return text, None

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        tool_result_content = []
        halted_for_confirmation = None

        for block in tool_use_blocks:
            tool_name, tool_input, tool_use_id = block.name, block.input, block.id
            trace.append(f"Master Agent -> {_agent_for(tool_name)} -> {tool_name}({tool_input})")

            if tool_name in SENSITIVE_TOOLS:
                halted_for_confirmation = {
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "tool_use_id": tool_use_id,
                }
                # Satisfy the API contract: every tool_use needs a tool_result
                # in the same turn, even if we're deferring real execution.
                tool_result_content.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
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
            tool_result_content.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps(result),
            })

        ctx.history.append({"role": "user", "content": tool_result_content})

        if halted_for_confirmation:
            ctx.set_pending(halted_for_confirmation)
            desc = _describe_action(halted_for_confirmation["tool_name"], halted_for_confirmation["tool_input"])
            return (
                f"Before I do that: {desc}. Should I go ahead? (yes/no)",
                halted_for_confirmation,
            )

    return "I wasn't able to complete this within the allowed number of steps. Could you rephrase or simplify the request?", None


def _describe_action(tool_name: str, tool_input: dict) -> str:
    if tool_name == "email_send_email":
        return f"send an email to {tool_input.get('to')} with subject '{tool_input.get('subject')}'"
    if tool_name == "email_reply_email":
        return f"send a reply (email id {tool_input.get('email_id')})"
    if tool_name == "calendar_delete_event":
        return f"cancel/delete event {tool_input.get('event_id')}"
    return f"execute {tool_name} with {tool_input}"


def handle_message(session_id: str, message: str, confirm: bool | None = None) -> ChatResponse:
    ctx = ContextStore.get(session_id)
    trace: list[str] = []
    tool_records: list[ToolCallRecord] = []

    if ctx.pending_action and confirm is not None:
        pending = ctx.pending_action
        ctx.set_pending(None)

        if not confirm:
            # Tell Claude the action was declined so it can respond naturally.
            ctx.history.append({"role": "user", "content": "The user declined to confirm that action. Do not perform it."})
        else:
            result = _dispatch(pending["tool_name"], pending["tool_input"])
            _remember_entities(ctx, pending["tool_name"], result)
            tool_records.append(ToolCallRecord(
                tool_name=pending["tool_name"], tool_input=pending["tool_input"],
                tool_result=result.get("data"), success=result.get("success"), error=result.get("error"),
            ))
            trace.append(f"Master Agent -> {_agent_for(pending['tool_name'])} -> {pending['tool_name']} (confirmed)")
            ctx.history.append({
                "role": "user",
                "content": f"The user confirmed. Tool result: {json.dumps(result)}. "
                            f"Report the real outcome to the user (success or failure), using these details.",
            })

        final_text, pending_confirmation = _run_agent_loop(ctx, trace, tool_records)
        ContextStore.save(ctx)
        return ChatResponse(session_id=session_id, reply=final_text, tool_calls=tool_records,
                             pending_confirmation=pending_confirmation, workflow_trace=trace)

    ctx.history.append({"role": "user", "content": message})
    final_text, pending_confirmation = _run_agent_loop(ctx, trace, tool_records)
    ContextStore.save(ctx)
    return ChatResponse(session_id=session_id, reply=final_text, tool_calls=tool_records,
                         pending_confirmation=pending_confirmation, workflow_trace=trace)
