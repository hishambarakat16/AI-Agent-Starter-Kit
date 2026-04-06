import os
from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .routers import authentication, chat, health
from .middleware import TimeoutMiddleware

from pathlib import Path
from app.core.logging_config import configure_logging

configure_logging(
    config_path=Path(__file__).resolve().parent / "core" / "logging.yaml",
    logs_dir=Path("logs/fintech-api"),
)

limiter = Limiter(key_func=get_remote_address)

REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "60"))

app = FastAPI(
    title="LangGraph Agent Starter",
    version="1.0.0",
)

app.add_middleware(TimeoutMiddleware, timeout_seconds=REQUEST_TIMEOUT_SECONDS)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(health.router)
app.include_router(authentication.router)
app.include_router(chat.router)
