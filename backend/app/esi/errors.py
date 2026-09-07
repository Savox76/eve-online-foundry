"""Fehlerarten von ESI.

Die Unterscheidung ist keine Kosmetik: ein 403 auf einer Struktur ohne
Docking-Zugriff ist ein **erwarteter Zustand**, kein Fehler. Wer ihn als Fehler
behandelt, laesst den ganzen Asset-Sync an einer einzigen fremden Struktur
haengen (Kapitel 18).
"""

from __future__ import annotations


class EsiError(Exception):
    """Basis fuer alles, was ESI zurueckmeldet."""

    def __init__(self, message: str, *, status_code: int | None = None, route: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.route = route


class EsiForbidden(EsiError):
    """403 -- kein Zugriff.

    Meist eine Struktur ohne Docking-Rechte oder eine Corp-Route ohne die
    passende In-Game-Rolle. Beides gehoert sichtbar gemeldet und mit einem
    Rueckfall angezeigt ("Unbekannte Struktur #1035..."), nicht als leere
    Liste verschwiegen.
    """


class EsiNotFound(EsiError):
    """404 -- gibt es nicht (mehr)."""


class EsiRateLimited(EsiError):
    """429 -- Token-Budget der Routengruppe erschoepft."""

    def __init__(self, message: str, *, retry_after: float, route: str = "") -> None:
        super().__init__(message, status_code=429, route=route)
        self.retry_after = retry_after


class EsiErrorLimited(EsiError):
    """420 -- Fehlerbudget aufgebraucht, alle Routen sind zu."""

    def __init__(self, message: str, *, reset_after: float, route: str = "") -> None:
        super().__init__(message, status_code=420, route=route)
        self.reset_after = reset_after


class EsiServerError(EsiError):
    """5xx -- CCPs Seite. Kostet nichts im Budget und darf wiederholt werden."""


class EsiPaginationError(EsiError):
    """Der Datensatz hat sich mitten im seitenweisen Abruf geaendert.

    Erkennbar daran, dass ``Last-Modified`` nicht ueber alle Seiten identisch
    ist. Die Seiten passen dann nicht zusammen; der Abruf wird verworfen und
    spaeter wiederholt.
    """
