import re
from typing import Sequence, Optional, Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from app.utils.ai_helper import AIHelper

class LLMGuard:

    _UUID_RE = re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    )
    _EMAIL_RE = re.compile(
        r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"
    )
    _PHONE_RE = re.compile(
        r"(?:(?:\+?\d{1,3}[\s\-\.]?)?(?:\(?\d{2,4}\)?[\s\-\.]?)?\d{3,4}[\s\-\.]?\d{4})(?:\s*(?:x|ext\.?)\s*\d{1,6})?\b",
        re.IGNORECASE,
    )

    _LOOKUP_PHRASES = (
        "customer id",
        "account id",
        "account number",
        "transaction id",
        "tx id",
        "user id",
        "this is my email",
        "my email is",
        "this is my phone",
        "my phone is",
        "use this email",
        "use this phone",
        "lookup",
        "search",
        "find my",
        "for customer",
        "for account",
        "for user",
        "using my",
        "by email",
        "by phone",
        "by customer",
    )

    _THIRD_PARTY_PHRASES = (
        "my friend",
        "my wife",
        "my husband",
        "my brother",
        "my sister",
        "my dad",
        "my father",
        "my mom",
        "my mother",
        "someone else",
        "another person",
        "for him",
        "for her",
        "their account",
        "his account",
        "her account",
    )
   
    _AGGREGATE_INTENT_RE = re.compile(
        r"\b("
        r"top\s+users|top\s+customers|highest\s+income|highest\s+balance|richest|"
        r"rank|leaderboard|all\s+users|all\s+customers|list\s+users|list\s+customers|"
        r"by\s+income|by\s+balance|by\s+spend|by\s+transactions|"
        r"average\s+income|median\s+income|distribution|percentile|"
        r"export\s+users|dump\s+users|download\s+users"
        r")\b",
        re.IGNORECASE,
    )

    _THIRD_PARTY_DATA_RE = re.compile(
        r"\b("
        r"my\s+(son|daughter|wife|husband|friend|father|mother|brother|sister)|"
        r"someone\s+else|another\s+person"
        r")\b",
        re.IGNORECASE,
    )
    
    
    
    @staticmethod
    def _last_human_text(messages: Sequence[BaseMessage]) -> str:
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                return (m.content or "").strip()
        return ""

    @staticmethod
    def is_cross_user_or_aggregate_request(messages: Sequence[BaseMessage]) -> bool:
        text = LLMGuard._last_human_text(messages)
        if not text:
            return False
        return bool(
            LLMGuard._AGGREGATE_INTENT_RE.search(text)
            or LLMGuard._THIRD_PARTY_DATA_RE.search(text)
        )

    @staticmethod
    def contains_identifier(text: str) -> bool:
        if not text:
            return False
        return bool(
            LLMGuard._UUID_RE.search(text)
            or LLMGuard._EMAIL_RE.search(text)
            or LLMGuard._PHONE_RE.search(text)
        )

    @staticmethod
    def cross_user_block_response() -> str:
        return (
            "I can’t help with requests about other people or any cross-user/aggregate customer data. "
            "I can only help with the account linked to your current login.\n\n"
            "If you want your own info, say for example:\n"
            "- show my profile\n"
            "- show my accounts\n"
            "- show my transactions"
        )

    @staticmethod
    def contains_lookup_phrase(text: str) -> bool:
        t = (text or "").lower()
        if not t:
            return False
        return any(p in t for p in LLMGuard._LOOKUP_PHRASES)

    @staticmethod
    def contains_third_party_intent(text: str) -> bool:
        t = (text or "").lower()
        if not t:
            return False
        return any(p in t for p in LLMGuard._THIRD_PARTY_PHRASES)

    @staticmethod
    def should_block_identity_lookup(messages: Sequence[BaseMessage]) -> bool:
        text = LLMGuard._last_human_text(messages)
        if not text:
            return False

        if LLMGuard.contains_identifier(text):
            return True

        return False
    
    
    @staticmethod
    def identity_block_response() -> str:
        return (
            "Sorry — I can’t use identifiers shared in chat (customer IDs, account IDs, emails, or phone numbers) "
            "to look up account information. I can only access the account linked to your current login.\n\n"
            "If you’d like, ask directly without identifiers, e.g.:\n"
            "- show my profile\n"
            "- show my accounts\n"
            "- show my transactions"
        )

    @staticmethod
    def make_block_ai_message() -> AIMessage:
        return AIMessage(content=LLMGuard.identity_block_response())

