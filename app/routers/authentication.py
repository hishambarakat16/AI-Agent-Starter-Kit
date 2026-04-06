import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import Hash, token
from app.schemas import TokenResponse
from app.services import get_app_user_by_email
from app.utils import LoggingHelper

logger = logging.getLogger("routers")

router = APIRouter(prefix="/auth", tags=["Authentication"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):

    email = (form_data.username or "").strip()
    user = get_app_user_by_email(email)

    if not user["is_active"]:
        logger.warning("login denied: inactive user email=%s", LoggingHelper._safe_email(email))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive",
        )

    if not Hash.verify(user["password_hash"], form_data.password):
        logger.warning("login failed: invalid credentials email=%s", LoggingHelper._safe_email(email))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    access_token = token.create_access_token({"sub": user["email"]})
    logger.info("login success email=%s", LoggingHelper._safe_email(user["email"]))
    return TokenResponse(access_token=access_token, token_type="bearer")
