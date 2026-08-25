"""
Context & state management for Larvi.

Each session keeps:
  - `history`: the raw Claude message list (for multi-turn tool-calling)
  - `last_entities`: the most recently referenced email / event, so
    follow-ups like "move IT to 5pm" resolve correctly.
  - `pending_action`: an action awaiting user confirmation (send/delete/etc).

Backed by a JSON file on disk (storage/sessions.json) so state survives
restarts. Swap `_load`/`_save` for a real DB (Postgres/Redis) in production.
"""
from __future__ import annotations
import json
import os
import threading
from typing import Any, Optional

from app.config import settings

_LOCK = threading.Lock()
_STORE_PATH = os.path.join(os.path.dirname(settings.state_db_path), "sessions.json")


def _ensure_dir():
    os.makedirs(os.path.dirname(_STORE_PATH), exist_ok=True)


def _load_all() -> dict[str, Any]:
    _ensure_dir()
    if not os.path.exists(_STORE_PATH):
        return {}
    try:
        with open(_STORE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def _save_all(data: dict[str, Any]) -> None:
    _ensure_dir()
    with open(_STORE_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)


class SessionContext:
    """In-memory view of a single session's state, persisted on save()."""

    def __init__(self, session_id: str, raw: dict[str, Any]):
        self.session_id = session_id
        self.history: list[dict[str, Any]] = raw.get("history", [])
        self.last_entities: dict[str, Any] = raw.get("last_entities", {})
        self.pending_action: Optional[dict[str, Any]] = raw.get("pending_action")

    def remember_entity(self, kind: str, entity: dict[str, Any]) -> None:
        """kind is e.g. 'email' or 'event'. Used to resolve follow-up
        references such as 'move it to 5pm' or 'reply to that email'."""
        self.last_entities[kind] = entity

    def get_entity(self, kind: str) -> Optional[dict[str, Any]]:
        return self.last_entities.get(kind)

    def set_pending(self, action: Optional[dict[str, Any]]) -> None:
        self.pending_action = action

    def to_dict(self) -> dict[str, Any]:
        return {
            "history": self.history,
            "last_entities": self.last_entities,
            "pending_action": self.pending_action,
        }


class ContextStore:
    """Thread-safe load/save of sessions keyed by session_id."""

    @staticmethod
    def get(session_id: str) -> SessionContext:
        with _LOCK:
            all_data = _load_all()
            raw = all_data.get(session_id, {})
            return SessionContext(session_id, raw)

    @staticmethod
    def save(ctx: SessionContext) -> None:
        with _LOCK:
            all_data = _load_all()
            all_data[ctx.session_id] = ctx.to_dict()
            _save_all(all_data)

    @staticmethod
    def reset(session_id: str) -> None:
        with _LOCK:
            all_data = _load_all()
            all_data.pop(session_id, None)
            _save_all(all_data)
