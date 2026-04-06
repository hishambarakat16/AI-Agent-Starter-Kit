from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional, Any, Dict
from uuid import uuid4

from fastapi import HTTPException, status

from app.schemas import (
    ChatMessageCreateRequest, ChatMessageResponse, ChatRole,
    ChatSessionCreateRequest, ChatSessionCreateResponse, ChatSessionDeleteResponse,
)

from .chat_store import ChatMemoryStore
from app.utils import RouterHelper

class ChatRepository:
    
    def __init__(self, store: ChatMemoryStore):
        self.store = store

    def create_session( self,request: ChatSessionCreateRequest, *, owner_email: str, customer_id: str, ) -> ChatSessionCreateResponse:
        
        session_id = uuid4().hex
        self.store.sessions[session_id] = []
        self.store.session_owner[session_id] = owner_email
        self.store.session_customer_id[session_id] = customer_id
        return ChatSessionCreateResponse(session_id=session_id, created_at=datetime.now(UTC))

    def get_session_customer_id(self, session_id: str, owner_email: str) -> str:
        RouterHelper.check_session(session_id, self.store.sessions, self.store.session_owner, owner_email)

        customer_id = self.store.session_customer_id.get(session_id)
        if not customer_id:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Session missing customer_id")

        return customer_id

    def add_user_message( self, session_id: str, request: ChatMessageCreateRequest,*, owner_email: str ) -> ChatMessageResponse:
        return self._add_message(session_id, ChatRole.user, request.content, owner_email)

    def add_assistant_message(self, session_id: str, content: str, *, owner_email: str, trace_id: Optional[str] = None) -> ChatMessageResponse:
        md = {}
        if trace_id:
            md["trace_id"] = trace_id

        return self._add_message(session_id, ChatRole.assistant, content, owner_email, metadata=md or None,)

    def update_assistant_message(self, session_id: str, message_id: str, content: str, *, owner_email: str, trace_id: Optional[str] = None) -> None:
        msg = self.get_message(session_id=session_id, message_id=message_id, owner_email=owner_email)
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")

        msg.content = content
        if trace_id:
            if not msg.metadata:
                msg.metadata = {}
            msg.metadata["trace_id"] = trace_id
    
    def get_history(self, session_id: str, *, owner_email: str) -> list[ChatMessageResponse]:
        RouterHelper.check_session(session_id, self.store.sessions, self.store.session_owner, owner_email)

        return list(self.store.sessions[session_id])

    def clear_history(self, session_id: str, *, owner_email: str) -> None:
        RouterHelper.check_session(session_id, self.store.sessions, self.store.session_owner, owner_email)
        self.store.sessions[session_id] = []

    def delete_session(self, session_id: str, *, owner_email: str) -> ChatSessionDeleteResponse:
        RouterHelper.check_session(session_id, self.store.sessions, self.store.session_owner, owner_email)

        del self.store.sessions[session_id]
        self.store.session_owner.pop(session_id, None)
        self.store.session_customer_id.pop(session_id, None)
        return ChatSessionDeleteResponse(session_id=session_id, deleted=True)


    def _add_message(self, session_id: str, role: ChatRole, content: str, owner_email: str, metadata: Optional[dict] = None,) -> ChatMessageResponse:
        RouterHelper.check_session(session_id, self.store.sessions, self.store.session_owner, owner_email)

        message = ChatMessageResponse( message_id=uuid4().hex, session_id=session_id, role=role, content=content,created_at=datetime.now(UTC), metadata=metadata)
        self.store.sessions[session_id].append(message)
        return message

    def get_message_trace_id(self, session_id: str, message_id: str, owner_email: str) -> Optional[str]:
        msg = self.get_message(session_id=session_id, message_id=message_id, owner_email=owner_email)
        if not msg:
            return None
        md = getattr(msg, "metadata", None) or {}
        return md.get("trace_id")

    def get_message(self, session_id: str, message_id: str, *, owner_email: str) -> Optional[ChatMessageResponse]:
        RouterHelper.check_session(session_id, self.store.sessions, self.store.session_owner, owner_email)
        for m in self.store.sessions[session_id]:
            if m.message_id == message_id:
                return m
        return None