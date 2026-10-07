from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.schema import schema_is_current
from app.database.session import get_session

router = APIRouter(tags=["operations"])


@router.get("/health", summary="Process health")
async def health() -> dict:
    return {"success": True, "data": {"status": "healthy"}}


@router.get("/ready", summary="Dependency and schema readiness")
async def ready(session: AsyncSession = Depends(get_session)) -> dict:
    try:
        await session.execute(text("SELECT 1"))
        schema_ready = await schema_is_current(session)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Readiness dependencies are unavailable",
        ) from exc
    if not schema_ready:
        raise HTTPException(
            status_code=503, detail="Database schema is not at the required revision"
        )
    return {"success": True, "data": {"status": "ready"}}
