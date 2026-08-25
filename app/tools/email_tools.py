"""
Email tools used by the Email Agent.

Each function returns a plain dict envelope: {"success": bool, "data": ..., "error": ...}
Larvi (the Master Agent) must NEVER claim an operation succeeded unless
`success` is True here — that guarantee is enforced in master_agent.py by
only reporting what these functions actually return.

When settings.mock_mode is True, functions operate on an in-memory mock
mailbox (app/tools/mock_data.py) so the whole system is demoable without
Gmail credentials. When False, functions call the real Gmail API via
app/auth/google_auth.py. The function signatures/return shape are
identical in both modes, so flipping MOCK_MODE is the only change needed
to go from demo to production.
"""
from __future__ import annotations
import base64
from email.mime.text import MIMEText
from typing import Optional

from app.config import settings
from app.tools import mock_data


def _ok(data: dict) -> dict:
    return {"success": True, "data": data, "error": None}


def _fail(error: str) -> dict:
    return {"success": False, "data": None, "error": error}


def _as_int(value, default: int) -> int:
    """Coerce a value that should be an int (some local LLMs send it as a
    string, e.g. limit='5' instead of limit=5)."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean(value):
    """Treat an empty string the same as None — some local LLMs send ''
    for an omitted optional field instead of leaving it out."""
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


# ---------------------------------------------------------------- search ---
def search_emails(query: Optional[str] = None, sender: Optional[str] = None,
                   subject_contains: Optional[str] = None, limit: int = 10) -> dict:
    """Search emails by free-text query, sender, and/or subject substring."""
    try:
        query, sender, subject_contains = _clean(query), _clean(sender), _clean(subject_contains)
        limit = _as_int(limit, 10)
        if settings.mock_mode:
            results = mock_data.MOCK_EMAILS
            if sender:
                results = [e for e in results if sender.lower() in e["from"].lower()]
            if subject_contains:
                results = [e for e in results if subject_contains.lower() in e["subject"].lower()]
            if query:
                q = query.lower()
                results = [e for e in results if q in e["subject"].lower() or q in e["body"].lower()]
            return _ok({"emails": results[:limit], "count": len(results[:limit])})

        from app.auth.google_auth import gmail_service
        service = gmail_service()
        parts = []
        if query:
            parts.append(query)
        if sender:
            parts.append(f"from:{sender}")
        if subject_contains:
            parts.append(f"subject:{subject_contains}")
        gmail_query = " ".join(parts) if parts else ""

        resp = service.users().messages().list(userId="me", q=gmail_query, maxResults=limit).execute()
        message_ids = [m["id"] for m in resp.get("messages", [])]
        emails = [_fetch_email_summary(service, mid) for mid in message_ids]
        return _ok({"emails": emails, "count": len(emails)})
    except Exception as e:
        return _fail(f"search_emails failed: {e}")


def _fetch_email_summary(service, message_id: str) -> dict:
    msg = service.users().messages().get(userId="me", id=message_id, format="metadata",
                                          metadataHeaders=["From", "Subject", "Date"]).execute()
    headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
    return {
        "id": message_id,
        "from": headers.get("From", ""),
        "subject": headers.get("Subject", ""),
        "snippet": msg.get("snippet", ""),
        "date": headers.get("Date", ""),
        "unread": "UNREAD" in msg.get("labelIds", []),
    }


# ------------------------------------------------------------------ read ---
def read_email(email_id: str) -> dict:
    """Fetch the full content of a single email by id."""
    try:
        if settings.mock_mode:
            email = next((e for e in mock_data.MOCK_EMAILS if e["id"] == email_id), None)
            if not email:
                return _fail(f"No email found with id '{email_id}'")
            return _ok(email)

        from app.auth.google_auth import gmail_service
        service = gmail_service()
        msg = service.users().messages().get(userId="me", id=email_id, format="full").execute()
        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
        body = _extract_body(msg["payload"])
        return _ok({
            "id": email_id,
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "body": body,
            "date": headers.get("Date", ""),
        })
    except Exception as e:
        return _fail(f"read_email failed: {e}")


def _extract_body(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and "data" in payload.get("body", {}):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        text = _extract_body(part)
        if text:
            return text
    return ""


# ------------------------------------------------------------------ list ---
def get_recent_emails(limit: int = 5, unread_only: bool = False) -> dict:
    try:
        limit = _as_int(limit, 5)
        if settings.mock_mode:
            results = mock_data.MOCK_EMAILS
            if unread_only:
                results = [e for e in results if e["unread"]]
            results = sorted(results, key=lambda e: e["date"], reverse=True)[:limit]
            return _ok({"emails": results, "count": len(results)})

        from app.auth.google_auth import gmail_service
        service = gmail_service()
        q = "is:unread" if unread_only else ""
        resp = service.users().messages().list(userId="me", q=q, maxResults=limit).execute()
        ids = [m["id"] for m in resp.get("messages", [])]
        emails = [_fetch_email_summary(service, i) for i in ids]
        return _ok({"emails": emails, "count": len(emails)})
    except Exception as e:
        return _fail(f"get_recent_emails failed: {e}")


# --------------------------------------------------------------- drafts ---
def create_draft(to: str, subject: str, body: str) -> dict:
    try:
        if settings.mock_mode:
            draft_id = mock_data.next_id("draft")
            return _ok({"draft_id": draft_id, "to": to, "subject": subject, "body": body})

        from app.auth.google_auth import gmail_service
        service = gmail_service()
        message = _build_mime_message(to, subject, body)
        draft = service.users().drafts().create(userId="me", body={"message": message}).execute()
        return _ok({"draft_id": draft["id"], "to": to, "subject": subject, "body": body})
    except Exception as e:
        return _fail(f"create_draft failed: {e}")


def _build_mime_message(to: str, subject: str, body: str) -> dict:
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {"raw": raw}


# ----------------------------------------------------------------- send ---
def send_email(to: str, subject: str, body: str) -> dict:
    """NOTE: this is a confirmation-gated action — the Master Agent must
    obtain explicit user confirmation before calling this tool."""
    try:
        if settings.mock_mode:
            sent_id = mock_data.next_id("sent")
            return _ok({"message_id": sent_id, "to": to, "subject": subject, "status": "sent"})

        from app.auth.google_auth import gmail_service
        service = gmail_service()
        message = _build_mime_message(to, subject, body)
        sent = service.users().messages().send(userId="me", body=message).execute()
        return _ok({"message_id": sent["id"], "to": to, "subject": subject, "status": "sent"})
    except Exception as e:
        return _fail(f"send_email failed: {e}")


def reply_email(email_id: str, body: str) -> dict:
    """NOTE: confirmation-gated. Replies in-thread to an existing email."""
    try:
        if settings.mock_mode:
            original = next((e for e in mock_data.MOCK_EMAILS if e["id"] == email_id), None)
            if not original:
                return _fail(f"No email found with id '{email_id}' to reply to")
            sent_id = mock_data.next_id("sent")
            return _ok({
                "message_id": sent_id,
                "to": original["from"],
                "subject": f"Re: {original['subject']}",
                "body": body,
                "status": "sent",
            })

        from app.auth.google_auth import gmail_service
        service = gmail_service()
        original = service.users().messages().get(userId="me", id=email_id, format="metadata",
                                                    metadataHeaders=["From", "Subject", "Message-ID"]).execute()
        headers = {h["name"]: h["value"] for h in original["payload"].get("headers", [])}
        message = MIMEText(body)
        message["to"] = headers.get("From", "")
        message["subject"] = f"Re: {headers.get('Subject', '')}"
        message["In-Reply-To"] = headers.get("Message-ID", "")
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = service.users().messages().send(
            userId="me", body={"raw": raw, "threadId": original.get("threadId")}
        ).execute()
        return _ok({"message_id": sent["id"], "status": "sent"})
    except Exception as e:
        return _fail(f"reply_email failed: {e}")
