"""
Larvi configuration.

All secrets are loaded from environment variables (see .env.example).
NOTHING sensitive is hard-coded here.
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # --- LLM ---
    # LLM_BACKEND selects which model powers the Master Agent's reasoning:
    #   "ollama"    -> free, local model via Ollama (no API key, no cost)
    #   "anthropic" -> Claude via the paid Anthropic API
    llm_backend: str = os.getenv("LLM_BACKEND", "ollama")

    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.1")

    # --- Google OAuth ---
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_redirect_uri: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback")
    google_token_path: str = os.getenv("GOOGLE_TOKEN_PATH", "storage/token.json")
    google_credentials_path: str = os.getenv("GOOGLE_CREDENTIALS_PATH", "storage/credentials.json")

    # --- App behavior ---
    # MOCK_MODE=true lets Larvi run and be demoed WITHOUT real Google credentials.
    # Set to false once you've completed Google Cloud / OAuth setup (see README).
    mock_mode: bool = os.getenv("MOCK_MODE", "true").lower() == "true"

    # Actions that require explicit user confirmation before executing.
    confirmation_required_actions: tuple = (
        "send_email",
        "reply_email",
        "delete_event",
        "delete_email",
    )

    # --- Storage ---
    state_db_path: str = os.getenv("STATE_DB_PATH", "storage/larvi_state.sqlite3")

    # --- Server ---
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))


settings = Settings()

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]

CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]

ALL_SCOPES = GMAIL_SCOPES + CALENDAR_SCOPES
