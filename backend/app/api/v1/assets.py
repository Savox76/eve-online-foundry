"""Bestaende: abrufen, durchsuchen, und was sich veraendert hat.

Zwei Nutzungsmuster praegen diese Ansicht (Kapitel 15): gezielte Suche ("wo
liegen meine Morphite?") und wiederkehrende Kontrolle ("was hat sich seit
gestern bewegt?"). Beides gewinnt man mit dichten, sortierbaren Tabellen --
deshalb liefert diese API Zeilen und Gesamtzahlen, keine verschachtelten
Baeume.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.esi.client import EsiClient
from app.esi.errors import EsiError
from app.esi.sso import SsoError
from app.models.esi import Asset, AssetChange, Character
from app.models.sde import SdeGroup, SdeType
from app.schemas.assets import (
    AssetChangeListResponse,
    AssetChangeRow,
    AssetListResponse,
    AssetRow,
    LocationSummary,
    SyncResultResponse,
)
from app.services.assets import get_asset_service
from app.services.characters import get_character_service
from app.services.locations import LocationResolver, fallback_name

router = APIRouter(prefix="/assets", tags=["assets"])


@router.post("/sync", response_model=SyncResultResponse, summary="Bestaende abrufen")
async def sync_assets(
    character_id: int = Query(description="Welcher Charakter"),
    session: AsyncSession = Depends(get_session),
) -> SyncResultResponse:
    """Holt die Bestaende eines Charakters von ESI.

    Der Client haelt sich dabei an ``Expires`` und ``ETag`` -- ein Aufruf kurz
    nach dem letzten liefert deshalb ``unchanged`` und kostet fast nichts.
    """
    if await session.get(Character, character_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Charakter nicht verbunden.")

    characters = get_character_service()
    try:
        token = await characters.access_token(session, character_id)
    except SsoError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    try:
        async with EsiClient() as client:
            result = await get_asset_service().sync_character(
                session, character_id, client=client, token=token
            )
    except EsiError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return SyncResultResponse(
        character_id=character_id,
        unchanged=result.unchanged,
        fetched=result.fetched,
        added=result.added,
        removed=result.removed,
        quantity_changes=result.quantity_changes,
        moved=result.moved,
        named=result.named,
        unresolved=result.unresolved,
    )


@router.get("", response_model=AssetListResponse, summary="Bestaende")
async def list_assets(
    session: AsyncSession = Depends(get_session),
    character_id: int | None = Query(default=None),
    search: str = Query(default="", description="Teil eines Typnamens"),
    location_id: int | None = Query(default=None, description="Wurzelort"),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> AssetListResponse:
    conditions = []
    if character_id is not None:
        conditions.append(Asset.owner_id == character_id)
    if location_id is not None:
        conditions.append(Asset.root_location_id == location_id)

    query = (
        select(Asset, SdeType.name, SdeType.volume, SdeType.packaged_volume, SdeGroup.name)
        .join(SdeType, SdeType.type_id == Asset.type_id, isouter=True)
        .join(SdeGroup, SdeGroup.group_id == SdeType.group_id, isouter=True)
    )
    for condition in conditions:
        query = query.where(condition)
    if search:
        query = query.where(SdeType.name.ilike(f"%{search}%"))

    total_query = select(func.count()).select_from(query.subquery())
    total = int((await session.execute(total_query)).scalar_one())

    rows = (
        await session.execute(
            query.order_by(Asset.root_location_id, SdeType.name, Asset.item_id)
            .limit(limit)
            .offset(offset)
        )
    ).all()

    resolver = LocationResolver(session)
    names = await resolver.resolve(
        [asset.root_location_id for asset, *_ in rows] + [asset.location_id for asset, *_ in rows]
    )
    container_names = await _container_names(session, [asset for asset, *_ in rows])

    result: list[AssetRow] = []
    newest: dt.datetime | None = None
    for asset, type_name, volume, packaged_volume, group_name in rows:
        unit_volume = packaged_volume if packaged_volume is not None else volume
        newest = asset.fetched_at if newest is None or asset.fetched_at > newest else newest
        result.append(
            AssetRow(
                item_id=asset.item_id,
                type_id=asset.type_id,
                type_name=type_name or f"Typ #{asset.type_id}",
                group_name=group_name or "",
                quantity=asset.quantity,
                volume=unit_volume,
                total_volume=(unit_volume * asset.quantity) if unit_volume is not None else None,
                location_id=asset.location_id,
                location_type=asset.location_type,
                location_flag=asset.location_flag,
                root_location_id=asset.root_location_id,
                location_name=names.get(asset.root_location_id or -1)
                or fallback_name(asset.root_location_id, asset.location_type),
                depth=asset.depth,
                container_name=container_names.get(asset.location_id),
                is_singleton=asset.is_singleton,
                is_blueprint_copy=asset.is_blueprint_copy,
                fetched_at=asset.fetched_at,
            )
        )

    unresolved_query = (
        select(func.count()).select_from(Asset).where(Asset.root_location_id.is_(None))
    )
    if character_id is not None:
        unresolved_query = unresolved_query.where(Asset.owner_id == character_id)
    unresolved = int((await session.execute(unresolved_query)).scalar_one())

    return AssetListResponse(rows=result, total=total, unresolved=unresolved, fetched_at=newest)


async def _container_names(session: AsyncSession, assets: list[Asset]) -> dict[int, str]:
    """Namen der Container, in denen die Zeilen liegen.

    Damit steht in der Tabelle "in *Ersatzteile Raitaru*" statt einer nackten
    Item-ID -- der Unterschied zwischen einer brauchbaren und einer
    unbrauchbaren Ortsangabe.
    """
    parents = {asset.location_id for asset in assets if asset.location_type == "item"}
    if not parents:
        return {}
    rows = await session.execute(
        select(Asset.item_id, Asset.name, SdeType.name)
        .join(SdeType, SdeType.type_id == Asset.type_id, isouter=True)
        .where(Asset.item_id.in_(list(parents)))
    )
    return {
        int(item_id): str(own_name or type_name or f"Container #{item_id}")
        for item_id, own_name, type_name in rows
    }


@router.get("/locations", response_model=list[LocationSummary], summary="Orte mit Bestand")
async def list_locations(
    session: AsyncSession = Depends(get_session),
    character_id: int | None = Query(default=None),
) -> list[LocationSummary]:
    query = select(
        Asset.root_location_id,
        func.count().label("stacks"),
        func.sum(Asset.quantity).label("items"),
    ).group_by(Asset.root_location_id)
    if character_id is not None:
        query = query.where(Asset.owner_id == character_id)

    rows = (await session.execute(query)).all()
    resolver = LocationResolver(session)
    names = await resolver.resolve([root for root, *_ in rows])

    summaries = [
        LocationSummary(
            location_id=root,
            name=names.get(root or -1) or fallback_name(root),
            location_type="structure" if root and root >= 1_000_000_000_000 else "",
            stacks=int(stacks or 0),
            items=int(items or 0),
        )
        for root, stacks, items in rows
    ]
    return sorted(summaries, key=lambda entry: (-entry.stacks, entry.name))


@router.get("/changes", response_model=AssetChangeListResponse, summary="Was sich bewegt hat")
async def list_changes(
    session: AsyncSession = Depends(get_session),
    character_id: int | None = Query(default=None),
    since_hours: int = Query(default=24, ge=1, le=24 * 90),
    limit: int = Query(default=200, ge=1, le=2000),
) -> AssetChangeListResponse:
    """Die taegliche Kontrollfrage: was hat sich seit gestern veraendert?"""
    since = dt.datetime.now(dt.UTC) - dt.timedelta(hours=since_hours)

    query = (
        select(AssetChange, SdeType.name)
        .join(SdeType, SdeType.type_id == AssetChange.type_id, isouter=True)
        .where(AssetChange.observed_at >= since)
    )
    if character_id is not None:
        query = query.where(AssetChange.owner_id == character_id)

    total = int(
        (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    )
    rows = (
        await session.execute(query.order_by(AssetChange.observed_at.desc()).limit(limit))
    ).all()

    resolver = LocationResolver(session)
    names = await resolver.resolve([change.location_id for change, _ in rows])

    return AssetChangeListResponse(
        rows=[
            AssetChangeRow(
                id=change.id,
                kind=change.kind,
                item_id=change.item_id,
                type_id=change.type_id,
                type_name=type_name or f"Typ #{change.type_id}",
                quantity_before=change.quantity_before,
                quantity_after=change.quantity_after,
                delta=_delta(change),
                location_id=change.location_id,
                location_name=names.get(change.location_id or -1)
                or fallback_name(change.location_id),
                location_before=change.location_before,
                observed_at=change.observed_at,
            )
            for change, type_name in rows
        ],
        total=total,
    )


def _delta(change: AssetChange) -> int | None:
    """Differenz, wo eine sinnvoll ist.

    Bei ``moved`` bleibt sie leer: die Menge hat sich nicht geaendert, nur der
    Ort. Eine 0 dort wuerde so aussehen, als waere nichts passiert.
    """
    if change.kind == "added":
        return change.quantity_after
    if change.kind == "removed":
        return -(change.quantity_before or 0)
    if change.kind == "quantity":
        return (change.quantity_after or 0) - (change.quantity_before or 0)
    return None
