"""Standort-IDs in lesbare Namen uebersetzen.

Ein Ort kann aus drei Quellen kommen: NPC-Stationen und Sonnensysteme stehen
im SDE, Spielerstrukturen kommen aus ESI. Und manche Struktur kommt gar nicht:
ohne Docking-Zugriff antwortet ``/universe/structures/{id}/`` mit 403.

Genau dafuer gibt es den Rueckfall ``Unbekannte Struktur #1035…``. Ohne ihn
haengt der ganze Asset-Sync an einer einzigen fremden Struktur (Kapitel 5) --
und in der Tabelle stuende eine leere Zelle, die aussieht wie ein Fehler.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.esi import Structure
from app.models.sde import SdeStation, SdeSystem

logger = logging.getLogger(__name__)


def fallback_name(location_id: int | None, location_type: str = "") -> str:
    """Was angezeigt wird, wenn der Name nicht aufloesbar ist."""
    if location_id is None:
        return "Unbekannter Ort"
    if location_type == "structure" or location_id >= 1_000_000_000_000:
        return f"Unbekannte Struktur #{location_id}"
    return f"Unbekannter Ort #{location_id}"


class LocationResolver:
    """Loest eine Menge von Standort-IDs in einem Rutsch auf.

    Bewusst als Stapelabfrage: eine Bestandstabelle mit 50.000 Zeilen hat
    vielleicht zwanzig verschiedene Orte. Je Zeile einzeln nachzuschlagen
    waere zwanzig Abfragen -- oder fuenfzigtausend.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(self, location_ids: Iterable[int | None]) -> dict[int, str]:
        wanted = {location_id for location_id in location_ids if location_id is not None}
        if not wanted:
            return {}

        names: dict[int, str] = {}
        ids = list(wanted)

        stations = await self._session.execute(
            select(SdeStation.station_id, SdeStation.name).where(SdeStation.station_id.in_(ids))
        )
        for station_id, name in stations:
            names[int(station_id)] = str(name)

        systems = await self._session.execute(
            select(SdeSystem.system_id, SdeSystem.name).where(SdeSystem.system_id.in_(ids))
        )
        for system_id, name in systems:
            names[int(system_id)] = str(name)

        structures = await self._session.execute(
            select(Structure.structure_id, Structure.name, Structure.access_denied).where(
                Structure.structure_id.in_(ids)
            )
        )
        for structure_id, name, access_denied in structures:
            if access_denied or not name:
                continue
            names[int(structure_id)] = str(name)

        return names

    async def name_for(self, location_id: int | None, location_type: str = "") -> str:
        if location_id is None:
            return fallback_name(None)
        found = await self.resolve([location_id])
        return found.get(location_id) or fallback_name(location_id, location_type)
