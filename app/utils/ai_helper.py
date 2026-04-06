
import logging
from typing import Sequence, Optional, Any, List, Dict
import json
import re
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage

from app.utils import Utils

logger_services = logging.getLogger("services")

class AIHelper:
    SENSITIVE_KEYS = {
        "customer_id", "account_id", "tx_id", "user_id", "id", "email", "phone", "mobile"
    }
    _UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")

    @staticmethod
    def redact_customer_id_output(text: str) -> str:
        if not text:
            return text
        s = text
        s = re.sub(r"(?im)^\s*Customer\s*ID\s*:\s*.*\n?", "", s)
        if re.search(r"(?i)\bcustomer\s*id\b", text):
            s = AIHelper._UUID_RE.sub("[hidden]", s)

        s = re.sub(r"\n{3,}", "\n\n", s).strip()
        return s
    
    @staticmethod
    def _strip_sensitive(obj: Any) -> Any:
        if obj is None:
            return None
        if isinstance(obj, dict):
            out: Dict[str, Any] = {}
            for k, v in obj.items():
                lk = str(k).lower()
                if lk in AIHelper.SENSITIVE_KEYS or lk.endswith("_id"):
                    continue
                out[k] = AIHelper._strip_sensitive(v)
            return out
        if isinstance(obj, list):
            return [AIHelper._strip_sensitive(x) for x in obj]
        return obj

    
    @staticmethod
    def tool_step_inputs(state: dict) -> tuple[int, BaseMessage, list[ToolMessage], Optional[str], list[dict[str, Any]]]:
        rounds = state["tool_rounds"] + 1
        last = state["messages"][-1]
        out: list[ToolMessage] = []
        customer_id = state.get("customer_id")
        tool_calls = getattr(last, "tool_calls", None) or []
        return rounds, out, customer_id, tool_calls
    
    @staticmethod
    def _last_ai_text(messages: Sequence[BaseMessage]) -> str:
        last_ai = next(
            (
                m
                for m in reversed(messages)
                if isinstance(m, AIMessage) and (m.content or "").strip()
            ),
            None,
        )
        return ((last_ai.content or "") if last_ai else "").strip()

    staticmethod
    def get_last_user_len(messages: Sequence[BaseMessage]) -> str:
        last_user_len = next(
            (
                len((m.content or "").strip())
                for m in reversed(messages)
                if getattr(m, "type", "") == "human"
            ),
            0,
        )
        return last_user_len
    
    
    @staticmethod
    def is_sql_tool(name: str) -> bool:
        return Utils.tool_kind(name) == "sql"

    @staticmethod
    def normalize_tool_args(name: str, args: dict[str, Any], customer_id: Optional[str]) -> dict[str, Any]:
        if not (customer_id and AIHelper.is_sql_tool(name)):
            return args

        out = dict(args or {})
        out["customer_id"] = customer_id
        return out
