"""Wo der Refresh Token liegt.

Anders als bei einem Server liegt der Token jetzt auf einem Rechner, auf dem
auch alles andere laeuft. Deshalb: **Schluesselbund des Systems**, mit einer
verschluesselten Datei als Rueckfallebene -- niemals eine Konfigurationsdatei
im Klartext, niemals ein Log (Kapitel 4 und 18).

Und die Regel, an der die meisten scheitern: **CCP tauscht den Refresh Token
bei jedem Refresh aus.** Wer den alten behaelt, fliegt beim uebernaechsten
Start raus und sucht den Fehler an der falschen Stelle. ``save()`` wird
deshalb nach *jedem* Refresh aufgerufen, nicht nur beim ersten Login.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

from app.core.paths import PORTABLE_MARKER, data_dir, reist_mit

logger = logging.getLogger(__name__)

#: Name im Schluesselbund. Taucht so im Anmeldeinformations-Manager auf.
KEYRING_SERVICE = "NewEdenFoundry"


class TokenStore(Protocol):
    """Was der Login-Ablauf von einem Speicher braucht."""

    @property
    def kind(self) -> str: ...

    def load(self, character_id: int) -> str | None: ...

    def save(self, character_id: int, refresh_token: str) -> None: ...

    def delete(self, character_id: int) -> None: ...


class KeyringTokenStore:
    """Der Normalfall: Windows Credential Manager, macOS Keychain, Secret Service."""

    kind = "keyring"

    def load(self, character_id: int) -> str | None:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, str(character_id))

    def save(self, character_id: int, refresh_token: str) -> None:
        import keyring

        keyring.set_password(KEYRING_SERVICE, str(character_id), refresh_token)

    def delete(self, character_id: int) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        # War schon weg? Dann ist der gewuenschte Zustand bereits erreicht.
        with contextlib.suppress(PasswordDeleteError):
            keyring.delete_password(KEYRING_SERVICE, str(character_id))


class EncryptedFileTokenStore:
    """Rueckfallebene fuer Systeme ohne Schluesselbund.

    .. warning::
       Das ist **schwaecher als der Schluesselbund**, und zwar in einem Punkt,
       den man kennen muss: der Schluessel liegt neben den Daten. Wer die
       Datei lesen kann, kann auch den Schluessel lesen. Beide Dateien tragen
       ``0600``, mehr traegt diese Ebene nicht.

       Was sie trotzdem leistet: der Token steht nirgends im Klartext. Er
       landet nicht versehentlich in einem Backup, einem Screenshot, einem
       ``grep`` oder einem Bugreport -- und genau das sind die Wege, auf denen
       so etwas in der Praxis abhandenkommt.
    """

    kind = "encrypted-file"

    def __init__(self, directory: Path | None = None) -> None:
        root = directory or data_dir()
        self._key_path = root / "token-key"
        self._data_path = root / "tokens.enc"

    # -- Schluessel ---------------------------------------------------------
    def _fernet(self) -> Fernet:
        from cryptography.fernet import Fernet

        if self._key_path.exists():
            key = self._key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            self._key_path.write_bytes(key)
            self._key_path.chmod(0o600)
        return Fernet(key)

    # -- Daten --------------------------------------------------------------
    def _read_all(self) -> dict[str, str]:
        if not self._data_path.exists():
            return {}
        from cryptography.fernet import InvalidToken

        fernet = self._fernet()
        try:
            raw = fernet.decrypt(self._data_path.read_bytes())
        except InvalidToken:
            # Schluessel und Daten passen nicht zusammen -- meist ein
            # kopiertes Datenverzeichnis. Alles verwerfen ist hier richtig:
            # ein Refresh Token, den wir nicht entschluesseln koennen, ist
            # wertlos, und der Nutzer muss sich ohnehin neu anmelden.
            logger.error(
                "Token-Datei laesst sich nicht entschluesseln -- sie wird verworfen. "
                "Die Charaktere sind neu zu verbinden."
            )
            self._data_path.unlink(missing_ok=True)
            return {}
        parsed: dict[str, str] = json.loads(raw)
        return parsed

    def _write_all(self, entries: dict[str, str]) -> None:
        fernet = self._fernet()
        payload = fernet.encrypt(json.dumps(entries).encode("utf-8"))

        # Erst daneben schreiben, dann umbenennen: ein Absturz mitten im
        # Schreiben darf nicht alle Tokens auf einmal kosten.
        temporary = self._data_path.with_suffix(".tmp")
        temporary.write_bytes(payload)
        temporary.chmod(0o600)
        os.replace(temporary, self._data_path)

    def load(self, character_id: int) -> str | None:
        return self._read_all().get(str(character_id))

    def save(self, character_id: int, refresh_token: str) -> None:
        entries = self._read_all()
        entries[str(character_id)] = refresh_token
        self._write_all(entries)

    def delete(self, character_id: int) -> None:
        entries = self._read_all()
        if entries.pop(str(character_id), None) is not None:
            self._write_all(entries)


class MemoryTokenStore:
    """Nur fuer Tests. Ueberlebt den Prozess nicht -- absichtlich."""

    kind = "memory"

    def __init__(self) -> None:
        self._entries: dict[int, str] = {}

    def load(self, character_id: int) -> str | None:
        return self._entries.get(character_id)

    def save(self, character_id: int, refresh_token: str) -> None:
        self._entries[character_id] = refresh_token

    def delete(self, character_id: int) -> None:
        self._entries.pop(character_id, None)


def keyring_available() -> bool:
    """Probiert den Schluesselbund aus, statt ihn nur zu befragen.

    ``keyring`` meldet auch dann einen Backend, wenn dahinter kein laufender
    Dienst steht -- unter Linux ohne Desktop-Sitzung ist das der Normalfall.
    Ein echter Schreib-Lese-Loeschzyklus ist die einzige verlaessliche
    Auskunft.
    """
    probe = "__foundry_probe__"
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, probe, "ok")
        value = keyring.get_password(KEYRING_SERVICE, probe)
        keyring.delete_password(KEYRING_SERVICE, probe)
    except Exception as exc:
        logger.info("Kein nutzbarer Schluesselbund (%s).", type(exc).__name__)
        return False
    return value == "ok"


_store: TokenStore | None = None


def get_token_store() -> TokenStore:
    """Der Speicher dieses Laufs -- Schluesselbund, sonst verschluesselte Datei."""
    global _store
    if _store is None:
        if reist_mit():
            _store = EncryptedFileTokenStore()
            logger.info(
                "%s liegt neben der Anwendung -- Refresh Tokens wandern in den Ordner "
                "statt in den Schluesselbund. Sie reisen damit mit und lassen auf "
                "diesem Rechner nichts zurueck; der Schluessel liegt aber neben den "
                "Daten. Wer den Ordner hat, hat die Tokens.",
                PORTABLE_MARKER,
            )
        elif keyring_available():
            _store = KeyringTokenStore()
            logger.info("Refresh Tokens liegen im Schluesselbund des Systems.")
        else:
            _store = EncryptedFileTokenStore()
            logger.warning(
                "Kein Schluesselbund verfuegbar -- Refresh Tokens liegen verschluesselt "
                "im Datenverzeichnis. Das ist die Rueckfallebene, nicht der Normalfall."
            )
    return _store


def set_token_store(store: TokenStore | None) -> None:
    """Setzt den Speicher -- fuer Tests und fuer die Rueckfallebene."""
    global _store
    _store = store
