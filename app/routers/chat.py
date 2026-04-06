from __future__ import annotations

import logging
from datetime import datetime
from fastapi import APIRouter, Depends, Request, status, HTTPException

from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth.oauth2 import get_current_user
from app.schemas import (
    ChatMessageCreateRequest, ChatMessageResponse, ChatSessionCreateRequest,
    ChatSessionCreateResponse, ChatSessionDeleteResponse, TokenData, ChatFeedbackCreateRequest,
    ChatFeedbackCreateResponse, FeedbackType
)

from app.repository import ChatMemoryStore , ChatRepository
from app.services import ChatService, AgentRunner, get_customer_id_for_email
from app.integrations.mcp import load_chat_mcp_servers, MCPMultiClient, MCPToolRegistry
from app.utils import RouterHelper
from langfuse import propagate_attributes, get_client

langfuse = get_client()
logger = logging.getLogger("routers")
router = APIRouter(prefix="/v1/chat", tags=["Chat"])

limiter = Limiter(key_func=get_remote_address)

store = ChatMemoryStore()
repo = ChatRepository(store=store)

mcp_client = MCPMultiClient(servers=load_chat_mcp_servers())
tool_registry = MCPToolRegistry(client=mcp_client)
agent = AgentRunner(tool_registry=tool_registry)
service = ChatService(repo=repo, agent=agent)


@router.post("/session/{session_id}/feedback", response_model=ChatFeedbackCreateResponse)
@limiter.limit("20/minute")
def create_feedback(request: Request, session_id: str, feedback_request: ChatFeedbackCreateRequest, current_user: TokenData = Depends(get_current_user)):
    email = RouterHelper.check_email(current_user)

    if feedback_request.feedback not in (FeedbackType.thumbs_up, FeedbackType.thumbs_down):
        return ChatFeedbackCreateResponse(session_id=session_id, recorded=False, created_at=datetime.utcnow())

    if not feedback_request.message_id:
        raise HTTPException(status_code=400, detail="message_id is required")

    trace_id = repo.get_message_trace_id(session_id=session_id, message_id=feedback_request.message_id, owner_email=email)

    if not trace_id:
        raise HTTPException(status_code=404, detail="trace_id not found for message")

    name = "thumbs_up" if feedback_request.feedback == FeedbackType.thumbs_up else "thumbs_down"
    value = 1 if feedback_request.feedback == FeedbackType.thumbs_up else 0
    score_id = f"{feedback_request.message_id}_{name}"
    langfuse.create_score(name=name, value=value, data_type="BOOLEAN", session_id=session_id, comment=feedback_request.reason, score_id=score_id, metadata=feedback_request.metadata)


    return ChatFeedbackCreateResponse(session_id=session_id, recorded=True, created_at=datetime.utcnow())


@router.post("/session", status_code=status.HTTP_201_CREATED, response_model=ChatSessionCreateResponse)
@limiter.limit("10/minute")
def create_chat_session(request: Request, session_request: ChatSessionCreateRequest, current_user: TokenData = Depends(get_current_user)):

    email = RouterHelper.check_email(current_user)
    customer_id = get_customer_id_for_email(email)
    resp = repo.create_session(session_request, owner_email=email, customer_id=customer_id)

    logger.info("session created session_id=%s", resp.session_id)
    logger.info("session created customer_id=%s email=%s", customer_id, email)

    return resp


@router.post("/session/{session_id}/message", status_code=status.HTTP_201_CREATED, response_model=ChatMessageResponse)
@limiter.limit("20/minute")
async def post_chat_message(request: Request, session_id: str, message_request: ChatMessageCreateRequest, current_user: TokenData = Depends(get_current_user)):

    email = RouterHelper.check_email(current_user)
    customer_id = repo.get_session_customer_id(session_id, email)

    with propagate_attributes( user_id=email, session_id=session_id,
        metadata={ "customer_id": customer_id, "endpoint": "chat_message"}):

        return await service.post_message_async(session_id=session_id, request=message_request, owner_email=email, customer_id=customer_id)



@router.post("/session/{session_id}/message:stream")
@limiter.limit("20/minute")
async def post_chat_message_stream(request: Request, session_id: str, message_request: ChatMessageCreateRequest, current_user: TokenData = Depends(get_current_user)):
    email = RouterHelper.check_email(current_user)
    customer_id = repo.get_session_customer_id(session_id, email)

    async def stream_generator():
        message_id = None
        trace_id = None
        full_text = []

        with propagate_attributes(user_id=email, session_id=session_id, metadata={"customer_id": customer_id, "endpoint": "chat_message_stream"}):
            with langfuse.start_as_current_observation(as_type="span", name="api.chat_message_stream") as span:
                async for item in service.stream_message_async(session_id=session_id, request=message_request, owner_email=email, customer_id=customer_id):
                    if isinstance(item, str):
                        full_text.append(item)
                        yield item
                    elif isinstance(item, dict):
                        message_id = item.get("message_id")
                        trace_id = item.get("trace_id")
                        assistant_text = item.get("full_text", "")

                        # Yield metadata as JSON string for frontend to parse
                        import json
                        yield json.dumps(item)

                        if assistant_text:
                            span.update_trace(input=message_request.content, output=assistant_text, metadata={"dataset": {"input": message_request.content, "output": assistant_text, "message_id": message_id}})

    return StreamingResponse(stream_generator(), media_type="text/plain")



@router.delete("/session/{session_id}", status_code=status.HTTP_200_OK, response_model=ChatSessionDeleteResponse)
@limiter.limit("10/minute")
def delete_chat_session(request: Request, session_id: str, current_user: TokenData = Depends(get_current_user)):
    email = RouterHelper.check_email(current_user)
    return repo.delete_session(session_id, owner_email=email)
