"""Gemeinsame Basis aller Modelle."""

from __future__ import annotations

import datetime as dt
from typing import Any, ClassVar

from sqlalchemy import DateTime, MetaData, TypeDecorator
from sqlalchemy.orm import DeclarativeBase

#: Benannte Constraints. Ohne diese Konvention erzeugt Alembic unter SQLite
#: anonyme Constraints, die sich spaeter nicht mehr per Migration aendern
#: lassen -- ein Problem, das man erst Monate spaeter bemerkt.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UtcDateTime(TypeDecorator[dt.datetime]):
    """``DateTime``, das UTC erzwingt.

    SQLite speichert Zeitzonen nicht mit. Ohne diesen Typ kommen Zeitstempel
    naiv zurueck und vergleichen sich stillschweigend falsch gegen die
    aware-Zeitstempel aus ESI -- ein Fehler, der beim Sync-Intervall Stunden
    verschiebt, ohne dass etwas kaputt aussieht.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: dt.datetime | None, dialect: object) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Nur aware datetimes speichern -- UTC erwartet.")
        return value.astimezone(dt.UTC).replace(tzinfo=None)

    def process_result_value(
        self, value: dt.datetime | None, dialect: object
    ) -> dt.datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=dt.UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map: ClassVar[dict[Any, Any]] = {dt.datetime: UtcDateTime}


def utcnow() -> dt.datetime:
    """Jetzt, in UTC und aware. ESI rechnet durchgaengig in UTC."""
    return dt.datetime.now(dt.UTC)
