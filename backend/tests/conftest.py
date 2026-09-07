"""Gemeinsame Fixtures.

Jeder Test bekommt ein eigenes Datenverzeichnis. Das ist nicht nur Hygiene:
``core/paths`` liest ``FOUNDRY_DATA_DIR`` bei jedem Aufruf, und ohne
Isolierung wuerde ein Test die echte Datenbank des Entwicklers anfassen.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import config as config_module
from app.core import db as db_module
from app.core import ratelimit as ratelimit_module


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Datenverzeichnis je Test, und alle Modul-Caches zurueckgesetzt."""
    monkeypatch.setenv("FOUNDRY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FOUNDRY_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("FOUNDRY_CONTACT_EMAIL", "test@example.invalid")
    config_module.reset_settings_cache()
    ratelimit_module.reset_budget()
    db_module._engine = None
    db_module._sessionmaker = None
    yield tmp_path
    config_module.reset_settings_cache()
    ratelimit_module.reset_budget()
    db_module._engine = None
    db_module._sessionmaker = None


@pytest.fixture
def migrated_db(isolated_data_dir: Path) -> Path:
    """Eine Datenbank auf dem aktuellen Migrationsstand."""
    from app.core.migrate import upgrade_to_head
    from app.core.paths import database_path

    upgrade_to_head()
    return database_path()


@pytest.fixture
def head_revision() -> str:
    """Die aktuelle Kopf-Revision.

    Gegen sie zu pruefen statt gegen eine festgeschriebene Kennung heisst: bei
    jeder neuen Migration bleibt der Test richtig, ohne angefasst zu werden.
    """
    from alembic.script import ScriptDirectory

    from app.core.migrate import alembic_config
    from app.core.paths import database_path

    head = ScriptDirectory.from_config(alembic_config(database_path())).get_current_head()
    assert head is not None
    return head


@pytest.fixture
def demo_sde() -> Path:
    """Die synthetischen Static-Data-Testdaten aus ``demo/sde``."""
    path = Path(__file__).resolve().parents[2] / "demo" / "sde"
    assert path.is_dir(), f"Demo-Daten fehlen unter {path}"
    return path


@pytest.fixture
def client(isolated_data_dir: Path) -> Iterator[TestClient]:
    """Ein Client gegen die vollstaendig gestartete Anwendung."""
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    from app.core.security import SESSION_HEADER

    return {SESSION_HEADER: "test-secret"}
