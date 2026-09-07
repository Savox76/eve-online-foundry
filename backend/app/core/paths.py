"""Wo die Anwendung ihre Daten ablegt.

Eine Desktop-Anwendung hat kein ``/var/lib``. Die Pfade folgen den Konventionen
des jeweiligen Systems (platformdirs), damit Sicherungen, Deinstallation und
Rechte funktionieren wie bei jeder anderen installierten Anwendung:

* Windows  ``%LOCALAPPDATA%\\NewEdenFoundry``
* macOS    ``~/Library/Application Support/NewEdenFoundry``
* Linux    ``~/.local/share/NewEdenFoundry``  (bzw. ``$XDG_DATA_HOME``)

``FOUNDRY_DATA_DIR`` sticht das aus -- dafuer ist es da, und die Tests nutzen es.
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "NewEdenFoundry"
APP_AUTHOR = "Savox76"


def data_dir() -> Path:
    """Wurzelverzeichnis fuer Datenbank, Sicherungen und Zwischenspeicher."""
    override = os.environ.get("FOUNDRY_DATA_DIR")
    root = Path(override) if override else Path(user_data_dir(APP_NAME, APP_AUTHOR))
    root.mkdir(parents=True, exist_ok=True)
    return root


def database_path() -> Path:
    """Die eine SQLite-Datei."""
    return data_dir() / "foundry.db"


def backup_dir() -> Path:
    """Sicherungen vor Migrationen. Die letzten zehn bleiben liegen."""
    path = data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sde_cache_dir() -> Path:
    """Heruntergeladene Static-Data-Exporte -- jederzeit wegwerfbar."""
    path = data_dir() / "sde-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def lock_path() -> Path:
    """Sperrdatei fuer die Einzelinstanz."""
    return data_dir() / "foundry.lock"


def session_secret_path() -> Path:
    """Rueckfallebene fuer den Entwicklungsbetrieb ohne Tauri-Schale.

    Im Normalbetrieb erzeugt die Schale das Geheimnis und reicht es per
    Umgebungsvariable durch -- dann wird diese Datei nie geschrieben.
    """
    return data_dir() / "session-secret"
