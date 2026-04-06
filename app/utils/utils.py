
import json
import inspect
from uuid import UUID
from fastapi import HTTPException, status
from app.schemas.auth import TokenData
from typing import Optional, AsyncIterator, Any, Iterable
import inspect, time
from functools import wraps
import logging

class AsyncHelper:

    @staticmethod
    async def run_tool(tool_by_name: dict[str, Any], name: str, args: dict, logger: logging.Logger):
        tool = tool_by_name.get(name)
        if not tool:
            logger.warning("unknown tool name=%s", name)
            return {"error": f"Unknown tool: {name}"}

        try:
            tool_name = getattr(tool, "name", name)
            logger.info("tool call name=%s args=%s", tool_name, args)

            if hasattr(tool, "ainvoke"):
                return await tool.ainvoke(args)

            result = tool.invoke(args)
            if inspect.isawaitable(result):
                return await result
            return result

        except Exception as e:
            logger.warning("tool error name=%s error=%s", name, e)
            return {"error": str(e)}

class RouterHelper():
    
    @staticmethod
    def check_email(current_user: TokenData):
        email = (current_user.email or "").strip()
        if not email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing email")

        return email
    
    @staticmethod
    def check_session(session_id, sessions, session_owner, owner_email):
        if session_id not in sessions: 
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        if session_owner.get(session_id) != owner_email: 
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    
    @staticmethod
    async def sse_bytes(tokens: AsyncIterator[str]) -> AsyncIterator[bytes]:
        async for chunk in tokens:
            yield chunk.encode("utf-8")

class LoggingHelper:

    @staticmethod
    def _safe_email(email: str) -> str:
        email = (email or "").strip()
        if "@" not in email:
            return "<missing>"
        local, domain = email.split("@", 1)
        if not local:
            return f"<redacted>@{domain}"
        return f"{local[:2]}***@{domain}"
    
    
    @staticmethod
    def _short_id(value: str) -> str:
        value = (value or "").strip()
        if len(value) <= 8:
            return value or "<missing>"
        return f"{value[:4]}…{value[-4:]}"

    @staticmethod
    def _short(value: Optional[str]) -> str:
        value = (value or "").strip()
        if not value:
            return "<missing>"
        if len(value) <= 10:
            return value
        return f"{value[:4]}…{value[-4:]}"
    
   
    @staticmethod
    def log_tools(preview, logger, tools):
        preview = []
        for t in tools[:5]:
            desc = (getattr(t, "description", "") or "").strip().replace("\n", " ")
            if len(desc) > 80:
                desc = desc[:80] + "…"
            preview.append({"name": t.name, "desc": desc})
        if preview:
            logger.debug("tools preview=%s", Utils._jsonify(preview))

    
    @staticmethod
    def timeit(logger, name: str | None = None, level: str = "info"):
        log = getattr(logger, level, logger.info)

        def deco(fn):

            if inspect.iscoroutinefunction(fn):
                @wraps(fn)
                async def wrapped(*args, **kwargs):
                    t0 = time.perf_counter()
                    try: return await fn(*args, **kwargs)
                    finally: log("%s latency_ms=%.1f", name or fn.__name__, (time.perf_counter() - t0) * 1000.0)

                return wrapped

            @wraps(fn)
            def wrapped(*args, **kwargs):
                t0 = time.perf_counter()
                try: return fn(*args, **kwargs)
                finally: log("%s latency_ms=%.1f", name or fn.__name__, (time.perf_counter() - t0) * 1000.0)

            return wrapped
        return deco


    @staticmethod
    def log_history(logger: logging.Logger, session_id: str, owner_email: str, history: Iterable[Any]) -> None:
        lines: list[str] = []
        for i, msg in enumerate(history):
            role = getattr(msg, "role", "?")
            content = getattr(msg, "content", "")
            lines.append(f"{i:03d} role={role} len={len(content)} content={content}")
        logger.info(
            "CHAT HISTORY session_id=%s owner=%s\n%s",
            session_id, owner_email, "\n".join(lines),
        )


    @staticmethod
    def log_lc_messages(logger: logging.Logger, session_id: str, lc_messages: list[Any]) -> None:
        lines: list[str] = []
        for i, m in enumerate(lc_messages):
            role = getattr(m, "type", None) or m.__class__.__name__
            content = getattr(m, "content", "")
            tool_calls = getattr(m, "tool_calls", None)
            if tool_calls:
                lines.append(f"{i:03d} {role} len={len(content)} tool_calls={tool_calls} content={content}")
            else:
                lines.append(f"{i:03d} {role} len={len(content)} content={content}")
        logger.info(
            "LC MESSAGES session_id=%s\n%s",
            session_id, "\n".join(lines),
        )


class Utils:
    
    
    @staticmethod
    def is_uuid(x) -> bool:
        try: UUID(str(x)); return True
        except Exception: return False
    
    @staticmethod
    def jsonify(obj) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False, default=str)
        except Exception:
            return str(obj)
        
    @staticmethod
    def tool_kind(name: str) -> str:
        if (name or "").startswith("sql_"):
            return "sql"
        if (name or "").startswith("policy_"):
            return "policy"
        return "other"



