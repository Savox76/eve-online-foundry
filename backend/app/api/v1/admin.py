"""Betriebszustand.

Kein eigener Tab, sondern hinter dem Nutzermenue (Kapitel 15) -- diese
Ansichten braucht man selten und dann meist im Fehlerfall. Genau dann aber
richtig: Rate-Limit-Verbrauch, Alter des Kompatibilitaetsdatums, welcher
SDE-Stand gilt und was die letzten Sync-Laeufe gemacht haben.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.config import ESI_COMPATIBILITY_DATE
from app.core.db import get_session
from app.core.migrate import current_revision
from app.core.paths import data_dir, database_path, ist_portabel
from app.core.ratelimit import get_budget
from app.esi.compat import GUARANTEED_DAYS, WARN_AFTER_DAYS, check_compatibility_date
from app.models.esi import SyncRun
from app.schemas.system import (
    CompatibilityInfo,
    RateLimitInfo,
    SdeBuildInfo,
    StatusResponse,
    SyncRunInfo,
)
from app.sde.importer import active_build

router = APIRouter(prefix="/admin", tags=["admin"])


def _compatibility_info() -> CompatibilityInfo:
    age = check_compatibility_date(ESI_COMPATIBILITY_DATE)
    if age >= GUARANTEED_DAYS:
        state = "expired"
    elif age >= WARN_AFTER_DAYS:
        state = "warn"
    else:
        state = "ok"
    return CompatibilityInfo(
        date=ESI_COMPATIBILITY_DATE,
        age_days=age,
        guaranteed_days=GUARANTEED_DAYS,
        state=state,
    )


@router.get("/status", response_model=StatusResponse, summary="Betriebszustand")
async def status(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=20, ge=1, le=200),
) -> StatusResponse:
    build = active_build()
    runs = (
        await session.execute(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(limit))
    ).scalars()

    return StatusResponse(
        version=__version__,
        database_revision=current_revision(database_path()),
        database_path=str(database_path()),
        data_dir=str(data_dir()),
        portable=ist_portabel(),
        sde=SdeBuildInfo(**build) if build else None,
        compatibility=_compatibility_info(),
        rate_limit=RateLimitInfo.model_validate(get_budget().snapshot()),
        recent_syncs=[SyncRunInfo.model_validate(run, from_attributes=True) for run in runs],
    )


@router.get("/rate-limit", response_model=RateLimitInfo, summary="ESI-Budget")
async def rate_limit() -> RateLimitInfo:
    """Der Verbrauch je Routengruppe, live.

    Interessant wird das in genau einem Moment: wenn nichts mehr geht und die
    Frage im Raum steht, ob es an CCP liegt oder am eigenen Zeitplan.
    """
    return RateLimitInfo.model_validate(get_budget().snapshot())
