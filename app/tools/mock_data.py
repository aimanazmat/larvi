"""
Mock Gmail/Calendar data so Larvi's full agent pipeline (Master Agent ->
Email/Calendar Agent -> Tool -> Result) can be demonstrated end-to-end
without Google Cloud setup. Swap MOCK_MODE=false once real OAuth is wired
up (app/auth/google_auth.py) and the pipeline hits real APIs instead —
the tool function signatures are identical either way.
"""
from __future__ import annotations
import itertools
from datetime import datetime, timedelta

_id_counter = itertools.count(1000)

now = datetime.now()

MOCK_EMAILS: list[dict] = [
    {
        "id": "email-1",
        "from": "ahmed@example.com",
        "subject": "Project Meeting Tomorrow",
        "snippet": "Hi, let's meet tomorrow at 3 PM to discuss the project milestones.",
        "body": "Hi,\n\nLet's meet tomorrow at 3 PM to discuss the project milestones and next steps for the capstone.\n\nBest,\nAhmed",
        "date": (now + timedelta(days=0)).isoformat(),
        "unread": True,
    },
    {
        "id": "email-2",
        "from": "ali@example.com",
        "subject": "Re: Design Review",
        "snippet": "Sounds good, I'll send the updated mockups by Friday.",
        "body": "Sounds good, I'll send the updated mockups by Friday.\n\nAli",
        "date": (now - timedelta(days=1)).isoformat(),
        "unread": False,
    },
    {
        "id": "email-3",
        "from": "hr@example.com",
        "subject": "Internship Weekly Update",
        "snippet": "Please submit your weekly progress report by end of day.",
        "body": "Please submit your weekly progress report by end of day Friday.",
        "date": (now - timedelta(days=2)).isoformat(),
        "unread": True,
    },
]

MOCK_EVENTS: list[dict] = [
    {
        "id": "event-1",
        "title": "Weekly Sync",
        "start": (now + timedelta(days=1, hours=2)).isoformat(),
        "end": (now + timedelta(days=1, hours=3)).isoformat(),
        "attendees": ["ali@example.com"],
        "location": "Zoom",
    }
]


def next_id(prefix: str) -> str:
    return f"{prefix}-{next(_id_counter)}"
