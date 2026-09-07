"""Charaktere verbinden und verbunden halten.

Der Ablauf aus Kapitel 4, von vorne bis hinten:

1. PKCE-Paar erzeugen, Callback-Listener oeffnen.
2. Systembrowser mit der Authorize-URL starten (macht die Oberflaeche).
3. Rueckruf entgegennehmen, ``state`` pruefen, Listener sofort schliessen.
4. Code plus ``code_verifier`` gegen Tokens tauschen.
5. Access Token offline gegen den JWKS validieren.
6. Refresh Token in den Schluesselbund legen.

Weil Schritt 2 und 3 zusammen bis zu fuenf Minuten dauern koennen, laeuft das
Ganze als Hintergrundaufgabe: die API gibt sofort die URL zurueck und der
Fortschritt wird abgefragt. Ein Login, der das HTTP-Request blockiert, laeuft
in jedes Timeout.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import secrets
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.esi.callback import CallbackError, CallbackListener
from app.esi.client import EsiClient
from app.esi.errors import EsiError, EsiForbidden
from app.esi.jwks import JwksCache, TokenClaims, TokenValidationError, validate_access_token
from app.esi.pkce import PkcePair
from app.esi.routes import CHARACTER_PUBLIC, CHARACTER_ROLES
from app.esi.scopes import REQUIRED_CORP_ROLE, ScopeTier, scopes_for
from app.esi.sso import (
    REFRESH_MARGIN_SECONDS,
    RefreshTokenRejectedError,
    SsoClient,
    SsoError,
    TokenResponse,
    authorize_url,
)
from app.esi.tokens import TokenStore, get_token_store
from app.models.esi import Character, CharacterRole, CharacterToken

logger = logging.getLogger(__name__)

#: Ab so vielen Fehlversuchen in Folge gilt der Charakter als abgemeldet. Ein
#: einzelner Ausfall des Login-Dienstes soll niemanden aussperren.
MAX_REFRESH_FAILURES = 3

#: Charakter samt dem, was ueber seinen Token bekannt ist.
ConnectedCharacter = tuple[Character, "CharacterToken | None"]

STATUS_OK = "ok"
STATUS_NEEDS_REAUTH = "needs_reauth"


class LoginState(StrEnum):
    WAITING = "waiting"
    DONE = "done"
    FAILED = "failed"


@dataclass
class LoginAttempt:
    """Ein laufender Anmeldeversuch."""

    id: str
    url: str
    state: LoginState = LoginState.WAITING
    character_id: int | None = None
    character_name: str = ""
    error: str | None = None
    started_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))


class CharacterService:
    """Alles, was mit Charakteren und ihren Tokens zu tun hat."""

    def __init__(
        self,
        *,
        token_store: TokenStore | None = None,
        jwks: JwksCache | None = None,
        sso_factory: type[SsoClient] = SsoClient,
    ) -> None:
        self._tokens = token_store or get_token_store()
        self._jwks = jwks or JwksCache()
        self._sso_factory = sso_factory
        self._attempts: dict[str, LoginAttempt] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        #: Access Tokens leben nur im Speicher. Sie halten 20 Minuten -- sie in
        #: die Datenbank zu schreiben brächte nichts und wäre ein Datenleck
        #: mehr.
        self._access: dict[int, tuple[str, dt.datetime]] = {}

    @property
    def token_storage(self) -> str:
        """Wo die Refresh Tokens liegen -- ``keyring`` oder ``encrypted-file``.

        Gehoert in die Oberflaeche: die Rueckfallebene ist schwaecher als der
        Schluesselbund, und niemand soll sie fuer den Normalfall halten.
        """
        return self._tokens.kind

    # -- Anmelden -----------------------------------------------------------
    def start_login(self, tiers: tuple[ScopeTier, ...] = (ScopeTier.BASE,)) -> LoginAttempt:
        """Startet einen Anmeldeversuch und liefert die URL fuer den Systembrowser."""
        settings = get_settings()
        scopes = scopes_for(*tiers)
        pkce = PkcePair.create()

        attempt = LoginAttempt(
            id=secrets.token_urlsafe(12),
            url=authorize_url(scopes, pkce),
        )
        self._attempts[attempt.id] = attempt

        task = asyncio.create_task(self._await_callback(attempt, pkce, settings.sso_callback_port))
        # Referenz halten, sonst kann der Garbage Collector die Aufgabe
        # mitten im Login einsammeln.
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return attempt

    def attempt(self, attempt_id: str) -> LoginAttempt | None:
        return self._attempts.get(attempt_id)

    async def _await_callback(self, attempt: LoginAttempt, pkce: PkcePair, port: int) -> None:
        try:
            async with CallbackListener(port, expected_state=pkce.state) as listener:
                result = await listener.wait()
            claims = await self._exchange_and_store(result.code, pkce.verifier)
        except (CallbackError, SsoError, TokenValidationError) as exc:
            attempt.state = LoginState.FAILED
            attempt.error = str(exc)
            logger.warning("Anmeldung fehlgeschlagen: %s", exc)
            return
        except Exception as exc:
            attempt.state = LoginState.FAILED
            attempt.error = f"Unerwarteter Fehler: {exc}"
            logger.exception("Anmeldung mit unerwartetem Fehler abgebrochen")
            return

        attempt.state = LoginState.DONE
        attempt.character_id = claims.character_id
        attempt.character_name = claims.character_name

    async def _exchange_and_store(self, code: str, verifier: str) -> TokenClaims:
        """Tauscht, prueft, speichert -- und schreibt den Charakter weg.

        Die Hintergrundaufgabe hat keine Sitzung aus einem Request und macht
        sich deshalb eine eigene auf. Damit ist der Login abgeschlossen, sobald
        er abgeschlossen *ist* -- die Oberflaeche muss nichts nachreichen.
        """
        async with self._sso_factory() as sso:
            token = await sso.exchange_code(code, verifier)

        claims = await validate_access_token(token.access_token, jwks=self._jwks)
        self._remember_access(claims.character_id, token)

        # Der Refresh Token wird gespeichert, bevor irgendetwas anderes
        # passiert. Geht danach etwas schief, ist der Charakter trotzdem
        # verbunden und nicht halb.
        self._tokens.save(claims.character_id, token.refresh_token)

        async with get_sessionmaker()() as session:
            await self.upsert_character(session, claims, token)
        return claims

    async def upsert_character(
        self, session: AsyncSession, claims: TokenClaims, token: TokenResponse
    ) -> Character:
        """Legt den Charakter an oder aktualisiert ihn."""
        character = await session.get(Character, claims.character_id)
        now = dt.datetime.now(dt.UTC)

        if character is None:
            character = Character(character_id=claims.character_id, name=claims.character_name)
            session.add(character)
        elif claims.owner_changed(character.owner_hash or None):
            # Der Charakter wurde verkauft. Alles verwerfen, was zum alten
            # Besitzer gehoert -- sonst zeigt Foundry fremde Assets an.
            logger.warning(
                "Der owner-Claim von %s hat sich geaendert -- der Charakter wurde "
                "uebertragen. Bestaende und Rollen werden verworfen.",
                claims.character_name,
            )
            await self._purge_owned_data(session, claims.character_id)

        character.name = claims.character_name
        character.owner_hash = claims.owner
        character.last_seen_at = now
        character.status = STATUS_OK
        character.status_reason = None

        record = await session.get(CharacterToken, claims.character_id)
        if record is None:
            record = CharacterToken(character_id=claims.character_id)
            session.add(record)
        record.scopes = " ".join(claims.scopes)
        record.storage = self._tokens.kind
        record.access_expires_at = token.expires_at
        record.last_refresh_at = now
        record.refresh_failures = 0

        await session.commit()
        return character

    async def _purge_owned_data(self, session: AsyncSession, character_id: int) -> None:
        from app.models.esi import Asset

        await session.execute(
            delete(CharacterRole).where(CharacterRole.character_id == character_id)
        )
        await session.execute(
            delete(Asset).where(Asset.owner_type == "character", Asset.owner_id == character_id)
        )

    # -- Verbunden halten ---------------------------------------------------
    def _remember_access(self, character_id: int, token: TokenResponse) -> None:
        self._access[character_id] = (token.access_token, token.expires_at)

    async def access_token(self, session: AsyncSession, character_id: int) -> str:
        """Ein gueltiges Access Token, notfalls frisch geholt."""
        cached = self._access.get(character_id)
        margin = dt.timedelta(seconds=REFRESH_MARGIN_SECONDS)
        if cached and dt.datetime.now(dt.UTC) + margin < cached[1]:
            return cached[0]
        return await self.refresh(session, character_id)

    async def refresh(self, session: AsyncSession, character_id: int) -> str:
        """Erneuert die Tokens eines Charakters.

        **Der neue Refresh Token wird sofort gespeichert.** CCP tauscht ihn bei
        jedem Refresh aus; wer den alten behaelt, fliegt beim uebernaechsten
        Start raus und sucht den Fehler an der falschen Stelle.
        """
        refresh_token = self._tokens.load(character_id)
        if refresh_token is None:
            await self._mark_needs_reauth(session, character_id, "Kein Refresh Token hinterlegt.")
            raise RefreshTokenRejectedError(
                f"Fuer Charakter {character_id} liegt kein Refresh Token vor."
            )

        try:
            async with self._sso_factory() as sso:
                token = await sso.refresh(refresh_token)
        except RefreshTokenRejectedError as exc:
            await self._mark_needs_reauth(session, character_id, str(exc))
            raise
        except SsoError as exc:
            # Ein Ausfall des Login-Dienstes ist kein Grund, jemanden
            # abzumelden -- erst wiederholtes Scheitern ist einer.
            await self._count_failure(session, character_id, str(exc))
            raise

        self._tokens.save(character_id, token.refresh_token)
        self._remember_access(character_id, token)

        claims = await validate_access_token(token.access_token, jwks=self._jwks)
        record = await session.get(CharacterToken, character_id)
        if record is not None:
            record.scopes = " ".join(claims.scopes)
            record.access_expires_at = token.expires_at
            record.last_refresh_at = dt.datetime.now(dt.UTC)
            record.refresh_failures = 0

        character = await session.get(Character, character_id)
        if character is not None:
            if claims.owner_changed(character.owner_hash or None):
                await self._purge_owned_data(session, character_id)
                await self._mark_needs_reauth(
                    session,
                    character_id,
                    "Der Charakter wurde uebertragen und muss neu autorisiert werden.",
                )
                self._tokens.delete(character_id)
                raise RefreshTokenRejectedError(
                    "Der owner-Claim hat sich geaendert -- der Charakter wurde verkauft."
                )
            character.status = STATUS_OK
            character.status_reason = None
            character.last_seen_at = dt.datetime.now(dt.UTC)

        await session.commit()
        return token.access_token

    async def _mark_needs_reauth(
        self, session: AsyncSession, character_id: int, reason: str
    ) -> None:
        character = await session.get(Character, character_id)
        if character is not None:
            character.status = STATUS_NEEDS_REAUTH
            character.status_reason = reason
            await session.commit()

    async def _count_failure(self, session: AsyncSession, character_id: int, reason: str) -> None:
        record = await session.get(CharacterToken, character_id)
        if record is None:
            return
        record.refresh_failures += 1
        if record.refresh_failures >= MAX_REFRESH_FAILURES:
            await self._mark_needs_reauth(session, character_id, reason)
        await session.commit()

    # -- Verwalten ----------------------------------------------------------
    async def list_characters(
        self, session: AsyncSession
    ) -> list[tuple[Character, CharacterToken | None]]:
        characters = (
            (await session.execute(select(Character).order_by(Character.name))).scalars().all()
        )
        result: list[ConnectedCharacter] = []
        for character in characters:
            record = await session.get(CharacterToken, character.character_id)
            result.append((character, record))
        return result

    async def remove(self, session: AsyncSession, character_id: int) -> bool:
        """Entfernt einen Charakter vollstaendig -- Token inbegriffen."""
        character = await session.get(Character, character_id)
        if character is None:
            return False

        await self._purge_owned_data(session, character_id)
        await session.delete(character)
        await session.commit()

        self._tokens.delete(character_id)
        self._access.pop(character_id, None)
        logger.info("Charakter %d entfernt, Refresh Token geloescht.", character_id)
        return True

    # -- Rollen -------------------------------------------------------------
    async def sync_roles(
        self, session: AsyncSession, character_id: int, *, client: EsiClient
    ) -> tuple[str, ...]:
        """Holt die In-Game-Rollen.

        Sie sagen, welche Corp-Routen der Token ueberhaupt bedienen darf. Fehlt
        die Director-Rolle, sind die Corp-Hangars nicht abrufbar -- und das
        gehoert sichtbar gemeldet, nicht stillschweigend als leere Liste
        angezeigt (Kapitel 4).
        """
        token = await self.access_token(session, character_id)
        try:
            response = await client.request(
                CHARACTER_ROLES, token=token, path_params={"character_id": character_id}
            )
        except EsiForbidden:
            logger.info("Charakter %d darf seine Rollen nicht lesen.", character_id)
            return ()

        if response.unchanged or not isinstance(response.data, dict):
            existing = (
                (
                    await session.execute(
                        select(CharacterRole.role).where(
                            CharacterRole.character_id == character_id,
                            CharacterRole.scope == "roles",
                        )
                    )
                )
                .scalars()
                .all()
            )
            return tuple(existing)

        await session.execute(
            delete(CharacterRole).where(CharacterRole.character_id == character_id)
        )
        now = dt.datetime.now(dt.UTC)
        for scope in ("roles", "roles_at_hq", "roles_at_base", "roles_at_other"):
            for role in response.data.get(scope, []) or []:
                session.add(
                    CharacterRole(
                        character_id=character_id, role=str(role), scope=scope, fetched_at=now
                    )
                )
        await session.commit()
        return tuple(str(role) for role in response.data.get("roles", []) or [])

    async def sync_public(
        self, session: AsyncSession, character_id: int, *, client: EsiClient
    ) -> None:
        """Holt Corp- und Allianzzugehoerigkeit. Oeffentlich, kein Token noetig."""
        try:
            response = await client.request(
                CHARACTER_PUBLIC, path_params={"character_id": character_id}
            )
        except EsiError as exc:
            logger.info("Oeffentliche Daten von %d nicht abrufbar: %s", character_id, exc)
            return
        if response.unchanged or not isinstance(response.data, dict):
            return

        character = await session.get(Character, character_id)
        if character is None:
            return
        character.corporation_id = response.data.get("corporation_id")
        character.alliance_id = response.data.get("alliance_id")
        await session.commit()


def missing_roles_for(granted_scopes: tuple[str, ...], roles: tuple[str, ...]) -> dict[str, str]:
    """Welche erteilten Corp-Scopes ohne die passende Rolle wirkungslos sind.

    Genau der Fall, der sonst als leere Liste durchgeht: der Scope ist da, die
    Rolle fehlt, ESI antwortet mit 403.
    """
    have = set(roles)
    return {
        scope: role
        for scope, role in REQUIRED_CORP_ROLE.items()
        if scope in granted_scopes and role not in have
    }


_service: CharacterService | None = None


def get_character_service() -> CharacterService:
    global _service
    if _service is None:
        _service = CharacterService()
    return _service


def set_character_service(service: CharacterService | None) -> None:
    """Fuer Tests."""
    global _service
    _service = service
