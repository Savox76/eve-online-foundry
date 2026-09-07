"""Migration beim Start -- mit Sicherung davor.

Eine Desktop-Anwendung hat kein Wartungsfenster und niemanden, der vor dem
Update ein Skript laufen laesst. Deshalb migriert Foundry beim Start, und
deshalb gilt die Regel aus Kapitel 18 ohne Ausnahme:

1. **Vor** jeder Migration eine Kopie der Datenbank, benannt nach dem
   abgeloesten Stand. Die letzten zehn bleiben liegen -- beim Zurueckrollen
   weiss man dann sofort, welche Datei zu welchem Stand gehoert.
2. Schlaegt die Migration fehl, **startet die Anwendung gar nicht**. Das ist
   beabsichtigt und besser als halb migriert: ein Werkzeug, das mit einem
   halben Schema rechnet, liefert falsche Zahlen statt einer Fehlermeldung.

Kopiert wird ueber die ``backup``-Schnittstelle von SQLite, nicht mit
``shutil.copy``. Der Unterschied zaehlt bei aktivem WAL: ein Dateikopieren
erwischt den Journalstand nicht zuverlaessig mit und kann eine Sicherung
erzeugen, die sich nicht oeffnen laesst -- was man erst merkt, wenn man sie
braucht.
"""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app import __version__
from app.core.paths import backup_dir, database_path

logger = logging.getLogger(__name__)

#: So viele Sicherungen bleiben liegen.
KEEP_BACKUPS = 10

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class MigrationError(RuntimeError):
    """Die Migration ist fehlgeschlagen. Die Sicherung liegt bereit."""


def alembic_config(db_path: Path) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    config.attributes["configure_logger"] = False
    return config


def current_revision(db_path: Path) -> str | None:
    """Auf welchem Migrationsstand die Datei steht. ``None`` = noch keiner."""
    if not db_path.exists():
        return None
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        connection.close()
    return str(row[0]) if row else None


def backup_database(db_path: Path, *, revision: str | None = None) -> Path | None:
    """Legt eine Sicherung an und liefert ihren Pfad.

    ``None``, wenn es noch nichts zu sichern gibt -- der allererste Start.
    """
    if not db_path.exists():
        return None

    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    label = revision or "unbekannt"
    target = backup_dir() / f"foundry-v{__version__}-{label}-{stamp}.db"

    source = sqlite3.connect(db_path)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    logger.info("Sicherung angelegt: %s", target)
    _prune_backups()
    return target


def _prune_backups() -> None:
    backups = sorted(
        backup_dir().glob("foundry-*.db"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for stale in backups[KEEP_BACKUPS:]:
        try:
            stale.unlink()
            logger.debug("Alte Sicherung entfernt: %s", stale.name)
        except OSError as exc:  # pragma: no cover -- Rechteproblem
            logger.warning("Alte Sicherung %s liess sich nicht entfernen: %s", stale.name, exc)


def upgrade_to_head(db_path: Path | None = None) -> str | None:
    """Bringt die Datenbank auf den aktuellen Stand.

    Liefert die Revision, auf der sie danach steht. Wirft ``MigrationError``,
    wenn etwas schiefgeht -- der Aufrufer bricht dann den Start ab.
    """
    target = db_path or database_path()
    before = current_revision(target)

    config = alembic_config(target)
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(config).get_current_head()

    if before == head:
        logger.info("Datenbank ist auf Stand %s -- keine Migration noetig.", head)
        return head

    backup = backup_database(target, revision=before)
    logger.info("Migriere Datenbank von %s auf %s ...", before or "leer", head)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        hint = (
            f" Die Sicherung des vorherigen Standes liegt unter {backup}."
            if backup
            else " Es gab noch keine Datenbank zu sichern."
        )
        raise MigrationError(
            f"Migration von {before or 'leer'} auf {head} fehlgeschlagen: {exc}.{hint}"
        ) from exc

    after = current_revision(target)
    logger.info("Datenbank steht jetzt auf %s.", after)
    return after
