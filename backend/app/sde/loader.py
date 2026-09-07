"""Zeilenweiser Zugriff auf einen Static Data Export.

JSON Lines statt YAML, und das aus einem handfesten Grund: der Export ist
gross, JSONL ist zeilenweise streambar und hat damit kein Speicherproblem.
Dieselbe Datenmenge als YAML einzulesen dauert Minuten und braucht Gigabyte
(Kapitel 5).

Zwei Quellen werden unterstuetzt, weil beide gebraucht werden:

* ein ``.zip`` -- so liefert CCP den Export aus
* ein Verzeichnis -- so liegen die synthetischen Testdaten in ``demo/sde/``,
  wo sie lesbar und im Diff nachvollziehbar bleiben sollen
"""

from __future__ import annotations

import json
import logging
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SdeSourceError(RuntimeError):
    """Die Quelle laesst sich nicht lesen."""


class SdeSource:
    """Ein Export, egal ob Archiv oder Verzeichnis."""

    def __init__(self, path: Path) -> None:
        if not path.exists():
            raise SdeSourceError(f"Kein Static Data Export unter {path}")
        self.path = path
        self._zip: zipfile.ZipFile | None = None
        if path.is_file():
            if not zipfile.is_zipfile(path):
                raise SdeSourceError(f"{path} ist kein ZIP-Archiv.")
            self._zip = zipfile.ZipFile(path)

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    def __enter__(self) -> SdeSource:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- Mitglieder ---------------------------------------------------------
    def members(self) -> list[str]:
        """Alle enthaltenen Dateinamen, ohne Verzeichnispfad."""
        if self._zip is not None:
            return [Path(info.filename).name for info in self._zip.infolist() if not info.is_dir()]
        return [child.name for child in self.path.rglob("*") if child.is_file()]

    def find(self, candidates: tuple[str, ...]) -> str | None:
        """Erster Kandidat, der tatsaechlich im Export liegt.

        Kandidatenlisten statt fester Namen, weil CCP die Benennung zwischen
        Export-Formaten schon geaendert hat. Was wirklich gefunden wurde,
        meldet ``importer --report``.
        """
        available = {name.lower(): name for name in self.members()}
        for candidate in candidates:
            hit = available.get(candidate.lower())
            if hit is not None:
                return hit
        return None

    def read_lines(self, member: str) -> Iterator[dict[str, Any]]:
        """Streamt ein JSONL-Mitglied zeilenweise.

        Kaputte Einzelzeilen werden gemeldet und uebersprungen, nicht
        verschluckt -- ein Export mit drei unlesbaren Zeilen soll importierbar
        bleiben, aber nicht unbemerkt.
        """
        broken = 0
        for lineno, raw in enumerate(self._open_lines(member), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                broken += 1
                if broken <= 5:
                    logger.warning("%s Zeile %d ist kein gueltiges JSON.", member, lineno)
                continue
            if isinstance(parsed, dict):
                yield parsed
        if broken:
            logger.warning("%s: %d unlesbare Zeilen uebersprungen.", member, broken)

    def _open_lines(self, member: str) -> Iterator[str]:
        if self._zip is not None:
            target = next(
                (
                    info.filename
                    for info in self._zip.infolist()
                    if Path(info.filename).name == member
                ),
                None,
            )
            if target is None:
                raise SdeSourceError(f"{member} liegt nicht im Archiv {self.path}")
            with self._zip.open(target) as handle:
                for raw in handle:
                    yield raw.decode("utf-8")
            return

        matches = list(self.path.rglob(member))
        if not matches:
            raise SdeSourceError(f"{member} liegt nicht in {self.path}")
        with matches[0].open(encoding="utf-8") as handle:
            yield from handle


def localized(value: Any, *, language: str = "en") -> str:
    """Holt einen Namen aus einem moeglicherweise lokalisierten Feld.

    Der SDE liefert Namen je nach Feld als schlichten String oder als Objekt
    mit Sprachschluesseln (``{"en": "Tritanium", "de": "Tritanium"}``). Beides
    kommt vor, deshalb hier einmal zentral entschieden statt an dreissig
    Stellen erraten.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in (language, "en", "en-us"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        for candidate in value.values():
            if isinstance(candidate, str) and candidate:
                return candidate
    return str(value)


def first_of(row: dict[str, Any], *keys: str) -> Any:
    """Erster vorhandener Schluessel aus einer Kandidatenliste."""
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None
