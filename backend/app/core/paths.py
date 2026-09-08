"""Wo die Anwendung ihre Daten ablegt.

**Portabel zuerst.** Liegt die Anwendung in einem Ordner, in den sie schreiben
darf, landet alles daneben in ``<Programmordner>/data`` -- Datenbank,
Sicherungen, Zwischenspeicher. Den Ordner kopieren heisst dann: alles
mitkopieren; den Ordner loeschen heisst: nichts bleibt zurueck. Das ist der
Normalfall, denn ausgeliefert wird als portables Paket.

Es gibt zwei Faelle, in denen das nicht geht, und fuer die faellt die
Anwendung auf die Konventionen des Systems zurueck (``platformdirs``):

* Die Anwendung wurde **installiert** -- unter ``C:\\Program Files`` oder
  ``/usr/bin`` darf ein normaler Benutzer nicht schreiben, und das ist auch
  richtig so.
* Der **Entwicklungsbetrieb**, in dem das Backend als Python-Modul laeuft und
  es gar keinen Programmordner gibt.

Dann gilt:

* Windows  ``%LOCALAPPDATA%\\NewEdenFoundry``
* macOS    ``~/Library/Application Support/NewEdenFoundry``
* Linux    ``~/.local/share/NewEdenFoundry``  (bzw. ``$XDG_DATA_HOME``)

``FOUNDRY_DATA_DIR`` sticht beides aus -- dafuer ist es da, und die Tests
nutzen es.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "NewEdenFoundry"
APP_AUTHOR = "Savox76"

#: Wie der Datenordner neben der Anwendung heisst. Bewusst englisch: er ist
#: sichtbar, und die Oberflaeche laesst sich zwischen Deutsch und Englisch
#: umschalten -- der Ordnername soll dabei nicht wandern.
DATA_DIR_NAME = "data"


def _programm_verzeichnis() -> Path | None:
    """Der Ordner, den der Benutzer als *die Anwendung* wahrnimmt.

    ``None`` im Entwicklungsbetrieb, wo das Backend als Python-Modul laeuft.
    """
    # Ein AppImage haengt sich schreibgeschuetzt unter /tmp ein -- sys.executable
    # zeigt dorthin und waere unbrauchbar. $APPIMAGE ist der Pfad der Datei
    # selbst, und deren Ordner ist das, was der Benutzer vor sich sieht.
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return Path(appimage).resolve().parent

    # Von PyInstaller gebuendelt: der Sidecar liegt neben der Schale.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return None


def _ist_beschreibbar(ordner: Path) -> bool:
    """Wirklich schreiben statt Rechte auswerten.

    ``os.access`` liegt unter Windows regelmaessig daneben, und auf einem
    schreibgeschuetzten Datentraeger oder unter ``C:\\Program Files`` haengt
    genau daran die Entscheidung.
    """
    probe = ordner / ".schreibprobe"
    try:
        ordner.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


@lru_cache(maxsize=1)
def _portabler_datenordner() -> Path | None:
    """Der Datenordner neben der Anwendung -- oder ``None``, wenn es nicht geht.

    Einmal je Prozess entschieden: die Schreibprobe kostet zwar wenig, aber
    ``data_dir()`` wird oft genug aufgerufen, dass es sich nicht lohnt.
    """
    neben = _programm_verzeichnis()
    if neben is None:
        return None
    kandidat = neben / DATA_DIR_NAME
    return kandidat if _ist_beschreibbar(kandidat) else None


def data_dir() -> Path:
    """Wurzelverzeichnis fuer Datenbank, Sicherungen und Zwischenspeicher."""
    override = os.environ.get("FOUNDRY_DATA_DIR")
    if override:
        root = Path(override)
    else:
        root = _portabler_datenordner() or Path(user_data_dir(APP_NAME, APP_AUTHOR))
    root.mkdir(parents=True, exist_ok=True)
    return root


def ist_portabel() -> bool:
    """Ob die Daten neben der Anwendung liegen. Fuer die Betriebszustandsansicht."""
    return os.environ.get("FOUNDRY_DATA_DIR") is None and _portabler_datenordner() is not None


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
