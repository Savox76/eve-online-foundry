"""EVE SSO: der native Flow.

Es gelten ausschliesslich ``/v2/oauth/authorize`` und ``/v2/oauth/token``, und
der Token-Endpunkt akzeptiert **nur** ``application/x-www-form-urlencoded``
(Kapitel 4). Ein JSON-Body wird dort abgewiesen -- das ist der haeufigste
Grund, warum ein sonst korrekter Login-Ablauf nicht funktioniert.

Ein Client Secret gibt es nicht. Die Anwendung weist sich ueber PKCE aus.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.config import (
    SSO_AUTHORIZE_URL,
    SSO_TOKEN_URL,
    get_settings,
)
from app.esi.pkce import PkcePair
from app.esi.scopes import normalize_scp_claim

logger = logging.getLogger(__name__)

#: Wie lange vor Ablauf ein Access Token als "gleich fällig" gilt. Ohne diesen
#: Vorlauf startet man Abrufe mit einem Token, das waehrend des Requests
#: ablaeuft.
REFRESH_MARGIN_SECONDS = 60


class SsoError(Exception):
    """Der Login-Dienst hat abgelehnt."""


class RefreshTokenRejectedError(SsoError):
    """Der Refresh Token gilt nicht mehr.

    Passiert, wenn der Nutzer die Anwendung im Portal abgemeldet hat, der
    Charakter verkauft wurde -- oder wenn ein *alter* Refresh Token benutzt
    wurde, weil der neue aus der letzten Antwort nicht gespeichert worden ist.
    """


@dataclass(frozen=True, slots=True)
class TokenResponse:
    """Antwort des Token-Endpunkts."""

    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"

    @property
    def expires_at(self) -> dt.datetime:
        return dt.datetime.now(dt.UTC) + dt.timedelta(seconds=self.expires_in)


def authorize_url(scopes: tuple[str, ...], pkce: PkcePair, *, client_id: str = "") -> str:
    """Die URL, die im **Systembrowser** geoeffnet wird.

    Nicht in einem eingebetteten Fenster: der Nutzer soll die echte Adresszeile
    von CCP sehen. Eine Anwendung, die das Login-Formular selbst anzeigt, ist
    von Phishing nicht zu unterscheiden.
    """
    settings = get_settings()
    resolved = client_id or settings.esi_client_id
    if not resolved:
        raise SsoError(
            "Keine Client-ID konfiguriert. Im EVE-Developers-Portal eine Anwendung "
            "vom Typ 'native' anlegen und FOUNDRY_ESI_CLIENT_ID setzen."
        )

    query = urlencode(
        {
            "response_type": "code",
            "redirect_uri": settings.sso_callback_url,
            "client_id": resolved,
            "scope": " ".join(scopes),
            "state": pkce.state,
            "code_challenge": pkce.challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{SSO_AUTHORIZE_URL}?{query}"


class SsoClient:
    """Spricht mit dem Token-Endpunkt."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client_id: str = "",
    ) -> None:
        settings = get_settings()
        self._client_id = client_id or settings.esi_client_id
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            transport=transport,
            headers={
                "User-Agent": settings.user_agent,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> SsoClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def exchange_code(self, code: str, verifier: str) -> TokenResponse:
        """Tauscht den Autorisierungscode gegen Tokens."""
        return await self._post(
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self._client_id,
                "code_verifier": verifier,
            }
        )

    async def refresh(self, refresh_token: str) -> TokenResponse:
        """Holt ein neues Access Token.

        **Die Antwort enthaelt in aller Regel einen neuen Refresh Token.** Der
        Aufrufer speichert ihn sofort -- der alte ist danach wertlos.
        """
        return await self._post(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._client_id,
            }
        )

    async def _post(self, form: dict[str, str]) -> TokenResponse:
        try:
            response = await self._client.post(
                SSO_TOKEN_URL,
                data=form,
                # CCP prueft den Host-Header. Ueber einen Proxy kann httpx ihn
                # sonst abweichend setzen.
                headers={"Host": "login.eveonline.com"},
            )
        except httpx.HTTPError as exc:
            raise SsoError(f"Login-Dienst nicht erreichbar: {exc}") from exc

        if response.status_code == 400:
            detail = _error_detail(response)
            if "invalid_grant" in detail or "invalid_token" in detail:
                raise RefreshTokenRejectedError(
                    "Der Refresh Token gilt nicht mehr. Haeufigste Ursachen: die "
                    "Anwendung wurde im Portal abgemeldet, der Charakter wurde "
                    "verkauft, oder ein alter Token wurde erneut benutzt. "
                    "Der Charakter muss neu verbunden werden."
                )
            raise SsoError(f"Login-Dienst lehnt ab: {detail}")

        if response.status_code >= 400:
            raise SsoError(
                f"Login-Dienst antwortet {response.status_code}: {_error_detail(response)}"
            )

        payload = response.json()
        try:
            token = TokenResponse(
                access_token=payload["access_token"],
                refresh_token=payload["refresh_token"],
                expires_in=int(payload.get("expires_in", 1200)),
                token_type=payload.get("token_type", "Bearer"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SsoError(f"Unerwartete Antwort des Token-Endpunkts: {exc}") from exc

        # Der Token selbst darf nirgends in ein Log.
        logger.info("Tokens erhalten, gueltig fuer %d s.", token.expires_in)
        return token


def _error_detail(response: httpx.Response) -> str:
    """Fehlertext des Login-Dienstes -- ohne den Token mitzuloggen."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    parts = [str(payload.get(key, "")) for key in ("error", "error_description")]
    return " ".join(part for part in parts if part) or str(payload)[:200]


def granted_scopes(payload: object) -> tuple[str, ...]:
    """Bequemer Zugriff auf den normalisierten ``scp``-Claim."""
    return normalize_scp_claim(payload)
