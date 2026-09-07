"""PKCE und der ``state``-Parameter.

Als Desktop-Anwendung gilt der native Flow, und der kommt **ganz ohne Client
Secret** aus. CCP sieht das ausdruecklich dafuer vor, dass Anwendungen ohne
ihren Schluessel ausgeliefert werden koennen -- eine installierte Anwendung
kann ohnehin nichts geheim halten (Kapitel 4).

Statt eines Geheimnisses beweist die Anwendung beim Tausch von Code gegen
Token, dass sie dieselbe ist, die den Login angestossen hat: sie schickt den
``code_verifier`` nach, aus dem die zuvor uebermittelte ``code_challenge``
gebildet wurde. Wer den Code unterwegs abfaengt, kann damit nichts anfangen.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass

#: Untergrenze aus RFC 7636. 32 zufaellige Bytes ergeben base64url-kodiert
#: 43 Zeichen -- genau die erlaubte Mindestlaenge, und mehr bringt nichts.
VERIFIER_BYTES = 32


def _b64url(raw: bytes) -> str:
    """Base64-URL **ohne Padding** -- mit ``=`` weist die SSO den Request ab."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def create_verifier() -> str:
    return _b64url(secrets.token_bytes(VERIFIER_BYTES))


def challenge_for(verifier: str) -> str:
    """SHA-256 des Verifiers, base64url, ohne Padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _b64url(digest)


@dataclass(frozen=True, slots=True)
class PkcePair:
    """Ein Login-Versuch.

    ``verifier`` bleibt im Prozess, nur ``challenge`` geht raus. ``state``
    bindet die Antwort des Browsers an genau diesen Versuch -- ein Callback
    mit fremdem ``state`` wird verworfen, sonst koennte jemand einen eigenen
    Code unterschieben.
    """

    verifier: str
    challenge: str
    state: str

    @classmethod
    def create(cls) -> PkcePair:
        verifier = create_verifier()
        return cls(
            verifier=verifier,
            challenge=challenge_for(verifier),
            state=secrets.token_urlsafe(24),
        )

    def matches_state(self, received: str) -> bool:
        """Vergleich in konstanter Zeit."""
        return secrets.compare_digest(self.state, received)
