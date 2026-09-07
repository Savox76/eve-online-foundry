"""ETag- und Expires-Speicher.

Caching ist bei ESI Pflicht, nicht Optimierung: CCP kuendigt Sperren fuer
Anwendungen an, die es umgehen (Kapitel 6). Der Speicher haelt zwei Dinge je
Abrufschluessel:

``expires_at``
    Vor Ablauf gibt es keine neuen Daten. Ein Request davor ist reine
    Verschwendung -- der Client stellt ihn gar nicht erst.

``etag``
    Wird als ``If-None-Match`` zurueckgeschickt. Antwort ``304`` heisst
    unveraendert: kein Traffic und nur ein Token statt zwei.

``Protocol`` statt Basisklasse, damit die Tests mit einer Variante im
Arbeitsspeicher auskommen und keine Datenbank brauchen.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CacheEntry:
    etag: str | None
    expires_at: dt.datetime | None

    def is_fresh(self, *, now: dt.datetime | None = None) -> bool:
        """Noch gueltig? Dann ist jeder Abruf ueberfluessig."""
        if self.expires_at is None:
            return False
        return (now or dt.datetime.now(dt.UTC)) < self.expires_at


class EtagStore(Protocol):
    """Was der Client von einem Cache-Speicher braucht."""

    async def get(self, key: str) -> CacheEntry | None: ...

    async def set(self, key: str, entry: CacheEntry) -> None: ...


class InMemoryEtagStore:
    """Fuer Tests und fuer Laeufe, die nichts behalten sollen."""

    def __init__(self) -> None:
        self._entries: dict[str, CacheEntry] = {}

    async def get(self, key: str) -> CacheEntry | None:
        return self._entries.get(key)

    async def set(self, key: str, entry: CacheEntry) -> None:
        self._entries[key] = entry

    def clear(self) -> None:
        self._entries.clear()


def parse_http_date(value: str | None) -> dt.datetime | None:
    """Liest einen HTTP-Zeitstempel (RFC 7231) als aware datetime in UTC."""
    if not value:
        return None
    from email.utils import parsedate_to_datetime

    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:  # pragma: no cover -- ESI liefert immer GMT
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)
