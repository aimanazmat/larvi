"""Shared data models for Larvi."""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Conversation/session identifier")
    message: str = Field(..., description="User's natural-language instruction")
    confirm: Optional[bool] = Field(
        None, description="If replying to a pending confirmation, true/false"
    )


class ToolCallRecord(BaseModel):
    tool_name: str
    tool_input: dict[str, Any]
    tool_result: Optional[dict[str, Any]] = None
    success: Optional[bool] = None
    error: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    pending_confirmation: Optional[dict[str, Any]] = None
    workflow_trace: list[str] = Field(default_factory=list)


class ToolResult(BaseModel):
    """Standard envelope every tool must return. Larvi only reports success
    if `success` is True and it came directly from a real tool/API call."""
    success: bool
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None
