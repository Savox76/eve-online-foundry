"""Gesundheitscheck.

Der einzige Endpunkt ohne Sitzungsgeheimnis -- die Tauri-Schale muss beim
Start feststellen koennen, ob der Sidecar hochgekommen ist, bevor sie ein
Geheimnis mitschicken kann. Er verraet deshalb nichts ausser: es lebt.
"""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.core.migrate import current_revision
from app.core.paths import database_path
from app.schemas.system import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Laeuft der Sidecar?")
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        database_revision=current_revision(database_path()),
    )
