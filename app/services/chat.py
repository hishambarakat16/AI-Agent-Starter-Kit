from __future__ import annotations

import logging
from typing import AsyncIterator, List

from langchain_core.messages import AIMessage, HumanMessage

from app.repository import ChatRepository
from app.schemas import ChatMessageCreateRequest, ChatMessageResponse
from .agent_runner import AgentRunner
from app.utils import LoggingHelper


logger = logging.getLogger("services")


class ChatService:
    """
    NOTE:
    Repository calls are currently synchronous and in-memory.
    This is safe for now. If repo becomes I/O-bound (DB, Redis),
    these calls MUST be made async.
    """

    def __init__(self, repo: ChatRepository, agent: AgentRunner):
        self.repo = repo
        self.agent = agent

    async def post_message_async( self, session_id: str, request: ChatMessageCreateRequest, owner_email: str, customer_id: str) -> ChatMessageResponse:
        self.repo.add_user_message(session_id=session_id, request=request, owner_email=owner_email)
        history = self.repo.get_history(session_id, owner_email=owner_email)
        
        logger.info("chat history loaded session_id=%s messages=%d", LoggingHelper._short_id(session_id), len(history))

        lc_messages = self.tranform_history_into_lc_messages(history)

        assistant_text, trace_id = await self.agent.ainvoke(lc_messages, customer_id=customer_id, repo=self.repo, session_id=session_id, owner_email=owner_email,)

        msg = self.repo.add_assistant_message( session_id=session_id, content=assistant_text.strip(), owner_email=owner_email, trace_id=trace_id)

        return msg

    async def stream_message_async(self, session_id: str, request: ChatMessageCreateRequest, owner_email: str, customer_id: str):

        self.repo.add_user_message(session_id=session_id, request=request, owner_email=owner_email)
        history = self.repo.get_history(session_id, owner_email=owner_email)

        lc_messages = self.tranform_history_into_lc_messages(history)

        placeholder_msg = self.repo.add_assistant_message(session_id=session_id, content="", owner_email=owner_email, trace_id=None)

        full_text = []
        trace_id = None

        async for chunk, tid in self.agent.astream(lc_messages, customer_id=customer_id, repo=self.repo, session_id=session_id, owner_email=owner_email):
            if chunk:
                full_text.append(chunk)
                yield chunk
            if tid:
                trace_id = tid

        assistant_text = "".join(full_text).strip()

        self.repo.update_assistant_message(session_id=session_id, message_id=placeholder_msg.message_id, content=assistant_text, owner_email=owner_email, trace_id=trace_id)

        yield {"message_id": placeholder_msg.message_id, "trace_id": trace_id, "full_text": assistant_text}



    def tranform_history_into_lc_messages(self, history: list[ChatMessageResponse]):
        lc_messages: List[HumanMessage | AIMessage] = []
        for msg in history:
            if msg.role == "user":
                lc_messages.append(HumanMessage(content=msg.content))
            else:
                lc_messages.append(AIMessage(content=msg.content))
        return lc_messages


# Debugging Code
        # delay = float(os.getenv("DEBUG_CHAT_DELAY_SECONDS", "0") or 0)
        # if delay > 0:
        #     logger.debug(
        #         "debug delay enabled session_id=%s delay_seconds=%.3f",
        #         LoggingHelper._short_id(session_id),
        #         delay,
        #     )
        #     await asyncio.sleep(delay)
