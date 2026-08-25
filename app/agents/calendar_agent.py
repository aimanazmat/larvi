"""
Calendar Agent. Same pattern as email_agent.py.
"""
from app.tools import calendar_tools

AGENT_NAME = "calendar_agent"

TOOL_SCHEMAS = [
    {
        "name": "calendar_get_events",
        "description": (
            "Get upcoming events, optionally within a start/end ISO-8601 range. "
            "IMPORTANT: when the user asks for 'upcoming meetings' or 'what's coming up' "
            "without naming a specific date, call this with NO start and NO end argument "
            "at all (omit both keys entirely) so every future event is considered — do not "
            "guess a narrow range like just today. Example correct call for 'what meetings "
            "do I have coming up?': calendar_get_events(limit=10) with no start/end."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start": {"type": "string", "description": "ISO-8601 datetime, inclusive lower bound"},
                "end": {"type": "string", "description": "ISO-8601 datetime, inclusive upper bound"},
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "calendar_search_events",
        "description": "Search events by title/keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "calendar_check_availability",
        "description": "Check whether the user is free between two ISO-8601 datetimes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start": {"type": "string"},
                "end": {"type": "string"},
            },
            "required": ["start", "end"],
        },
    },
    {
        "name": "calendar_create_event",
        "description": "Create a new calendar event.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string", "description": "ISO-8601 datetime"},
                "end": {"type": "string", "description": "ISO-8601 datetime"},
                "attendees": {"type": "array", "items": {"type": "string"}},
                "location": {"type": "string"},
            },
            "required": ["title", "start", "end"],
        },
    },
    {
        "name": "calendar_update_event",
        "description": (
            "Update an existing event's title/time/location. Also used to RESCHEDULE "
            "an event (pass new start/end). event_id MUST be a real id string returned "
            "by calendar_get_events or calendar_search_events (e.g. 'event-1001') — "
            "never the event's title. If you don't have the real id yet, call "
            "calendar_get_events or calendar_search_events first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "title": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "calendar_delete_event",
        "description": (
            "Cancel/delete an event. Sensitive action — only call after explicit user "
            "confirmation. event_id MUST be a real id from calendar_get_events or "
            "calendar_search_events (e.g. 'event-1001'), never the event's title."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "string"}},
            "required": ["event_id"],
        },
    },
]

_DISPATCH = {
    "calendar_get_events": lambda **kw: calendar_tools.get_events(**kw),
    "calendar_search_events": lambda **kw: calendar_tools.search_events(**kw),
    "calendar_check_availability": lambda **kw: calendar_tools.check_availability(**kw),
    "calendar_create_event": lambda **kw: calendar_tools.create_event(**kw),
    "calendar_update_event": lambda **kw: calendar_tools.update_event(**kw),
    "calendar_delete_event": lambda **kw: calendar_tools.delete_event(**kw),
}

SENSITIVE_TOOLS = {"calendar_delete_event"}


def dispatch(tool_name: str, tool_input: dict) -> dict:
    if tool_name not in _DISPATCH:
        return {"success": False, "data": None, "error": f"Unknown calendar tool '{tool_name}'"}
    return _DISPATCH[tool_name](**tool_input)
