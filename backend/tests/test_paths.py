"""Wo die Daten landen -- portabel neben der Anwendung oder im System.

Die Entscheidung faellt an genau einer Stelle, und sie faellt falsch herum,
wenn man sie nicht festnagelt: schreibt die Anwendung neben sich, obwohl sie
installiert ist, scheitert sie unter ``C:\\Program Files``; schreibt sie ins
System, obwohl sie portabel liegt, bleibt beim Loeschen des Ordners etwas
zurueck.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from app.core import paths


@pytest.fixture(autouse=True)
def ohne_gemerkte_entscheidung(monkeypatch: pytest.MonkeyPatch) -> None:
    """Die Entscheidung wird je Prozess gemerkt -- fuer Tests zuruecksetzen."""
    monkeypatch.delenv("FOUNDRY_DATA_DIR", raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    paths._portabler_datenordner.cache_clear()
    yield
    paths._portabler_datenordner.cache_clear()


def test_gebuendelt_und_beschreibbar_landet_neben_der_anwendung(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    programm = tmp_path / "New Eden Foundry"
    programm.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(programm / "foundry-backend"))

    assert paths.data_dir() == programm / "data"
    assert paths.ist_portabel() is True
    assert paths.database_path() == programm / "data" / "foundry.db"


def test_nicht_beschreibbar_faellt_auf_das_system_zurueck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Der Installationsfall: /usr/bin und C:\\Program Files gehoeren nicht uns."""
    programm = tmp_path / "programme"
    programm.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(programm / "foundry-backend"))

    system = tmp_path / "systemablage"
    monkeypatch.setattr(paths, "user_data_dir", lambda *a, **k: str(system))
    monkeypatch.setattr(paths, "_ist_beschreibbar", lambda _ordner: False)

    assert paths.data_dir() == system
    assert paths.ist_portabel() is False


def test_entwicklungsbetrieb_schreibt_nicht_neben_den_python_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ohne Buendelung gibt es keinen Programmordner -- sonst laege alles neben python."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    system = tmp_path / "systemablage"
    monkeypatch.setattr(paths, "user_data_dir", lambda *a, **k: str(system))

    assert paths._programm_verzeichnis() is None
    assert paths.data_dir() == system
    assert paths.ist_portabel() is False


def test_appimage_nimmt_den_ordner_der_datei_nicht_den_mountpunkt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein AppImage haengt sich schreibgeschuetzt unter /tmp ein.

    Wer dort sys.executable auswertet, landet in einem Nur-Lese-Verzeichnis,
    das beim naechsten Start ohnehin anders heisst.
    """
    ablage = tmp_path / "usb-stick"
    ablage.mkdir()
    mountpunkt = tmp_path / "tmp" / ".mount_abc123" / "usr" / "bin"
    mountpunkt.mkdir(parents=True)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(mountpunkt / "foundry-backend"))
    monkeypatch.setenv("APPIMAGE", str(ablage / "New-Eden-Foundry.AppImage"))

    assert paths.data_dir() == ablage / "data"


def test_umgebungsvariable_sticht_alles_aus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    programm = tmp_path / "programm"
    programm.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(programm / "foundry-backend"))
    monkeypatch.setenv("FOUNDRY_DATA_DIR", str(tmp_path / "woanders"))

    assert paths.data_dir() == tmp_path / "woanders"
    assert paths.ist_portabel() is False, "explizit gesetzt ist nicht portabel"


def test_schreibprobe_erkennt_einen_unbrauchbaren_ordner(tmp_path: Path) -> None:
    """Nicht die Rechte auswerten, sondern schreiben.

    Der Weg ueber ``os.access`` liegt unter Windows regelmaessig daneben. Als
    Gegenprobe dient hier eine Datei, wo ein Ordner sein muesste -- das
    scheitert unabhaengig von Benutzer und System. Ein bloss
    schreibgeschuetzter Ordner taugt dafuer nicht: als root laesst er sich
    trotzdem beschreiben, und der Test waere je nach Umgebung gruen oder rot.
    """
    datei = tmp_path / "keine-ablage"
    datei.write_text("Ich bin eine Datei.", encoding="utf-8")

    assert paths._ist_beschreibbar(datei / "data") is False
    assert paths._ist_beschreibbar(tmp_path / "frei") is True


@pytest.mark.skipif(os.geteuid() == 0, reason="root schreibt auch in einen 0500-Ordner")
def test_schreibprobe_erkennt_fehlende_rechte(tmp_path: Path) -> None:
    """Der eigentliche Anwendungsfall: Program Files und /usr/bin."""
    gesperrt = tmp_path / "gesperrt"
    gesperrt.mkdir()
    gesperrt.chmod(0o500)
    try:
        assert paths._ist_beschreibbar(gesperrt / "data") is False
    finally:
        gesperrt.chmod(0o700)


def test_schreibprobe_laesst_nichts_liegen(tmp_path: Path) -> None:
    ordner = tmp_path / "sauber"
    assert paths._ist_beschreibbar(ordner) is True
    assert list(ordner.iterdir()) == []
