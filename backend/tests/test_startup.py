"""Start der Anwendung: Sicherung, Migration, Einzelinstanz.

Die drei Zusicherungen aus Kapitel 18, die zusammen verhindern, dass ein
Update Anwendung und Daten zugleich mitnimmt.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.core.instance import AlreadyRunningError, InstanceLock
from app.core.migrate import (
    KEEP_BACKUPS,
    MigrationError,
    backup_database,
    current_revision,
    upgrade_to_head,
)
from app.core.paths import backup_dir, database_path


# -- Migration ---------------------------------------------------------------
def test_erste_migration_legt_die_datenbank_an(isolated_data_dir: Path, head_revision: str) -> None:
    assert current_revision(database_path()) is None
    assert upgrade_to_head() == head_revision
    assert database_path().exists()


def test_zweiter_lauf_migriert_nicht_erneut(isolated_data_dir: Path) -> None:
    """Der Normalfall bei jedem Start: nichts zu tun, also auch keine Sicherung."""
    upgrade_to_head()
    vorhandene = len(list(backup_dir().glob("foundry-*.db")))
    upgrade_to_head()
    assert len(list(backup_dir().glob("foundry-*.db"))) == vorhandene


def test_erster_start_sichert_nichts(isolated_data_dir: Path) -> None:
    """Es gibt noch nichts zu sichern -- und das ist kein Fehlerfall."""
    assert backup_database(database_path()) is None


def test_sicherung_ist_eine_oeffenbare_datenbank(migrated_db: Path) -> None:
    """Der eigentliche Punkt: eine Sicherung, die man nicht oeffnen kann, ist keine.

    Deshalb die ``backup``-Schnittstelle von SQLite statt ``shutil.copy`` --
    bei aktivem WAL erwischt ein Dateikopieren den Journalstand nicht
    zuverlaessig mit.
    """
    ziel = backup_database(migrated_db, revision="0001_fundament")
    assert ziel is not None
    assert ziel.exists()

    connection = sqlite3.connect(ziel)
    try:
        tabellen = {
            name
            for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        connection.close()
    assert "sde_types" in tabellen
    assert "alembic_version" in tabellen


def test_sicherung_traegt_den_abgeloesten_stand_im_namen(migrated_db: Path) -> None:
    """Beim Zurueckrollen weiss man dann sofort, welche Datei wozu gehoert."""
    ziel = backup_database(migrated_db, revision="0001_fundament")
    assert ziel is not None
    assert "0001_fundament" in ziel.name
    assert ziel.name.startswith("foundry-v")


def test_es_bleiben_hoechstens_zehn_sicherungen(migrated_db: Path) -> None:
    for index in range(KEEP_BACKUPS + 5):
        backup_database(migrated_db, revision=f"rev{index:03d}")
    assert len(list(backup_dir().glob("foundry-*.db"))) == KEEP_BACKUPS


def test_fehlgeschlagene_migration_nennt_die_sicherung(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Schlaegt die Migration fehl, startet die Anwendung nicht -- mit Hinweis wohin."""
    from alembic import command
    from app.core import migrate as migrate_module

    def explodiert(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Spalte fehlt")

    monkeypatch.setattr(command, "upgrade", explodiert)
    monkeypatch.setattr(
        migrate_module, "current_revision", lambda _path: "0000_vorher", raising=True
    )

    with pytest.raises(MigrationError) as exc:
        upgrade_to_head()

    meldung = str(exc.value)
    assert "Spalte fehlt" in meldung
    assert "Sicherung" in meldung
    assert "backups" in meldung


# -- Einzelinstanz -----------------------------------------------------------
def test_zweite_instanz_wird_abgewiesen(isolated_data_dir: Path) -> None:
    """Zwei Prozesse auf einer SQLite-Datei sind ein Fehler, kein Wartezustand."""
    with InstanceLock(), pytest.raises(AlreadyRunningError, match="laeuft bereits"):
        InstanceLock().acquire()


def test_sperre_wird_wieder_frei(isolated_data_dir: Path) -> None:
    with InstanceLock():
        pass
    with InstanceLock():
        pass  # kein Fehler -- die Sperre war wirklich frei


def test_sperre_haelt_die_pid_fest(isolated_data_dir: Path) -> None:
    import os

    from app.core.paths import lock_path

    with InstanceLock():
        assert lock_path().read_text(encoding="utf-8").strip() == str(os.getpid())
