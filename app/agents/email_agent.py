"""
Email Agent.

Exposes its tools as Claude-compatible tool schemas and dispatches calls
to app/tools/email_tools.py. The Master Agent treats this module as a
black box: it only sees tool names/schemas and results.
"""
from app.tools import email_tools

AGENT_NAME = "email_agent"

TOOL_SCHEMAS = [
    {
        "name": "email_search_emails",
        "description": (
            "Search emails by free-text query, sender, and/or subject substring. "
            "Use for requests like 'find emails from Ahmed' or 'find the email about the meeting'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text/keyword search"},
                "sender": {"type": "string", "description": "Filter by sender name or email"},
                "subject_contains": {"type": "string", "description": "Substring to match in subject"},
                "limit": {"type": "integer", "description": "Max results", "default": 10},
            },
        },
    },
    {
        "name": "email_read_email",
        "description": (
            "Read the full content (body) of a single email given its id. "
            "email_id MUST be a real id from email_search_emails or "
            "email_get_recent_emails (e.g. 'email-3'), never the subject line."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"email_id": {"type": "string"}},
            "required": ["email_id"],
        },
    },
    {
        "name": "email_get_recent_emails",
        "description": "Get the most recent emails, optionally filtered to unread only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 5},
                "unread_only": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "email_create_draft",
        "description": "Create a draft email (does not send it).",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "email_send_email",
        "description": (
            "Send a NEW email immediately (it actually goes out — use this whenever the "
            "user says 'send'). This is a sensitive/destructive-class action — only call "
            "this after the user has explicitly confirmed. If not yet confirmed, ask the "
            "user to confirm first instead of calling this tool. Do NOT call "
            "email_create_draft instead of this when the user asked to send."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "email_reply_email",
        "description": (
            "Reply in-thread to an existing email by id. Sensitive action — only call after "
            "explicit user confirmation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["email_id", "body"],
        },
    },
]

_DISPATCH = {
    "email_search_emails": lambda **kw: email_tools.search_emails(**kw),
    "email_read_email": lambda **kw: email_tools.read_email(**kw),
    "email_get_recent_emails": lambda **kw: email_tools.get_recent_emails(**kw),
    "email_create_draft": lambda **kw: email_tools.create_draft(**kw),
    "email_send_email": lambda **kw: email_tools.send_email(**kw),
    "email_reply_email": lambda **kw: email_tools.reply_email(**kw),
}

# Tools that must never fire without prior explicit user confirmation.
SENSITIVE_TOOLS = {"email_send_email", "email_reply_email"}


def dispatch(tool_name: str, tool_input: dict) -> dict:
    if tool_name not in _DISPATCH:
        return {"success": False, "data": None, "error": f"Unknown email tool '{tool_name}'"}
    return _DISPATCH[tool_name](**tool_input)
