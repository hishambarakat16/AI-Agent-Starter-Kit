import asyncio
import logging
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("middleware")


class TimeoutMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce request timeout limits.

    Wraps each request in an asyncio timeout to prevent long-running requests
    from consuming resources indefinitely.
    """

    def __init__(self, app, timeout_seconds: float = 60.0):
        super().__init__(app)
        self.timeout_seconds = timeout_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Execute request with timeout enforcement.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            Response from handler or timeout error response
        """
        try:
            # Wrap the request processing in a timeout
            response = await asyncio.wait_for(
                call_next(request),
                timeout=self.timeout_seconds
            )
            return response

        except asyncio.TimeoutError:
            # Log the timeout
            logger.warning(
                "request timeout path=%s method=%s timeout_seconds=%.1f",
                request.url.path,
                request.method,
                self.timeout_seconds,
            )

            # Determine language from Accept-Language header
            accept_language = request.headers.get("lang", "").lower()
            is_arabic = "ar" in accept_language

            if is_arabic:
                message = "عذراً، نواجه مشكلة في الخدمة حالياً. يرجى المحاولة مرة أخرى لاحقاً."
                message_en = "Sorry, we're experiencing an issue with the service. Please try again later."
            else:
                message = "Sorry, we're experiencing an issue with the service. Please try again later."
                message_en = message

            return JSONResponse(
                status_code=504,  # Gateway Timeout
                content={
                    "error": "Request timeout",
                    "message": message,
                    "message_en": message_en,
                    "timeout_seconds": self.timeout_seconds,
                },
                headers={
                    "Retry-After": "60",  # Suggest retry after 60 seconds
                },
            )

        except Exception as e:
            # Catch any other exceptions and log them
            logger.error(
                "unexpected error in timeout middleware path=%s error=%s",
                request.url.path,
                str(e),
                exc_info=True,
            )
            raise
