"""Alembic-Umgebung.

Zwei Dinge weichen von der Vorlage ab, beide wegen SQLite:

``render_as_batch=True``
    SQLite kann Spalten nicht direkt aendern oder loeschen. Alembic baut die
    Tabelle dafuer neu -- das muss eingeschaltet sein, sonst scheitert die
    erste Migration, die eine Spalte anfasst.

``PRAGMA foreign_keys``
    Waehrend eines Batch-Umbaus muss die Pruefung aus sein, sonst reisst der
    Tabellentausch bestehende Verweise. Danach wieder an.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, event, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.paths import database_path  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.base import UtcDateTime  # noqa: E402

config = context.config

# Zwei Feinheiten, beide notwendig:
#
# ``disable_existing_loggers=False`` -- die Vorgabe von ``fileConfig`` ist
# ``True`` und schaltet damit *jeden* bereits eingerichteten Logger ab. Da die
# Migration beim Anwendungsstart laeuft (Kapitel 18), waere danach das gesamte
# Logging der Anwendung stumm, ohne dass irgendetwas auf einen Fehler hindeutet.
#
# ``configure_logger`` -- wird die Migration aus dem Anwendungscode heraus
# aufgerufen statt ueber die Kommandozeile, ist das Logging bereits
# eingerichtet und soll gar nicht angefasst werden.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Rendert eigene Typen als das, was sie in der DDL wirklich sind.

    Ohne diesen Haken schreibt Alembic ``app.models.base.UtcDateTime()`` in die
    Migration -- und koppelt sie damit an Anwendungscode, der sich aendern
    darf. Eine Migration von heute muss in zwei Jahren noch laufen, auch wenn
    die Klasse laengst anders heisst. Auf DDL-Ebene ist ``UtcDateTime``
    schlicht ein ``DATETIME``; genau das wird geschrieben.
    """
    if type_ == "type" and isinstance(obj, UtcDateTime):
        return "sa.DateTime()"
    return False


def _database_url() -> str:
    """Reihenfolge: -x db=..., Umgebung, sonst der Standardpfad."""
    override = context.get_x_argument(as_dictionary=True).get("db")
    if override:
        return f"sqlite:///{override}"
    if url := os.environ.get("FOUNDRY_DATABASE_URL"):
        return url
    return f"sqlite:///{database_path()}"


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        render_item=_render_item,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool, future=True)

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
            render_item=_render_item,
        )
        with context.begin_transaction():
            context.run_migrations()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
