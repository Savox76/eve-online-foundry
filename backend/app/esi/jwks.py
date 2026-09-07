"""Offline-Validierung des Access Tokens.

Das Access Token von EVE SSO ist ein JWT und wird **offline** gegen den
JWKS-Satz geprueft (Kapitel 4). Das ist kein Optimierungsdetail: eine
Anwendung, die bei jedem Request bei CCP nachfragt, ob ein Token echt ist,
wartet unnoetig -- und faellt aus, sobald der Login-Dienst kurz haengt.

Geprueft wird viererlei:

1. **Signatur** gegen den oeffentlichen Schluessel aus dem JWKS.
2. **Issuer** ``login.eveonline.com``. CCP liefert ihn mal mit, mal ohne
   Schema, deshalb sind beide Formen zugelassen.
3. **Audience** enthaelt die eigene Client-ID *und* ``"EVE Online"``. Beides
   zusammen, nicht eines von beiden -- sonst waere ein Token einer fremden
   Anwendung hier gueltig.
4. **exp**, mit einer kleinen Toleranz gegen Uhrenversatz.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import PyJWKSet
from jwt.exceptions import PyJWKSetError

from app.core.config import (
    SSO_EXPECTED_AUDIENCE,
    SSO_ISSUERS,
    SSO_JWKS_URL,
    get_settings,
)
from app.esi.scopes import normalize_scp_claim

logger = logging.getLogger(__name__)

#: Uhren auf Desktops laufen auseinander. Ein paar Sekunden Toleranz sind
#: ueblich; mehr wuerde ein abgelaufenes Token unnoetig lange gelten lassen.
LEEWAY_SECONDS = 30

#: Der Schluesselsatz wechselt selten. Haeufiger als das nachzuladen bringt
#: nichts -- bei einem unbekannten ``kid`` wird ohnehin sofort neu geholt.
JWKS_TTL_SECONDS = 3600.0

SUBJECT_PREFIX = "CHARACTER:EVE:"


class TokenValidationError(Exception):
    """Das Token ist nicht (mehr) gueltig."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """Was im Access Token steht, in brauchbarer Form."""

    character_id: int
    character_name: str
    #: Aendert sich beim Charakter-Transfer. Siehe ``owner_changed``.
    owner: str
    scopes: tuple[str, ...]
    expires_at: dt.datetime
    issued_at: dt.datetime | None
    raw: dict[str, Any]

    def owner_changed(self, previous_owner: str | None) -> bool:
        """Wurde der Charakter seit dem letzten Login verkauft?

        Der ``owner``-Claim aendert sich beim Charakter-Transfer. Wer ihn nicht
        mitspeichert und vergleicht, zeigt nach einem Verkauf fremde Assets an
        (Kapitel 4). Faellt das auf, sind alle Tokens dieses Charakters sofort
        zu verwerfen.
        """
        return previous_owner is not None and previous_owner != self.owner


class JwksCache:
    """Haelt den JWKS-Satz von CCP im Speicher."""

    def __init__(self, url: str = SSO_JWKS_URL, *, ttl: float = JWKS_TTL_SECONDS) -> None:
        self._url = url
        self._ttl = ttl
        self._keys: PyJWKSet | None = None
        self._fetched_at: dt.datetime | None = None

    def _is_fresh(self, now: dt.datetime) -> bool:
        if self._fetched_at is None:
            return False
        return (now - self._fetched_at).total_seconds() < self._ttl

    async def get(self, *, force: bool = False) -> PyJWKSet:
        now = dt.datetime.now(dt.UTC)
        cached = self._keys
        if not force and cached is not None and self._is_fresh(now):
            return cached

        settings = get_settings()
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0), headers={"User-Agent": settings.user_agent}
        ) as client:
            try:
                response = await client.get(self._url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                if self._keys is not None:
                    # Lieber mit einem alten Schluesselsatz weiterarbeiten als
                    # den Nutzer auszusperren, weil der Login-Dienst kurz
                    # haengt. Ein wirklich zurueckgezogener Schluessel faellt
                    # bei der Signaturpruefung ohnehin auf.
                    logger.warning("JWKS nicht erreichbar (%s) -- nutze den letzten Stand.", exc)
                    return self._keys
                raise TokenValidationError(f"JWKS nicht erreichbar: {exc}") from exc

        try:
            self._keys = PyJWKSet.from_dict(response.json())
        except (PyJWKSetError, ValueError, KeyError) as exc:
            # Ein leerer oder unlesbarer Schluesselsatz ist kein brauchbares
            # Ergebnis. Wichtig ist, dass er hier auffaellt statt spaeter als
            # ``AttributeError`` in der Signaturpruefung.
            raise TokenValidationError(f"JWKS von CCP ist unbrauchbar: {exc}") from exc
        self._fetched_at = now
        return self._keys

    async def key_for(self, kid: str | None) -> Any:
        """Schluessel zu einer Key-ID, mit einem Nachladeversuch.

        Ein unbekanntes ``kid`` heisst fast immer: CCP hat rotiert. Genau
        dafuer ist der zweite Versuch da.
        """
        try:
            keys = await self.get()
            return _pick(keys, kid)
        except (KeyError, TokenValidationError):
            logger.info("Key-ID %r nicht im zwischengespeicherten JWKS -- neu holen.", kid)

        keys = await self.get(force=True)
        try:
            return _pick(keys, kid)
        except KeyError as exc:
            raise TokenValidationError(
                f"Der Schluessel {kid!r} steht nicht im JWKS von CCP."
            ) from exc


def _pick(keys: PyJWKSet, kid: str | None) -> Any:
    if kid is not None:
        for key in keys.keys:
            if key.key_id == kid:
                return key
        raise KeyError(kid)
    if len(keys.keys) == 1:
        return keys.keys[0]
    raise KeyError("Token ohne kid, aber mehrere Schluessel im JWKS")


async def validate_access_token(
    token: str, *, jwks: JwksCache, client_id: str | None = None
) -> TokenClaims:
    """Prueft ein Access Token und liefert seine Claims."""
    expected_client_id = client_id or get_settings().esi_client_id
    if not expected_client_id:
        raise TokenValidationError(
            "Keine Client-ID konfiguriert -- ohne sie laesst sich die Audience "
            "nicht pruefen. FOUNDRY_ESI_CLIENT_ID setzen."
        )

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise TokenValidationError(f"Kein lesbares JWT: {exc}") from exc

    key = await jwks.key_for(header.get("kid"))

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=[header.get("alg", "RS256")],
            # Die Audience wird unten selbst geprueft: PyJWT laesst *einen*
            # Treffer genuegen, CCP verlangt aber beide Eintraege.
            options={"verify_aud": False, "require": ["exp", "sub"]},
            leeway=LEEWAY_SECONDS,
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenValidationError("Das Access Token ist abgelaufen.") from exc
    except jwt.PyJWTError as exc:
        raise TokenValidationError(f"Token-Pruefung fehlgeschlagen: {exc}") from exc

    _check_issuer(payload)
    _check_audience(payload, expected_client_id)

    return _claims_from(payload)


def _check_issuer(payload: dict[str, Any]) -> None:
    issuer = str(payload.get("iss", ""))
    if issuer not in SSO_ISSUERS:
        raise TokenValidationError(
            f"Unerwarteter Issuer {issuer!r} -- erwartet wurde login.eveonline.com."
        )


def _check_audience(payload: dict[str, Any], client_id: str) -> None:
    raw = payload.get("aud")
    audience = {str(raw)} if isinstance(raw, str) else {str(item) for item in raw or ()}

    missing = {client_id, SSO_EXPECTED_AUDIENCE} - audience
    if missing:
        raise TokenValidationError(
            f"Audience unvollstaendig: {sorted(missing)} fehlt. Ein Token fuer "
            "eine andere Anwendung ist hier nicht gueltig."
        )


def _claims_from(payload: dict[str, Any]) -> TokenClaims:
    subject = str(payload.get("sub", ""))
    if not subject.startswith(SUBJECT_PREFIX):
        raise TokenValidationError(f"Unerwartetes Subject {subject!r}.")
    try:
        character_id = int(subject.removeprefix(SUBJECT_PREFIX))
    except ValueError as exc:
        raise TokenValidationError(f"Keine Charakter-ID in {subject!r}.") from exc

    return TokenClaims(
        character_id=character_id,
        character_name=str(payload.get("name", "")),
        owner=str(payload.get("owner", "")),
        scopes=normalize_scp_claim(payload.get("scp")),
        expires_at=dt.datetime.fromtimestamp(int(payload["exp"]), tz=dt.UTC),
        issued_at=(
            dt.datetime.fromtimestamp(int(payload["iat"]), tz=dt.UTC) if "iat" in payload else None
        ),
        raw=payload,
    )
