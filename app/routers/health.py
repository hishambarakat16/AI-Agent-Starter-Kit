import logging
from fastapi import APIRouter, status

logger = logging.getLogger("routers")

router = APIRouter(prefix="/v1", tags=["Health"])


@router.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    # logger.debug("health check")  # keep commented unless you need it
    return {"status": "ok"}
