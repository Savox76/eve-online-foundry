"""Die Laeufe, die der Scheduler ausfuehrt.

Der Unterschied zu einem Server steckt in der ersten Zeile jeder Funktion:
gefragt wird nicht "welche Uhrzeit ist es", sondern **"wie alt sind die
Daten"**. Ein Server laeuft durch und darf "nachts um vier" sagen; eine
Desktop-Anwendung laeuft nur, wenn jemand sie startet -- und wer sie nach zwei
Wochen wieder oeffnet, will aktuelle Zahlen sehen und nicht vierzehn
nachgeholte Laeufe (Kapitel 17, Phase 2).

Was hier **nicht** hineingehoert: jeder Aufruf der UI-Endpunkte von ESI. Ein
zeitgesteuerter oder gebuendelter UI-Aufruf ist keine Bedienhilfe mehr,
sondern Steuerung des Clients -- und die ist eindeutig untersagt (Kapitel 11).
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.esi.client import EsiClient
from app.esi.errors import EsiError
from app.esi.sso import SsoError
from app.models.esi import Asset, Character
from app.services.assets import OWNER_CHARACTER, get_asset_service
from app.services.characters import STATUS_OK, get_character_service

logger = logging.getLogger(__name__)


async def newest_asset_timestamp(character_id: int) -> dt.datetime | None:
    """Wann wurden die Bestaende dieses Charakters zuletzt geholt?"""
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(Asset.fetched_at)
            .where(Asset.owner_type == OWNER_CHARACTER, Asset.owner_id == character_id)
            .order_by(Asset.fetched_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def sync_assets(*, max_age_minutes: float = 70.0) -> None:
    """Holt die Bestaende aller Charaktere, deren Daten zu alt sind.

    Charaktere mit ``needs_reauth`` werden uebersprungen: ein Abruf mit einem
    ungueltigen Token kostet nur Fehlerbudget und wird nicht plotzlich
    funktionieren.
    """
    characters_service = get_character_service()
    assets_service = get_asset_service()
    threshold = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=max_age_minutes)

    async with get_sessionmaker()() as session:
        characters = (
            (await session.execute(select(Character).where(Character.status == STATUS_OK)))
            .scalars()
            .all()
        )
        if not characters:
            logger.debug("Kein verbundener Charakter -- nichts zu synchronisieren.")
            return

        async with EsiClient() as client:
            for character in characters:
                newest = await newest_asset_timestamp(character.character_id)
                if newest is not None and newest > threshold:
                    logger.debug(
                        "Bestaende von %s sind aktuell (%s) -- uebersprungen.",
                        character.name,
                        newest,
                    )
                    continue

                try:
                    token = await characters_service.access_token(session, character.character_id)
                    await assets_service.sync_character(
                        session, character.character_id, client=client, token=token
                    )
                except SsoError as exc:
                    # Der Charakter ist bereits als 'needs_reauth' markiert;
                    # die Oberflaeche zeigt das an. Kein Grund, den Lauf fuer
                    # die uebrigen Charaktere abzubrechen.
                    logger.warning("Bestaende von %s: %s", character.name, exc)
                except EsiError as exc:
                    logger.warning("Bestaende von %s nicht abrufbar: %s", character.name, exc)


async def sync_roles() -> None:
    """Gleicht In-Game-Rollen und Corp-Zugehoerigkeit ab.

    Verliert ein Charakter die Director-Rolle, versiegt der Corp-Sync lautlos.
    Deshalb wird regelmaessig nachgesehen und der Verlust sichtbar gemeldet,
    statt eine leere Liste anzuzeigen (Kapitel 18).
    """
    service = get_character_service()
    async with get_sessionmaker()() as session:
        characters = (
            (await session.execute(select(Character).where(Character.status == STATUS_OK)))
            .scalars()
            .all()
        )
        if not characters:
            return
        async with EsiClient() as client:
            for character in characters:
                try:
                    await service.sync_public(session, character.character_id, client=client)
                    await service.sync_roles(session, character.character_id, client=client)
                except (SsoError, EsiError) as exc:
                    logger.warning("Rollen von %s nicht abrufbar: %s", character.name, exc)
