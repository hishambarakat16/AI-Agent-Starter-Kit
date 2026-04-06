from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRole(str, Enum):
    user = "user"
    assistant = "assistant"

# Session
class ChatSessionCreateRequest(BaseModel):
    metadata: Optional[Dict[str, Any]] = Field(default=None)


class ChatSessionCreateResponse(BaseModel):
    session_id: str = Field(..., description="Opaque session identifier")
    created_at: datetime


# Message
class ChatMessageCreateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=20_000)
    metadata: Optional[Dict[str, Any]] = Field(default=None)


class ChatMessageResponse(BaseModel):
    message_id: str
    session_id: str
    role: ChatRole
    content: str
    created_at: datetime
    metadata: Optional[Dict[str, Any]] = Field(default=None)


class ChatMessageStreamResponse(BaseModel):
    session_id: str
    started_at: datetime


# Delete
class ChatSessionDeleteResponse(BaseModel):
    session_id: str
    deleted: bool


# Feedback
class FeedbackType(str, Enum):
    thumbs_up = "thumbs_up"
    thumbs_down = "thumbs_down"


class ChatFeedbackCreateRequest(BaseModel):
    feedback: FeedbackType
    message_id: Optional[str] = None
    reason: Optional[str] = Field(default=None, max_length=2000)
    metadata: Optional[Dict[str, Any]] = None


class ChatFeedbackCreateResponse(BaseModel):
    session_id: str
    recorded: bool
    created_at: datetime


# Handoff
class HandoffChannel(str, Enum):
    email = "email"
    phone = "phone"
    human_agent = "human_agent"


class ChatHandoffCreateRequest(BaseModel):
    channel: HandoffChannel
    notes: Optional[str] = Field(default=None, max_length=4000)
    metadata: Optional[Dict[str, Any]] = None


class ChatHandoffCreateResponse(BaseModel):
    session_id: str
    created: bool
    created_at: datetime
