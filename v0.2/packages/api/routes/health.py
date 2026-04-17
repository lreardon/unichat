from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.api.dependencies import get_db_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db_session)) -> dict:
    result = await db.execute(text("SELECT 1"))
    result.scalar_one()
    return {"status": "ok"}
