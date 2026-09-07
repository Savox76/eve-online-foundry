"""EVE SSO: Charaktere verbinden und verbunden halten.

Der Login laeuft als Hintergrundaufgabe, weil zwischen dem Oeffnen des
Browsers und der Rueckkehr Minuten liegen koennen. ``POST /auth/login`` gibt
sofort die URL zurueck, ``GET /auth/login/{id}`` sagt, wie weit es ist.

Die Oberflaeche oeffnet diese URL im **Systembrowser**. Ein eingebettetes
Login-Formular waere von Phishing nicht zu unterscheiden (Kapitel 4).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.esi.client import EsiClient
from app.esi.scopes import REQUIRED_CORP_ROLE, SCOPES_BY_TIER, ScopeTier
from app.esi.sso import SsoError
from app.models.esi import CharacterRole
from app.schemas.auth import (
    CharacterInfo,
    CharacterListResponse,
    LoginStartRequest,
    LoginStartResponse,
    LoginStatusResponse,
    ScopeTierInfo,
)
from app.services.characters import get_character_service, missing_roles_for

router = APIRouter(prefix="/auth", tags=["auth"])

#: Was in der Oberflaeche neben jedem Paket steht. Die Beschreibung ist der
#: eigentliche Zweck der Staffelung: wer weiss, wofuer ein Scope gebraucht
#: wird, erteilt ihn eher.
TIER_LABELS: dict[ScopeTier, tuple[str, str]] = {
    ScopeTier.BASE: (
        "Basis",
        "Ohne diese sieben Scopes ist ein Charakter fuer Foundry nicht nutzbar: "
        "Bestaende, Blueprints, laufende Jobs, Skills, Strukturnamen und Rollen.",
    ),
    ScopeTier.FITTINGS: ("Fittings", "Ingame-Fittings lesen und Doktrinen zurueckschreiben."),
    ScopeTier.COMFORT: (
        "Komfort",
        "Markt-, Contract- und Infofenster im Client oeffnen, Wegpunkt setzen. "
        "Wirkt nur auf Klick, nie zeitgesteuert.",
    ),
    ScopeTier.MAIL: (
        "Nachrichten",
        "Postfach lesen und beantworten. Optional und je Charakter; die Mails "
        "sind nur fuer den Besitzer sichtbar.",
    ),
    ScopeTier.PLANETS: ("Planetare Industrie", "Kolonien, Extraktoren und Fabriken."),
    ScopeTier.CORP: (
        "Corp",
        "Corp-Hangars, -Blueprints, -Jobs und -Strukturen. Braucht zusaetzlich "
        "die passende In-Game-Rolle -- ohne sie antwortet ESI mit 403.",
    ),
    ScopeTier.OPTIONAL: ("Optional", "Preise aus eigenen Strukturmaerkten."),
}


@router.get("/scopes", response_model=list[ScopeTierInfo], summary="Scope-Pakete")
async def scope_tiers() -> list[ScopeTierInfo]:
    return [
        ScopeTierInfo(
            tier=tier.value,
            label=TIER_LABELS[tier][0],
            description=TIER_LABELS[tier][1],
            scopes=list(scopes),
            required_roles={
                scope: role for scope, role in REQUIRED_CORP_ROLE.items() if scope in scopes
            },
        )
        for tier, scopes in SCOPES_BY_TIER.items()
    ]


@router.post("/login", response_model=LoginStartResponse, summary="Anmeldung starten")
async def start_login(payload: LoginStartRequest) -> LoginStartResponse:
    try:
        tiers = tuple(ScopeTier(value) for value in payload.tiers)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unbekanntes Scope-Paket: {exc}") from exc
    if not tiers:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mindestens ein Scope-Paket angeben.")
    # Ohne das Basispaket kann Foundry mit dem Charakter nichts anfangen.
    if ScopeTier.BASE not in tiers:
        tiers = (ScopeTier.BASE, *tiers)

    try:
        attempt = get_character_service().start_login(tiers)
    except SsoError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return LoginStartResponse(id=attempt.id, url=attempt.url)


@router.get(
    "/login/{attempt_id}", response_model=LoginStatusResponse, summary="Stand der Anmeldung"
)
async def login_status(attempt_id: str) -> LoginStatusResponse:
    attempt = get_character_service().attempt(attempt_id)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unbekannter Anmeldeversuch.")
    return LoginStatusResponse(
        id=attempt.id,
        state=attempt.state.value,
        character_id=attempt.character_id,
        character_name=attempt.character_name,
        error=attempt.error,
        started_at=attempt.started_at,
    )


@router.get("/characters", response_model=CharacterListResponse, summary="Verbundene Charaktere")
async def list_characters(session: AsyncSession = Depends(get_session)) -> CharacterListResponse:
    service = get_character_service()
    entries = await service.list_characters(session)

    infos: list[CharacterInfo] = []
    for character, token in entries:
        roles = (
            (
                await session.execute(
                    select(CharacterRole.role).where(
                        CharacterRole.character_id == character.character_id,
                        CharacterRole.scope == "roles",
                    )
                )
            )
            .scalars()
            .all()
        )
        scopes = token.scope_list() if token else ()
        infos.append(
            CharacterInfo(
                character_id=character.character_id,
                name=character.name,
                corporation_id=character.corporation_id,
                alliance_id=character.alliance_id,
                status=character.status,
                status_reason=character.status_reason,
                connected_at=character.connected_at,
                last_seen_at=character.last_seen_at,
                scopes=list(scopes),
                token_storage=token.storage if token else "",
                access_expires_at=token.access_expires_at if token else None,
                last_refresh_at=token.last_refresh_at if token else None,
                roles=[str(role) for role in roles],
                scopes_without_role=missing_roles_for(scopes, tuple(str(r) for r in roles)),
            )
        )

    return CharacterListResponse(characters=infos, token_storage=service.token_storage)


@router.delete(
    "/characters/{character_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Charakter entfernen",
)
async def remove_character(character_id: int, session: AsyncSession = Depends(get_session)) -> None:
    """Entfernt den Charakter samt Refresh Token und seinen Bestaenden."""
    if not await get_character_service().remove(session, character_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Charakter nicht verbunden.")


@router.post(
    "/characters/{character_id}/refresh",
    response_model=CharacterInfo,
    summary="Token erneuern und Rollen abgleichen",
)
async def refresh_character(
    character_id: int, session: AsyncSession = Depends(get_session)
) -> CharacterInfo:
    service = get_character_service()
    try:
        await service.refresh(session, character_id)
    except SsoError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    async with EsiClient() as client:
        await service.sync_public(session, character_id, client=client)
        await service.sync_roles(session, character_id, client=client)

    listed = await list_characters(session)
    for info in listed.characters:
        if info.character_id == character_id:
            return info
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Charakter nicht verbunden.")
