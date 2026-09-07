"""API-Version 1.

Ein Router je Fachbereich, exakt nach der Struktur aus Kapitel 16. Die
Bereiche, deren Phase noch nicht dran ist, sind leere Router -- registriert,
aber ohne Routen. Das haelt die Struktur vollstaendig, ohne in der
OpenAPI-Ausgabe Funktionen zu behaupten, die es nicht gibt.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    assets,
    auth,
    blueprints,
    fittings,
    health,
    industry,
    market,
    planets,
    projects,
)

#: ``/health`` haengt bewusst NICHT unter ``/api/v1`` -- die Schale fragt es
#: ab, bevor sie irgendetwas ueber die API weiss.
system_router = APIRouter()
system_router.include_router(health.router)

api_router = APIRouter(prefix="/api/v1")
for module in (
    auth,
    assets,
    blueprints,
    industry,
    market,
    projects,
    fittings,
    planets,
    admin,
):
    api_router.include_router(module.router)

__all__ = ["api_router", "system_router"]
