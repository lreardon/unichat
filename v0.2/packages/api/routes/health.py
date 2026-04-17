from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.api.dependencies import get_db_session

router = APIRouter(tags=["health"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/health")
async def health_check(db: DbSession) -> dict[str, str]:
    result = await db.execute(text("SELECT 1"))
    result.scalar_one()
    return {"status": "ok"}
