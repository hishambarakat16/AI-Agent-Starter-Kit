from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from ..schemas import ChatMessageResponse


@dataclass
class ChatMemoryStore:
    """
    Simple in-memory persistence for sessions and messages.
    Replace later with SQLAlchemy models + DB sessions.
    """
    sessions: Dict[str, List[ChatMessageResponse]] = field(default_factory=dict)
    session_owner: Dict[str, str] = field(default_factory=dict)
    session_customer_id: Dict[str, str] = field(default_factory=dict)
