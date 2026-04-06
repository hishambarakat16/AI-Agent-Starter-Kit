from __future__ import annotations

import logging

from fastapi import HTTPException, status

from app.utils.connect_db import get_conn
from app.utils import LoggingHelper

logger = logging.getLogger("services")


@LoggingHelper.timeit(logger, "identity get_app_user_by_email", level="info")
def get_app_user_by_email(email: str) -> dict:
    email = (email or "").strip()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT email, password_hash, customer_id, is_active
                FROM core.app_users
                WHERE email = %s
                """,
                (email,),
            )
            
            row = cur.fetchone()
            if not row:
                raise HTTPException( status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

            user = { "email": row[0], "password_hash": row[1], "customer_id": str(row[2]), "is_active": bool(row[3])}
            return user
        
    finally:
        conn.close()


def get_customer_id_for_email(email: str) -> str:
    user = get_app_user_by_email(email)
    
    if not user["is_active"]:
        logger.warning("identity inactive email=%s customer_id=%s", LoggingHelper._safe_email(user["email"]), LoggingHelper._short_id(user["customer_id"]),)
        
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive",
        )
    return user["customer_id"]
