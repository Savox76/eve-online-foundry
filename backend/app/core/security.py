"""Absicherung des Loopback-Servers.

Ein Server auf ``127.0.0.1`` ist fuer *jeden* Prozess auf dem Rechner
erreichbar -- auch fuer eine Webseite im Browser, die per ``fetch`` dorthin
schiesst. Beides wird hier geschlossen (Kapitel 18):

1. **Sitzungsgeheimnis.** Die Tauri-Schale erzeugt es beim Start und reicht es
   dem Sidecar durch; das Fenster schickt es in jedem Request mit. Ein fremder
   Prozess kennt es nicht.
2. **Kein CORS.** Es wird bewusst *keine* CORS-Middleware registriert. Damit
   verweigert der Browser jeder fremden Origin schon den Lesezugriff auf die
   Antwort.

Verglichen wird in konstanter Zeit -- der Aufwand ist ein Einzeiler.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.paths import session_secret_path

logger = logging.getLogger(__name__)

#: Header, in dem das Fenster das Geheimnis mitschickt.
SESSION_HEADER = "X-Foundry-Session"

#: Ohne Geheimnis erreichbar. Bewusst kurz gehalten: der Gesundheitscheck ist
#: das, worauf die Schale beim Start wartet -- und er verraet nichts.
PUBLIC_PATHS = frozenset({"/health", "/health/", "/docs", "/openapi.json", "/redoc"})


def resolve_session_secret() -> str:
    """Liefert das Sitzungsgeheimnis dieses Laufs.

    Reihenfolge: Umgebung (Normalbetrieb, von der Schale gesetzt) vor Datei
    (Entwicklungsbetrieb, damit ``npm run dev`` es lesen kann).
    """
    settings = get_settings()
    if settings.session_secret:
        return settings.session_secret

    path = session_secret_path()
    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing

    generated = secrets.token_urlsafe(32)
    path.write_text(generated, encoding="utf-8")
    # Nur der Besitzer darf lesen. Unter Windows ist das ein No-op, dort
    # schuetzt das Benutzerprofil.
    path.chmod(0o600)
    logger.warning(
        "Kein Sitzungsgeheimnis uebergeben -- eins erzeugt und in %s abgelegt. "
        "Im Normalbetrieb reicht die Tauri-Schale es durch.",
        path,
    )
    return generated


class SessionSecretMiddleware:
    """Weist jeden Request ohne gueltiges Sitzungsgeheimnis ab."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    async def __call__(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        provided = request.headers.get(SESSION_HEADER, "")
        if not secrets.compare_digest(provided, self._secret):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "detail": (
                        "Sitzungsgeheimnis fehlt oder ist falsch. Dieser Server "
                        "beantwortet nur Anfragen des eigenen Anwendungsfensters."
                    )
                },
            )
        return await call_next(request)
