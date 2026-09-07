"""Charaktere verbinden und verbunden halten.

Der Login laesst sich gegen CCP nicht fahren, aber der ganze Ablauf dahinter
schon: Rueckruf annehmen, Code tauschen, Token pruefen, speichern -- und vor
allem das, was danach kommt und im Alltag schiefgeht: Rotation, verkaufte
Charaktere, ein Login-Dienst, der kurz haengt.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import SSO_JWKS_URL, SSO_TOKEN_URL
from app.core.db import get_sessionmaker
from app.esi.jwks import JwksCache
from app.esi.sso import RefreshTokenRejectedError, SsoError
from app.esi.tokens import MemoryTokenStore
from app.models.esi import Asset, Character, CharacterToken
from app.services.characters import (
    MAX_REFRESH_FAILURES,
    STATUS_NEEDS_REAUTH,
    STATUS_OK,
    CharacterService,
    missing_roles_for,
)
from tests import factories
from tests.test_callback import freier_port


@pytest.fixture
def store() -> MemoryTokenStore:
    return MemoryTokenStore()


@pytest.fixture
def service(store: MemoryTokenStore, monkeypatch: pytest.MonkeyPatch) -> CharacterService:
    monkeypatch.setenv("FOUNDRY_ESI_CLIENT_ID", factories.CLIENT_ID)
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    return CharacterService(token_store=store, jwks=JwksCache())


def _mock_sso(refresh: str = "refresh-eins", access: str | None = None) -> respx.Route:
    """Legt JWKS und Token-Endpunkt fest und liefert die Token-Route zurueck.

    Der Rueckruf des Browsers geht an den eigenen Listener auf der
    Loopback-Adresse. Der muss durchgelassen werden, sonst faengt respx den
    Test an der Stelle ab, an der er gerade den Browser nachspielt.
    """
    respx.route(host="127.0.0.1").pass_through()
    respx.get(SSO_JWKS_URL).mock(return_value=httpx.Response(200, json=factories.jwks_document()))
    return respx.post(SSO_TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json=factories.token_response(access=access, refresh=refresh)
        )
    )


async def _durchlaufen(service: CharacterService, port: int, *, state_ok: bool = True) -> None:
    """Startet einen Login und spielt den Rueckruf des Browsers nach."""
    attempt = service.start_login()
    await asyncio.sleep(0.05)  # Listener hochkommen lassen

    from urllib.parse import parse_qs, urlsplit

    state = parse_qs(urlsplit(attempt.url).query)["state"][0]
    async with httpx.AsyncClient(timeout=5.0) as client:
        await client.get(
            f"http://127.0.0.1:{port}/callback",
            params={"code": "der-code", "state": state if state_ok else "falsch"},
        )
    for _ in range(60):
        if attempt.state != "waiting":
            break
        await asyncio.sleep(0.05)
    service._last_attempt = attempt  # type: ignore[attr-defined]


# -- Anmelden ----------------------------------------------------------------
@respx.mock
async def test_login_verbindet_den_charakter(
    service: CharacterService,
    store: MemoryTokenStore,
    migrated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = freier_port()
    monkeypatch.setenv("FOUNDRY_SSO_CALLBACK_PORT", str(port))
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    _mock_sso()

    await _durchlaufen(service, port)

    attempt = service._last_attempt  # type: ignore[attr-defined]
    assert attempt.state == "done", attempt.error
    assert attempt.character_id == factories.CHARACTER_ID

    # Der Refresh Token liegt im Speicher, nicht in der Datenbank.
    assert store.load(factories.CHARACTER_ID) == "refresh-eins"

    async with get_sessionmaker()() as session:
        character = await session.get(Character, factories.CHARACTER_ID)
        assert character is not None
        assert character.name == factories.CHARACTER_NAME
        assert character.owner_hash == factories.OWNER_HASH
        assert character.status == STATUS_OK

        token = await session.get(CharacterToken, factories.CHARACTER_ID)
        assert token is not None
        assert "esi-assets.read_assets.v1" in token.scope_list()
        assert token.storage == "memory"


@respx.mock
async def test_login_mit_falschem_state_scheitert(
    service: CharacterService,
    store: MemoryTokenStore,
    migrated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = freier_port()
    monkeypatch.setenv("FOUNDRY_SSO_CALLBACK_PORT", str(port))
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    _mock_sso()

    await _durchlaufen(service, port, state_ok=False)

    attempt = service._last_attempt  # type: ignore[attr-defined]
    assert attempt.state == "failed"
    assert "State" in (attempt.error or "")
    assert store.load(factories.CHARACTER_ID) is None


# -- Verbunden bleiben -------------------------------------------------------
async def _verbinde(
    session: AsyncSession, service: CharacterService, store: MemoryTokenStore
) -> None:
    """Legt einen verbundenen Charakter an, ohne den Browser zu bemuehen."""
    from app.esi.jwks import TokenClaims
    from app.esi.sso import TokenResponse

    claims = TokenClaims(
        character_id=factories.CHARACTER_ID,
        character_name=factories.CHARACTER_NAME,
        owner=factories.OWNER_HASH,
        scopes=("publicData", "esi-assets.read_assets.v1"),
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(minutes=20),
        issued_at=None,
        raw={},
    )
    token = TokenResponse(access_token="egal", refresh_token="refresh-eins", expires_in=1200)
    store.save(factories.CHARACTER_ID, "refresh-eins")
    await service.upsert_character(session, claims, token)


@respx.mock
async def test_refresh_speichert_den_neuen_token_sofort(
    service: CharacterService, store: MemoryTokenStore, migrated_db: Path
) -> None:
    """Der Fehler, der einen beim uebernaechsten Start aussperrt."""
    async with get_sessionmaker()() as session:
        await _verbinde(session, service, store)
        _mock_sso(refresh="refresh-zwei")

        await service.refresh(session, factories.CHARACTER_ID)

    assert store.load(factories.CHARACTER_ID) == "refresh-zwei"


@respx.mock
async def test_access_token_wird_zwischengespeichert(
    service: CharacterService, store: MemoryTokenStore, migrated_db: Path
) -> None:
    """Ein gueltiges Token erneut zu holen kostet nur Zeit."""
    async with get_sessionmaker()() as session:
        await _verbinde(session, service, store)
        route = _mock_sso()

        erster = await service.access_token(session, factories.CHARACTER_ID)
        zweiter = await service.access_token(session, factories.CHARACTER_ID)

    assert erster == zweiter
    assert route.call_count == 1


@respx.mock
async def test_abgelehnter_refresh_verlangt_neue_anmeldung(
    service: CharacterService, store: MemoryTokenStore, migrated_db: Path
) -> None:
    async with get_sessionmaker()() as session:
        await _verbinde(session, service, store)
        respx.post(SSO_TOKEN_URL).mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"})
        )

        with pytest.raises(RefreshTokenRejectedError):
            await service.refresh(session, factories.CHARACTER_ID)

    async with get_sessionmaker()() as session:
        character = await session.get(Character, factories.CHARACTER_ID)
        assert character is not None
        assert character.status == STATUS_NEEDS_REAUTH
        assert character.status_reason


@respx.mock
async def test_ein_ausfall_meldet_niemanden_ab(
    service: CharacterService, store: MemoryTokenStore, migrated_db: Path
) -> None:
    """Erst wiederholtes Scheitern ist ein Grund, jemanden auszusperren."""
    async with get_sessionmaker()() as session:
        await _verbinde(session, service, store)
        respx.post(SSO_TOKEN_URL).mock(return_value=httpx.Response(500, text="kaputt"))

        for _ in range(MAX_REFRESH_FAILURES - 1):
            with pytest.raises(SsoError):
                await service.refresh(session, factories.CHARACTER_ID)

        character = await session.get(Character, factories.CHARACTER_ID)
        assert character is not None
        assert character.status == STATUS_OK

        with pytest.raises(SsoError):
            await service.refresh(session, factories.CHARACTER_ID)

    async with get_sessionmaker()() as session:
        character = await session.get(Character, factories.CHARACTER_ID)
        assert character is not None
        assert character.status == STATUS_NEEDS_REAUTH


@respx.mock
async def test_verkaufter_charakter_verliert_seine_bestaende(
    service: CharacterService, store: MemoryTokenStore, migrated_db: Path
) -> None:
    """Sonst zeigt Foundry dem neuen Besitzer die Assets des alten."""
    async with get_sessionmaker()() as session:
        await _verbinde(session, service, store)
        session.add(
            Asset(
                item_id=1,
                owner_type="character",
                owner_id=factories.CHARACTER_ID,
                type_id=9_900_001,
                quantity=42,
                location_id=factories.STRUCTURE_ID,
            )
        )
        await session.commit()

        _mock_sso(access=factories.access_token(owner="ein-anderer-besitzer="))

        with pytest.raises(RefreshTokenRejectedError, match="verkauft"):
            await service.refresh(session, factories.CHARACTER_ID)

    async with get_sessionmaker()() as session:
        assets = (await session.execute(select(Asset))).scalars().all()
        assert assets == []
        character = await session.get(Character, factories.CHARACTER_ID)
        assert character is not None
        assert character.status == STATUS_NEEDS_REAUTH
    assert store.load(factories.CHARACTER_ID) is None, "Der Token muss weg sein"


async def test_entfernen_loescht_auch_den_token(
    service: CharacterService, store: MemoryTokenStore, migrated_db: Path
) -> None:
    async with get_sessionmaker()() as session:
        await _verbinde(session, service, store)
        session.add(
            Asset(
                item_id=2,
                owner_type="character",
                owner_id=factories.CHARACTER_ID,
                type_id=9_900_001,
                quantity=1,
                location_id=factories.STRUCTURE_ID,
            )
        )
        await session.commit()

        assert await service.remove(session, factories.CHARACTER_ID) is True

    assert store.load(factories.CHARACTER_ID) is None
    async with get_sessionmaker()() as session:
        assert await session.get(Character, factories.CHARACTER_ID) is None
        assert (await session.execute(select(Asset))).scalars().all() == []


async def test_entfernen_eines_unbekannten_charakters(
    service: CharacterService, migrated_db: Path
) -> None:
    async with get_sessionmaker()() as session:
        assert await service.remove(session, 9_000_999) is False


async def test_ohne_hinterlegten_token_gibt_es_kein_access_token(
    service: CharacterService, store: MemoryTokenStore, migrated_db: Path
) -> None:
    async with get_sessionmaker()() as session:
        await _verbinde(session, service, store)
        store.delete(factories.CHARACTER_ID)
        with pytest.raises(RefreshTokenRejectedError):
            await service.access_token(session, factories.CHARACTER_ID)


# -- Rollen ------------------------------------------------------------------
def test_erteilter_corp_scope_ohne_rolle_faellt_auf() -> None:
    """Der Fall, der sonst als leere Liste durchgeht."""
    fehlend = missing_roles_for(
        ("esi-assets.read_corporation_assets.v1", "esi-industry.read_corporation_jobs.v1"),
        ("Factory_Manager",),
    )
    assert fehlend == {"esi-assets.read_corporation_assets.v1": "Director"}


def test_ohne_corp_scopes_fehlt_auch_keine_rolle() -> None:
    assert missing_roles_for(("publicData",), ()) == {}


def test_mit_rolle_fehlt_nichts() -> None:
    assert missing_roles_for(("esi-assets.read_corporation_assets.v1",), ("Director",)) == {}
