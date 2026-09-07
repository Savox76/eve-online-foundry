"""Der Login-Ablauf: PKCE, Token-Endpunkt und JWT-Pruefung.

Was hier scharf geprueft wird, ist die *Ablehnung*. Ein gueltiges Token
durchzulassen ist die leichte Haelfte -- die schwere ist, dass ein Token mit
falschem Issuer, unvollstaendiger Audience oder fremdem ``state`` eben nicht
durchkommt.
"""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx

from app.core.config import SSO_JWKS_URL, SSO_TOKEN_URL
from app.esi.jwks import JwksCache, TokenValidationError, validate_access_token
from app.esi.pkce import PkcePair, challenge_for, create_verifier
from app.esi.sso import (
    RefreshTokenRejectedError,
    SsoClient,
    SsoError,
    authorize_url,
)
from tests import factories


# -- PKCE --------------------------------------------------------------------
def test_challenge_folgt_dem_rfc_beispiel() -> None:
    """Testvektor aus RFC 7636 -- damit steht die Implementierung fest."""
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert challenge_for(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_verifier_und_challenge_tragen_kein_padding() -> None:
    """Mit ``=`` weist die SSO den Request ab."""
    pair = PkcePair.create()
    assert "=" not in pair.verifier
    assert "=" not in pair.challenge
    assert len(create_verifier()) >= 43


def test_jeder_versuch_bekommt_eigene_werte() -> None:
    erster, zweiter = PkcePair.create(), PkcePair.create()
    assert erster.verifier != zweiter.verifier
    assert erster.state != zweiter.state


def test_fremder_state_wird_abgelehnt() -> None:
    pair = PkcePair.create()
    assert pair.matches_state(pair.state)
    assert not pair.matches_state("etwas anderes")


# -- Authorize-URL -----------------------------------------------------------
def test_authorize_url_enthaelt_alles_noetige(monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib.parse import parse_qs, urlsplit

    monkeypatch.setenv("FOUNDRY_ESI_CLIENT_ID", factories.CLIENT_ID)
    from app.core.config import reset_settings_cache

    reset_settings_cache()

    pair = PkcePair.create()
    url = authorize_url(("publicData", "esi-assets.read_assets.v1"), pair)
    params = parse_qs(urlsplit(url).query)

    assert params["response_type"] == ["code"]
    assert params["client_id"] == [factories.CLIENT_ID]
    assert params["code_challenge"] == [pair.challenge]
    assert params["code_challenge_method"] == ["S256"]
    assert params["scope"] == ["publicData esi-assets.read_assets.v1"]
    # Der Verifier bleibt im Prozess -- nur die Challenge geht raus.
    assert pair.verifier not in url


def test_ohne_client_id_gibt_es_keine_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOUNDRY_ESI_CLIENT_ID", "")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    with pytest.raises(SsoError, match="Client-ID"):
        authorize_url(("publicData",), PkcePair.create())


# -- Token-Endpunkt ----------------------------------------------------------
@respx.mock
async def test_code_wird_formularkodiert_getauscht() -> None:
    """Der Token-Endpunkt akzeptiert **nur** ``x-www-form-urlencoded``."""
    route = respx.post(SSO_TOKEN_URL).mock(
        return_value=httpx.Response(200, json=factories.token_response())
    )
    async with SsoClient(client_id=factories.CLIENT_ID) as client:
        token = await client.exchange_code("der-code", "der-verifier")

    request = route.calls.last.request
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    body = request.content.decode()
    assert "grant_type=authorization_code" in body
    assert "code_verifier=der-verifier" in body
    # Ein Client Secret gibt es beim nativen Flow nicht.
    assert "client_secret" not in body
    assert token.refresh_token == "refresh-eins"
    assert token.expires_at > dt.datetime.now(dt.UTC)


@respx.mock
async def test_refresh_schickt_den_richtigen_grant() -> None:
    route = respx.post(SSO_TOKEN_URL).mock(
        return_value=httpx.Response(200, json=factories.token_response(refresh="refresh-zwei"))
    )
    async with SsoClient(client_id=factories.CLIENT_ID) as client:
        token = await client.refresh("refresh-eins")

    body = route.calls.last.request.content.decode()
    assert "grant_type=refresh_token" in body
    assert "refresh_token=refresh-eins" in body
    assert token.refresh_token == "refresh-zwei", "Der neue Token muss zurueckkommen"


@respx.mock
async def test_invalid_grant_wird_als_abgelaufen_erkannt() -> None:
    """Der haeufigste Grund: ein alter Refresh Token wurde erneut benutzt."""
    respx.post(SSO_TOKEN_URL).mock(
        return_value=httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "Invalid refresh token"}
        )
    )
    async with SsoClient(client_id=factories.CLIENT_ID) as client:
        with pytest.raises(RefreshTokenRejectedError, match="neu verbunden"):
            await client.refresh("uralt")


@respx.mock
async def test_fehlermeldung_traegt_keinen_token(caplog: pytest.LogCaptureFixture) -> None:
    respx.post(SSO_TOKEN_URL).mock(return_value=httpx.Response(500, text="Internal Server Error"))
    with caplog.at_level("INFO"):
        async with SsoClient(client_id=factories.CLIENT_ID) as client:
            with pytest.raises(SsoError):
                await client.refresh("streng-geheimer-token")
    assert "streng-geheimer-token" not in caplog.text


# -- JWT-Pruefung ------------------------------------------------------------
@pytest.fixture
def jwks_route() -> respx.Route:
    return respx.get(SSO_JWKS_URL).mock(
        return_value=httpx.Response(200, json=factories.jwks_document())
    )


@respx.mock
async def test_gueltiges_token_wird_angenommen(jwks_route: respx.Route) -> None:
    claims = await validate_access_token(
        factories.access_token(), jwks=JwksCache(), client_id=factories.CLIENT_ID
    )
    assert claims.character_id == factories.CHARACTER_ID
    assert claims.character_name == factories.CHARACTER_NAME
    assert "esi-assets.read_assets.v1" in claims.scopes
    assert jwks_route.called


@respx.mock
async def test_einzelner_scope_kommt_als_string(jwks_route: respx.Route) -> None:
    """Der Fallstrick: bei genau einem Scope liefert das JWT einen String."""
    token = factories.access_token(scopes="publicData")
    claims = await validate_access_token(token, jwks=JwksCache(), client_id=factories.CLIENT_ID)
    assert claims.scopes == ("publicData",)


@respx.mock
async def test_fremder_issuer_wird_abgelehnt(jwks_route: respx.Route) -> None:
    token = factories.access_token(issuer="login.example.invalid")
    with pytest.raises(TokenValidationError, match="Issuer"):
        await validate_access_token(token, jwks=JwksCache(), client_id=factories.CLIENT_ID)


@respx.mock
async def test_issuer_mit_und_ohne_schema_gilt(jwks_route: respx.Route) -> None:
    """CCP liefert ihn mal so, mal so."""
    token = factories.access_token(issuer="https://login.eveonline.com")
    claims = await validate_access_token(token, jwks=JwksCache(), client_id=factories.CLIENT_ID)
    assert claims.character_id == factories.CHARACTER_ID


@respx.mock
async def test_audience_ohne_eve_online_wird_abgelehnt(jwks_route: respx.Route) -> None:
    token = factories.access_token(audience=[factories.CLIENT_ID])
    with pytest.raises(TokenValidationError, match="Audience"):
        await validate_access_token(token, jwks=JwksCache(), client_id=factories.CLIENT_ID)


@respx.mock
async def test_audience_einer_fremden_anwendung_wird_abgelehnt(jwks_route: respx.Route) -> None:
    """Sonst waere das Token einer anderen Anwendung hier gueltig."""
    token = factories.access_token(audience=["eine-fremde-client-id", "EVE Online"])
    with pytest.raises(TokenValidationError, match="Audience"):
        await validate_access_token(token, jwks=JwksCache(), client_id=factories.CLIENT_ID)


@respx.mock
async def test_abgelaufenes_token_wird_abgelehnt(jwks_route: respx.Route) -> None:
    token = factories.access_token(expires_in=-3600)
    with pytest.raises(TokenValidationError, match="abgelaufen"):
        await validate_access_token(token, jwks=JwksCache(), client_id=factories.CLIENT_ID)


@respx.mock
async def test_unbekannte_key_id_holt_den_schluesselsatz_neu() -> None:
    """Ein unbekanntes ``kid`` heisst fast immer: CCP hat rotiert."""
    veraltet = factories.jwks_document()
    veraltet["keys"][0]["kid"] = "alter-schluessel"
    route = respx.get(SSO_JWKS_URL).mock(
        side_effect=[
            httpx.Response(200, json=veraltet),
            httpx.Response(200, json=factories.jwks_document()),
        ]
    )
    claims = await validate_access_token(
        factories.access_token(), jwks=JwksCache(), client_id=factories.CLIENT_ID
    )
    assert claims.character_id == factories.CHARACTER_ID
    assert route.call_count == 2


@respx.mock
async def test_leerer_schluesselsatz_faellt_auf() -> None:
    """Ohne diese Pruefung schluege es erst spaeter und unverstaendlich fehl."""
    respx.get(SSO_JWKS_URL).mock(return_value=httpx.Response(200, json={"keys": []}))
    with pytest.raises(TokenValidationError, match="unbrauchbar"):
        await validate_access_token(
            factories.access_token(), jwks=JwksCache(), client_id=factories.CLIENT_ID
        )


@respx.mock
async def test_schluessel_bleibt_dauerhaft_unbekannt(jwks_route: respx.Route) -> None:
    token = factories.access_token(kid="gibt-es-nicht")
    with pytest.raises(TokenValidationError, match="steht nicht im JWKS"):
        await validate_access_token(token, jwks=JwksCache(), client_id=factories.CLIENT_ID)


@respx.mock
async def test_schluesselsatz_wird_zwischengespeichert(jwks_route: respx.Route) -> None:
    cache = JwksCache()
    for _ in range(3):
        await validate_access_token(
            factories.access_token(), jwks=cache, client_id=factories.CLIENT_ID
        )
    assert jwks_route.call_count == 1


@respx.mock
async def test_ausfall_des_jwks_nutzt_den_letzten_stand() -> None:
    """Lieber mit altem Schluesselsatz weiterarbeiten als aussperren."""
    route = respx.get(SSO_JWKS_URL).mock(
        side_effect=[
            httpx.Response(200, json=factories.jwks_document()),
            httpx.ConnectError("weg"),
        ]
    )
    cache = JwksCache(ttl=0.0)  # erzwingt den zweiten Abruf
    await validate_access_token(factories.access_token(), jwks=cache, client_id=factories.CLIENT_ID)
    claims = await validate_access_token(
        factories.access_token(), jwks=cache, client_id=factories.CLIENT_ID
    )
    assert claims.character_id == factories.CHARACTER_ID
    assert route.call_count == 2


def test_besitzerwechsel_wird_erkannt() -> None:
    from app.esi.jwks import TokenClaims

    claims = TokenClaims(
        character_id=factories.CHARACTER_ID,
        character_name=factories.CHARACTER_NAME,
        owner="neuer-besitzer=",
        scopes=(),
        expires_at=dt.datetime.now(dt.UTC),
        issued_at=None,
        raw={},
    )
    assert claims.owner_changed("alter-besitzer=") is True
    assert claims.owner_changed("neuer-besitzer=") is False
    # Beim allerersten Login gibt es keinen Vorgaenger -- das ist kein Wechsel.
    assert claims.owner_changed(None) is False
