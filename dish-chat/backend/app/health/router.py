from fastapi import APIRouter

from .schemas import Health

router = APIRouter()

@router.get("/health", tags=["health"])
async def health_check() -> Health:
    return Health()