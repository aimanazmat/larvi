"""
Calendar tools used by the Calendar Agent. Same mock/real duality as
email_tools.py — see that file's docstring for the rationale.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional

from app.config import settings
from app.tools import mock_data


def _ok(data: dict) -> dict:
    return {"success": True, "data": data, "error": None}


def _fail(error: str) -> dict:
    return {"success": False, "data": None, "error": error}


def _parse(dt_str: str) -> datetime:
    """Robustly parse a datetime string. Small local LLMs sometimes send
    relative words instead of real ISO datetimes (e.g. 'now', 'today',
    'tomorrow') despite instructions — handle those gracefully instead
    of crashing, on top of normal ISO-8601 parsing."""
    if not isinstance(dt_str, str):
        raise ValueError(f"Expected a datetime string, got {dt_str!r}")

    s = dt_str.strip().lower()
    now = datetime.now()

    if s in ("now",):
        return now
    if s == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if s == "tomorrow":
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        return datetime.fromisoformat(dt_str)
    except ValueError:
        pass

    # Fallback: "now+7days" / "now+2hours" style relative expressions.
    import re
    m = re.match(r"^now\s*\+\s*(\d+)\s*(day|days|hour|hours|minute|minutes)$", s)
    if m:
        amount, unit = int(m.group(1)), m.group(2)
        if unit.startswith("day"):
            return now + timedelta(days=amount)
        if unit.startswith("hour"):
            return now + timedelta(hours=amount)
        return now + timedelta(minutes=amount)

    raise ValueError(f"Could not parse datetime string: {dt_str!r}")


def _as_int(value, default: int) -> int:
    """Coerce a value that should be an int (some local LLMs send it as a
    string, e.g. limit='5' instead of limit=5)."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ list ---
def get_events(start: Optional[str] = None, end: Optional[str] = None, limit: int = 10) -> dict:
    try:
        limit = _as_int(limit, 10)
        if settings.mock_mode:
            events = mock_data.MOCK_EVENTS
            if start:
                events = [e for e in events if _parse(e["start"]) >= _parse(start)]
            if end:
                events = [e for e in events if _parse(e["start"]) <= _parse(end)]
            return _ok({"events": events[:limit], "count": len(events[:limit])})

        from app.auth.google_auth import calendar_service
        service = calendar_service()
        params = {
            "calendarId": "primary",
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": limit,
        }
        if start:
            params["timeMin"] = _parse(start).astimezone().isoformat()
        if end:
            params["timeMax"] = _parse(end).astimezone().isoformat()
        resp = service.events().list(**params).execute()
        events = [_normalize_event(e) for e in resp.get("items", [])]
        return _ok({"events": events, "count": len(events)})
    except Exception as e:
        return _fail(f"get_events failed: {e}")


def _normalize_event(e: dict) -> dict:
    return {
        "id": e["id"],
        "title": e.get("summary", "(no title)"),
        "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date")),
        "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date")),
        "attendees": [a.get("email") for a in e.get("attendees", [])],
        "location": e.get("location", ""),
    }


# ---------------------------------------------------------------- search ---
def search_events(query: str, limit: int = 10) -> dict:
    try:
        limit = _as_int(limit, 10)
        if settings.mock_mode:
            q = query.lower()
            results = [e for e in mock_data.MOCK_EVENTS if q in e["title"].lower()]
            return _ok({"events": results[:limit], "count": len(results[:limit])})

        from app.auth.google_auth import calendar_service
        service = calendar_service()
        resp = service.events().list(calendarId="primary", q=query, singleEvents=True,
                                      orderBy="startTime", maxResults=limit).execute()
        events = [_normalize_event(e) for e in resp.get("items", [])]
        return _ok({"events": events, "count": len(events)})
    except Exception as e:
        return _fail(f"search_events failed: {e}")


# ---------------------------------------------------------- availability ---
def check_availability(start: str, end: str) -> dict:
    try:
        if settings.mock_mode:
            s, e = _parse(start), _parse(end)
            conflicts = [
                ev for ev in mock_data.MOCK_EVENTS
                if _parse(ev["start"]) < e and _parse(ev["end"]) > s
            ]
            return _ok({"available": len(conflicts) == 0, "conflicts": conflicts})

        from app.auth.google_auth import calendar_service
        service = calendar_service()
        body = {
            "timeMin": _parse(start).astimezone().isoformat(),
            "timeMax": _parse(end).astimezone().isoformat(),
            "items": [{"id": "primary"}],
        }
        resp = service.freebusy().query(body=body).execute()
        busy = resp["calendars"]["primary"]["busy"]
        return _ok({"available": len(busy) == 0, "conflicts": busy})
    except Exception as e:
        return _fail(f"check_availability failed: {e}")


# ---------------------------------------------------------------- create ---
def create_event(title: str, start: str, end: str, attendees: Optional[list[str]] = None,
                  location: Optional[str] = None) -> dict:
    try:
        if settings.mock_mode:
            event = {
                "id": mock_data.next_id("event"),
                "title": title,
                "start": start,
                "end": end,
                "attendees": attendees or [],
                "location": location or "",
            }
            mock_data.MOCK_EVENTS.append(event)
            return _ok(event)

        from app.auth.google_auth import calendar_service
        service = calendar_service()
        body = {
            "summary": title,
            "start": {"dateTime": _parse(start).astimezone().isoformat()},
            "end": {"dateTime": _parse(end).astimezone().isoformat()},
            "location": location or "",
            "attendees": [{"email": a} for a in (attendees or [])],
        }
        created = service.events().insert(calendarId="primary", body=body).execute()
        return _ok(_normalize_event(created))
    except Exception as e:
        return _fail(f"create_event failed: {e}")


# ---------------------------------------------------------------- update ---
def update_event(event_id: str, title: Optional[str] = None, start: Optional[str] = None,
                  end: Optional[str] = None, location: Optional[str] = None) -> dict:
    """Covers both 'update details' and 'reschedule' (start/end change)."""
    try:
        if settings.mock_mode:
            event = next((e for e in mock_data.MOCK_EVENTS if e["id"] == event_id), None)
            if not event:
                return _fail(f"No event found with id '{event_id}'")
            if title:
                event["title"] = title
            if start:
                event["start"] = start
            if end:
                event["end"] = end
            if location:
                event["location"] = location
            return _ok(event)

        from app.auth.google_auth import calendar_service
        service = calendar_service()
        existing = service.events().get(calendarId="primary", eventId=event_id).execute()
        if title:
            existing["summary"] = title
        if start:
            existing["start"] = {"dateTime": _parse(start).astimezone().isoformat()}
        if end:
            existing["end"] = {"dateTime": _parse(end).astimezone().isoformat()}
        if location:
            existing["location"] = location
        updated = service.events().update(calendarId="primary", eventId=event_id, body=existing).execute()
        return _ok(_normalize_event(updated))
    except Exception as e:
        return _fail(f"update_event failed: {e}")


# ---------------------------------------------------------------- delete ---
def delete_event(event_id: str) -> dict:
    """NOTE: confirmation-gated (cancel/delete). Master Agent must confirm
    with the user before calling this for anything but trivial events."""
    try:
        if settings.mock_mode:
            before = len(mock_data.MOCK_EVENTS)
            mock_data.MOCK_EVENTS[:] = [e for e in mock_data.MOCK_EVENTS if e["id"] != event_id]
            if len(mock_data.MOCK_EVENTS) == before:
                return _fail(f"No event found with id '{event_id}'")
            return _ok({"deleted_id": event_id})

        from app.auth.google_auth import calendar_service
        service = calendar_service()
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return _ok({"deleted_id": event_id})
    except Exception as e:
        return _fail(f"delete_event failed: {e}")
