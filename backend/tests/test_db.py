"""SQLite-PRAGMAs.

Diese Tests pruefen keine Einstellung, sondern eine Voraussetzung: ohne
``foreign_keys=ON`` sind alle Fremdschluessel im Modell reine Dokumentation,
und ohne WAL blockiert jeder Sync-Lauf die Oberflaeche.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.db import build_engine


async def test_fremdschluessel_sind_eingeschaltet(tmp_path: Path) -> None:
    engine = build_engine(tmp_path / "t.db")
    async with engine.connect() as connection:
        assert (await connection.execute(text("PRAGMA foreign_keys"))).scalar() == 1
    await engine.dispose()


async def test_journal_mode_ist_wal(tmp_path: Path) -> None:
    engine = build_engine(tmp_path / "t.db")
    async with engine.connect() as connection:
        assert (await connection.execute(text("PRAGMA journal_mode"))).scalar() == "wal"
    await engine.dispose()


async def test_busy_timeout_ist_gesetzt(tmp_path: Path) -> None:
    engine = build_engine(tmp_path / "t.db")
    async with engine.connect() as connection:
        assert (await connection.execute(text("PRAGMA busy_timeout"))).scalar() == 5000
    await engine.dispose()


async def test_fremdschluessel_werden_wirklich_durchgesetzt(migrated_db: Path) -> None:
    """Der Test, auf den es ankommt: das PRAGMA hat auch Wirkung."""
    from sqlalchemy.exc import IntegrityError

    engine = build_engine(migrated_db)
    async with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            await connection.execute(
                text(
                    "INSERT INTO sde_groups (group_id, category_id, name, published) "
                    "VALUES (1, 424242, 'Waise', 1)"
                )
            )
    await engine.dispose()


async def test_utc_datetime_verweigert_naive_zeitstempel(migrated_db: Path) -> None:
    """Naive Zeitstempel vergleichen sich stillschweigend falsch gegen ESI-Daten."""
    import datetime as dt

    from app.models.base import UtcDateTime

    column = UtcDateTime()
    with pytest.raises(ValueError, match="UTC"):
        naiv = dt.datetime(2026, 9, 1, 12, 0)  # noqa: DTZ001 -- genau darum geht es hier
        column.process_bind_param(naiv, None)

    aware = dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC)
    stored = column.process_bind_param(aware, None)
    assert stored is not None
    assert column.process_result_value(stored, None) == aware
