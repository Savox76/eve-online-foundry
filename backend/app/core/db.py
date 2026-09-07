"""Datenbankzugriff.

SQLite braucht drei PRAGMAs, die nicht Feinschliff sind, sondern die
Voraussetzung dafuer, dass die Anwendung korrekt laeuft (Kapitel 3):

``foreign_keys=ON``
    Fremdschluessel sind in SQLite standardmaessig **aus**. Ohne dieses PRAGMA
    sind alle ``ForeignKey``-Angaben in den Modellen reine Dokumentation.

``journal_mode=WAL``
    Damit der Sync schreiben kann, waehrend die Oberflaeche liest. Ohne WAL
    blockiert jeder Sync-Lauf die gesamte Oberflaeche.

``busy_timeout``
    Zweite Sicherung gegen zwei Prozesse auf derselben Datei (Kapitel 18).
    Die erste ist die Instanzsperre in ``core/instance.py``.

Die PRAGMAs haengen an ``connect``, nicht an einer Startroutine: eine
Verbindung, die sie nicht bekommen hat, gibt es damit gar nicht erst.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.paths import database_path

#: Fuenf Sekunden. Laenger zu warten hilft nicht -- wenn eine zweite Instanz
#: laeuft, ist das ein Fehler, den man sehen soll, kein Wartezustand.
BUSY_TIMEOUT_MS = 5_000

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _apply_pragmas(dbapi_connection: Any, _record: Any) -> None:
    """Wird fuer jede neue Verbindung aufgerufen.

    Hier steht bewusst **kein** ``isinstance(..., sqlite3.Connection)``-Waechter.
    Der liegt nahe und ist falsch: unter ``aiosqlite`` reicht SQLAlchemy einen
    ``AsyncAdapt_aiosqlite_connection`` durch, nicht die rohe
    ``sqlite3.Connection``. Ein solcher Waechter greift also immer, ueberspringt
    alle PRAGMAs -- und zwar lautlos. Die Datenbank laeuft dann ohne
    Fremdschluessel und ohne WAL weiter, was man erst bemerkt, wenn Daten
    inkonsistent sind. ``tests/test_db.py`` prueft deshalb die PRAGMAs nach,
    statt sich auf das Registrieren des Hooks zu verlassen.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        # Guter Kompromiss aus Sicherheit und Tempo, sobald WAL aktiv ist.
        cursor.execute("PRAGMA synchronous=NORMAL")
        # Der SDE-Import schreibt sehr viele Zeilen; 64 MB Cache sparen dabei
        # spuerbar Zeit und kosten auf einem Desktop nichts.
        cursor.execute("PRAGMA cache_size=-64000")
    finally:
        cursor.close()


def build_engine(db_path: Path | None = None, *, echo: bool = False) -> AsyncEngine:
    """Baut eine Engine mit den PRAGMAs aus dem Modulkopf."""
    path = db_path or database_path()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        echo=echo,
        future=True,
        # SQLite mag keine grossen Pools; eine Desktop-Anwendung braucht sie nicht.
        pool_pre_ping=True,
    )
    event.listen(engine.sync_engine, "connect", _apply_pragmas)
    return engine


def get_engine() -> AsyncEngine:
    """Die eine Engine des Prozesses."""
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI-Abhaengigkeit: eine Sitzung pro Request."""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    """Beim Herunterfahren -- gibt die WAL-Dateien sauber frei."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
