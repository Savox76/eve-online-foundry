"""Bestaende holen, Standorte aufloesen, Deltas mitschreiben.

Drei Dinge passieren hier, und das zweite ist das, was man unterschaetzt:

**Holen.** Seitenweise ueber ``/characters/{id}/assets/``, 1000 Eintraege pro
Seite. Der Client prueft dabei, dass ``Last-Modified`` ueber alle Seiten
identisch bleibt -- sonst passen die Seiten nicht zusammen.

**Standorte aufloesen.** Ein ``location_id`` kann eine NPC-Station sein, eine
Spielerstruktur, ein Sonnensystem -- oder die ``item_id`` eines anderen Assets,
also ein Container oder ein Schiff. Um "liegt in Hangar X in Struktur Y" zu
beantworten, muss die Elternkette hochgelaufen werden, bis eine echte Location
auftaucht. Das erledigt eine rekursive CTE mit Zyklusschutz (Kapitel 5).

**Delta mitschreiben.** Der Sync laeuft ohnehin; wer dabei den alten Stand
ueberschreibt, wirft eine Historie weg, die er geschenkt bekaeme -- und die
sich spaeter *nicht* rekonstruieren laesst (Kapitel 7).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.esi.client import EsiClient
from app.esi.routes import CHARACTER_ASSET_NAMES, CHARACTER_ASSETS
from app.models.esi import Asset, AssetChange

logger = logging.getLogger(__name__)

#: Obergrenze fuer die Kette Container-in-Container. EVE schachtelt in der
#: Praxis hoechstens drei bis vier Ebenen; 32 ist grosszuegig und begrenzt
#: zugleich einen Zyklus, falls ESI je einen liefert.
MAX_CONTAINER_DEPTH = 32

#: Die Namensroute nimmt hoechstens so viele IDs pro Aufruf.
NAME_BATCH_SIZE = 1000

OWNER_CHARACTER = "character"


def classify_location(location_id: int, known_item_ids: set[int]) -> str:
    """Was fuer eine Art Ort ist das?

    Die ID-Baender stammen aus dem Aufbau der EVE-Datenbank und sind seit
    Jahren stabil. Ein ``location_id``, der zugleich die ``item_id`` eines
    anderen Assets ist, ist immer ein Container oder Schiff -- diese Pruefung
    steht deshalb zuerst.
    """
    if location_id in known_item_ids:
        return "item"
    if 30_000_000 <= location_id < 32_000_000:
        return "solar_system"
    if 60_000_000 <= location_id < 64_000_000:
        return "station"
    if location_id >= 1_000_000_000_000:
        return "structure"
    return "other"


@dataclass(slots=True)
class SyncResult:
    """Was ein Lauf bewirkt hat."""

    fetched: int = 0
    unchanged: bool = False
    added: int = 0
    removed: int = 0
    quantity_changes: int = 0
    moved: int = 0
    named: int = 0
    unresolved: int = 0
    changes: list[AssetChange] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return self.added + self.removed + self.quantity_changes + self.moved


class AssetService:
    """Der Asset-Sync eines Charakters."""

    async def sync_character(
        self,
        session: AsyncSession,
        character_id: int,
        *,
        client: EsiClient,
        token: str,
        with_names: bool = True,
    ) -> SyncResult:
        response = await client.request_all_pages(
            CHARACTER_ASSETS, token=token, path_params={"character_id": character_id}
        )
        if response.unchanged:
            logger.info("Bestaende von %d unveraendert -- nichts zu tun.", character_id)
            return SyncResult(unchanged=True)

        rows: list[dict[str, Any]] = list(response.data or [])
        result = await self._apply(session, character_id, rows)

        await self._resolve_locations(session, character_id)
        result.unresolved = await self._count_unresolved(session, character_id)

        if with_names:
            result.named = await self._fetch_names(
                session, character_id, client=client, token=token
            )

        await session.commit()
        logger.info(
            "Bestaende von %d: %d Eintraege, %d Aenderungen (%d neu, %d weg, %d Menge, %d bewegt)",
            character_id,
            result.fetched,
            result.total_changes,
            result.added,
            result.removed,
            result.quantity_changes,
            result.moved,
        )
        return result

    # -- Schreiben und Delta ------------------------------------------------
    async def _apply(
        self, session: AsyncSession, character_id: int, rows: list[dict[str, Any]]
    ) -> SyncResult:
        result = SyncResult(fetched=len(rows))
        now = dt.datetime.now(dt.UTC)

        previous = {
            row.item_id: row
            for row in (
                await session.execute(
                    select(Asset).where(
                        Asset.owner_type == OWNER_CHARACTER, Asset.owner_id == character_id
                    )
                )
            )
            .scalars()
            .all()
        }
        incoming_ids = {int(row["item_id"]) for row in rows if "item_id" in row}
        known_item_ids = incoming_ids

        for raw in rows:
            item_id = int(raw["item_id"])
            location_id = int(raw["location_id"])
            quantity = int(raw.get("quantity", 1))
            existing = previous.pop(item_id, None)

            if existing is None:
                session.add(
                    Asset(
                        item_id=item_id,
                        owner_type=OWNER_CHARACTER,
                        owner_id=character_id,
                        type_id=int(raw["type_id"]),
                        quantity=quantity,
                        location_id=location_id,
                        location_flag=str(raw.get("location_flag", "")),
                        location_type=classify_location(location_id, known_item_ids),
                        is_singleton=bool(raw.get("is_singleton", False)),
                        is_blueprint_copy=bool(raw.get("is_blueprint_copy", False)),
                        fetched_at=now,
                    )
                )
                result.added += 1
                result.changes.append(
                    self._change(
                        character_id,
                        kind="added",
                        item_id=item_id,
                        type_id=int(raw["type_id"]),
                        location_id=location_id,
                        quantity_after=quantity,
                        at=now,
                    )
                )
                continue

            if existing.quantity != quantity:
                result.quantity_changes += 1
                result.changes.append(
                    self._change(
                        character_id,
                        kind="quantity",
                        item_id=item_id,
                        type_id=existing.type_id,
                        location_id=location_id,
                        quantity_before=existing.quantity,
                        quantity_after=quantity,
                        at=now,
                    )
                )
            if existing.location_id != location_id:
                result.moved += 1
                result.changes.append(
                    self._change(
                        character_id,
                        kind="moved",
                        item_id=item_id,
                        type_id=existing.type_id,
                        location_id=location_id,
                        location_before=existing.location_id,
                        quantity_after=quantity,
                        at=now,
                    )
                )

            existing.quantity = quantity
            existing.location_id = location_id
            existing.location_flag = str(raw.get("location_flag", ""))
            existing.location_type = classify_location(location_id, known_item_ids)
            existing.is_singleton = bool(raw.get("is_singleton", False))
            existing.is_blueprint_copy = bool(raw.get("is_blueprint_copy", False))
            existing.fetched_at = now

        # Was uebrig bleibt, ist verschwunden.
        for gone in previous.values():
            result.removed += 1
            result.changes.append(
                self._change(
                    character_id,
                    kind="removed",
                    item_id=gone.item_id,
                    type_id=gone.type_id,
                    location_id=gone.location_id,
                    quantity_before=gone.quantity,
                    at=now,
                )
            )
        if previous:
            await session.execute(delete(Asset).where(Asset.item_id.in_(list(previous))))

        for change in result.changes:
            session.add(change)
        await session.flush()
        return result

    @staticmethod
    def _change(
        character_id: int,
        *,
        kind: str,
        item_id: int,
        type_id: int,
        location_id: int | None,
        at: dt.datetime,
        quantity_before: int | None = None,
        quantity_after: int | None = None,
        location_before: int | None = None,
    ) -> AssetChange:
        return AssetChange(
            owner_type=OWNER_CHARACTER,
            owner_id=character_id,
            item_id=item_id,
            type_id=type_id,
            location_id=location_id,
            kind=kind,
            quantity_before=quantity_before,
            quantity_after=quantity_after,
            location_before=location_before,
            observed_at=at,
        )

    # -- Standorte aufloesen ------------------------------------------------
    async def _resolve_locations(self, session: AsyncSession, character_id: int) -> None:
        """Laeuft die Elternkette hoch, bis eine echte Location auftaucht.

        Der Zyklusschutz ist ``depth < :max_depth``: ohne ihn wuerde ein Paar
        von Assets, die sich gegenseitig als Ort nennen, die CTE endlos laufen
        lassen.

        Der zweite Schritt ist der wichtigere. Wer die Grenze erreicht, hat
        keine Wurzel gefunden, sondern nur aufgehoert zu suchen -- sein
        ``root_location_id`` waere ein erfundener Ort und wuerde jedes
        Aggregat darueber verfaelschen. Solche Zeilen bekommen deshalb
        ``NULL`` und tauchen in der Oberflaeche als "unbekannt" auf. Eine
        fehlende Angabe sieht man; eine falsche glaubt man.
        """
        await session.flush()
        await session.execute(
            text(
                """
                WITH RECURSIVE chain(item_id, location_id, depth) AS (
                    SELECT a.item_id, a.location_id, 0
                      FROM esi_assets a
                     WHERE a.owner_type = :owner_type AND a.owner_id = :owner_id
                    UNION ALL
                    SELECT c.item_id, parent.location_id, c.depth + 1
                      FROM chain c
                      JOIN esi_assets parent ON parent.item_id = c.location_id
                     WHERE c.depth < :max_depth
                ),
                deepest AS (
                    SELECT item_id, location_id, depth,
                           ROW_NUMBER() OVER (
                               PARTITION BY item_id ORDER BY depth DESC
                           ) AS rang
                      FROM chain
                )
                UPDATE esi_assets
                   SET root_location_id = (
                           SELECT d.location_id FROM deepest d
                            WHERE d.item_id = esi_assets.item_id AND d.rang = 1
                       ),
                       depth = (
                           SELECT d.depth FROM deepest d
                            WHERE d.item_id = esi_assets.item_id AND d.rang = 1
                       )
                 WHERE owner_type = :owner_type AND owner_id = :owner_id
                """
            ),
            {
                "owner_type": OWNER_CHARACTER,
                "owner_id": character_id,
                "max_depth": MAX_CONTAINER_DEPTH,
            },
        )

        await session.execute(
            text(
                """
                UPDATE esi_assets
                   SET root_location_id = NULL
                 WHERE owner_type = :owner_type
                   AND owner_id = :owner_id
                   AND depth >= :max_depth
                """
            ),
            {
                "owner_type": OWNER_CHARACTER,
                "owner_id": character_id,
                "max_depth": MAX_CONTAINER_DEPTH,
            },
        )

    async def _count_unresolved(self, session: AsyncSession, character_id: int) -> int:
        rows = await session.execute(
            select(Asset.item_id).where(
                Asset.owner_type == OWNER_CHARACTER,
                Asset.owner_id == character_id,
                Asset.root_location_id.is_(None),
            )
        )
        return len(rows.scalars().all())

    # -- Namen --------------------------------------------------------------
    async def _fetch_names(
        self, session: AsyncSession, character_id: int, *, client: EsiClient, token: str
    ) -> int:
        """Holt die Namen benannter Container und Schiffe.

        Nur fuer ``is_singleton`` -- gestapelte Items koennen keinen Namen
        tragen, und jede unnoetige ID im Request kostet Budget.
        """
        candidates = (
            (
                await session.execute(
                    select(Asset.item_id).where(
                        Asset.owner_type == OWNER_CHARACTER,
                        Asset.owner_id == character_id,
                        Asset.is_singleton.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not candidates:
            return 0

        named = 0
        for start in range(0, len(candidates), NAME_BATCH_SIZE):
            batch = [int(item) for item in candidates[start : start + NAME_BATCH_SIZE]]
            response = await client.request(
                CHARACTER_ASSET_NAMES,
                token=token,
                json=batch,
                path_params={"character_id": character_id},
                use_cache=False,
            )
            for entry in response.data or []:
                name = str(entry.get("name", "")).strip()
                # ESI liefert fuer unbenannte Container den Typnamen oder
                # "None" zurueck. Beides ist kein Name und wird verworfen.
                if not name or name == "None":
                    continue
                asset = await session.get(Asset, int(entry["item_id"]))
                if asset is not None:
                    asset.name = name
                    named += 1
        return named


_service: AssetService | None = None


def get_asset_service() -> AssetService:
    global _service
    if _service is None:
        _service = AssetService()
    return _service
