"""Der Sidecar.

Startreihenfolge, und jeder Schritt ist eine Bedingung fuer den naechsten:

1. **Kompatibilitaetsdatum pruefen.** Ein Zukunftsdatum wuerde ESI ablehnen --
   das hier zu merken kostet Millisekunden, mitten im Sync kostet es eine
   Fehlersuche.
2. **Einzelinstanz sichern.** Zwei Prozesse auf einer SQLite-Datei sind ein
   Fehler, kein Wartezustand.
3. **Migrieren, mit Sicherung davor.** Schlaegt das fehl, startet die
   Anwendung gar nicht -- beabsichtigt und besser als halb migriert.
4. **Zeitplaene starten.**

Erst danach antwortet ``/health`` mit ``ok``, und erst darauf wartet die
Tauri-Schale, bevor sie das Fenster zeigt.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import AsyncIterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.api.v1 import api_router, system_router
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.instance import AlreadyRunningError, InstanceLock
from app.core.migrate import MigrationError, upgrade_to_head
from app.core.security import SessionSecretMiddleware, resolve_session_secret
from app.esi.compat import CompatibilityDateError, check_compatibility_date
from app.esi.errors import EsiError, EsiErrorLimited, EsiForbidden, EsiRateLimited
from app.workers.scheduler import get_scheduler, reset_scheduler

logger = logging.getLogger(__name__)


class StartupError(RuntimeError):
    """Der Start ist gescheitert. Die Schale zeigt die Meldung an."""


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    check_compatibility_date()

    lock = InstanceLock()
    lock.acquire()

    try:
        upgrade_to_head()
    except MigrationError:
        lock.release()
        raise

    scheduler = get_scheduler()
    scheduler.start()
    logger.info(
        "New Eden Foundry %s bereit auf http://%s:%d", __version__, settings.host, settings.port
    )

    try:
        yield
    finally:
        reset_scheduler()
        await dispose_engine()
        lock.release()
        logger.info("Sidecar beendet.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="New Eden Foundry",
        version=__version__,
        summary="Backend-Sidecar der Desktop-Anwendung.",
        description=(
            "Laeuft ausschliesslich auf der Loopback-Adresse und beantwortet nur "
            "Anfragen des eigenen Anwendungsfensters."
        ),
        lifespan=lifespan,
        # Bewusst KEINE CORS-Middleware: der Browser verweigert damit jeder
        # fremden Origin den Lesezugriff auf die Antworten (Kapitel 18).
    )

    app.middleware("http")(SessionSecretMiddleware(resolve_session_secret()))

    app.include_router(system_router)
    app.include_router(api_router)

    _register_exception_handlers(app)
    return app


def _register_exception_handlers(app: FastAPI) -> None:
    """ESI-Fehler als saubere Antworten, nicht als 500.

    Besonders 403: eine Struktur ohne Docking-Zugriff oder eine fehlende
    In-Game-Rolle ist ein *erwarteter* Zustand. Er gehoert sichtbar gemeldet,
    damit das Frontend "Unbekannte Struktur #..." anzeigen kann, statt eine
    leere Liste als Wahrheit auszugeben (Kapitel 18).
    """

    @app.exception_handler(EsiForbidden)
    async def _forbidden(_request: Request, exc: EsiForbidden) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"detail": str(exc), "route": exc.route, "kind": "esi_forbidden"},
        )

    @app.exception_handler(EsiRateLimited)
    async def _rate_limited(_request: Request, exc: EsiRateLimited) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"detail": str(exc), "route": exc.route, "retry_after": exc.retry_after},
            headers={"Retry-After": str(int(exc.retry_after))},
        )

    @app.exception_handler(EsiErrorLimited)
    async def _error_limited(_request: Request, exc: EsiErrorLimited) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": str(exc),
                "route": exc.route,
                "retry_after": exc.reset_after,
                "kind": "esi_error_limit",
            },
            headers={"Retry-After": str(int(exc.reset_after))},
        )

    @app.exception_handler(EsiError)
    async def _generic(_request: Request, exc: EsiError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"detail": str(exc), "route": exc.route, "upstream_status": exc.status_code},
        )


def run() -> int:
    """Einstiegspunkt der gebuendelten Binaerdatei."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    try:
        uvicorn.run(
            create_app(),
            host=settings.host,
            port=settings.port,
            log_config=None,
            access_log=False,
        )
    except AlreadyRunningError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    except (MigrationError, CompatibilityDateError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
