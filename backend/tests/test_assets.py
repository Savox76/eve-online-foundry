"""Bestaende: Delta, Standortaufloesung und Namen.

Der Delta-Teil ist der, der in Kapitel 7 als "faellt in Phase 2 und ist nicht
nachholbar" markiert ist. Deshalb steht er hier vollstaendig unter Test --
inklusive der vier Faelle, die er auseinanderhalten muss.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select

from app.core.config import ESI_BASE_URL
from app.core.db import get_sessionmaker
from app.esi.cache import InMemoryEtagStore
from app.esi.client import EsiClient
from app.models.esi import Asset, AssetChange
from app.services.assets import MAX_CONTAINER_DEPTH, AssetService, classify_location
from app.services.locations import fallback_name
from tests import factories

ASSETS_URL = f"{ESI_BASE_URL}/characters/{factories.CHARACTER_ID}/assets/"
NAMES_URL = f"{ESI_BASE_URL}/characters/{factories.CHARACTER_ID}/assets/names/"


def _mock_assets(rows: list[dict[str, Any]], *, names: list[dict[str, Any]] | None = None) -> None:
    respx.get(ASSETS_URL).mock(
        return_value=httpx.Response(200, json=rows, headers={"X-Pages": "1"})
    )
    respx.post(NAMES_URL).mock(return_value=httpx.Response(200, json=names or []))


async def _sync(rows: list[dict[str, Any]], **kwargs: Any) -> Any:
    async with (
        get_sessionmaker()() as session,
        EsiClient(etag_store=InMemoryEtagStore()) as client,
    ):
        _mock_assets(rows, **kwargs)
        return await AssetService().sync_character(
            session, factories.CHARACTER_ID, client=client, token="egal"
        )


# -- Ortsarten ---------------------------------------------------------------
@pytest.mark.parametrize(
    ("location_id", "erwartet"),
    [
        (30_000_142, "solar_system"),
        (60_003_760, "station"),
        (1_035_000_000_001, "structure"),
        (12_345, "other"),
    ],
)
def test_ortsarten_werden_erkannt(location_id: int, erwartet: str) -> None:
    assert classify_location(location_id, set()) == erwartet


def test_ein_anderes_asset_als_ort_ist_ein_container() -> None:
    """Diese Pruefung steht zuerst -- sonst wuerde ein Container falsch einsortiert."""
    assert classify_location(60_003_760, {60_003_760}) == "item"


def test_rueckfallnamen_sind_aussagekraeftig() -> None:
    """Eine leere Zelle sieht aus wie ein Fehler; eine ID ist eine Auskunft."""
    assert fallback_name(1_035_000_000_001) == "Unbekannte Struktur #1035000000001"
    assert fallback_name(None) == "Unbekannter Ort"


# -- Erster Lauf -------------------------------------------------------------
@respx.mock
async def test_erster_lauf_legt_alles_neu_an(migrated_db: Path) -> None:
    ergebnis = await _sync(
        [
            factories.asset(1, type_id=9_900_001, quantity=32_000),
            factories.asset(2, type_id=9_900_002, quantity=8_000),
        ]
    )
    assert ergebnis.fetched == 2
    assert ergebnis.added == 2
    assert ergebnis.removed == 0

    async with get_sessionmaker()() as session:
        assert len((await session.execute(select(Asset))).scalars().all()) == 2
        aenderungen = (await session.execute(select(AssetChange))).scalars().all()
        assert {a.kind for a in aenderungen} == {"added"}


# -- Die vier Delta-Faelle ---------------------------------------------------
@respx.mock
async def test_mengenaenderung_wird_erkannt(migrated_db: Path) -> None:
    await _sync([factories.asset(1, quantity=1000)])
    ergebnis = await _sync([factories.asset(1, quantity=400)])

    assert ergebnis.quantity_changes == 1
    async with get_sessionmaker()() as session:
        change = (
            (await session.execute(select(AssetChange).where(AssetChange.kind == "quantity")))
            .scalars()
            .one()
        )
        assert change.quantity_before == 1000
        assert change.quantity_after == 400


@respx.mock
async def test_verschwundener_bestand_wird_erkannt(migrated_db: Path) -> None:
    """ "Wo sind die 2000 Morphite geblieben" -- die Frage, die sonst niemand beantworten kann."""
    await _sync([factories.asset(1, quantity=2000), factories.asset(2)])
    ergebnis = await _sync([factories.asset(2)])

    assert ergebnis.removed == 1
    async with get_sessionmaker()() as session:
        change = (
            (await session.execute(select(AssetChange).where(AssetChange.kind == "removed")))
            .scalars()
            .one()
        )
        assert change.quantity_before == 2000
        assert (await session.execute(select(Asset).where(Asset.item_id == 1))).scalar() is None


@respx.mock
async def test_umzug_wird_als_umzug_erkannt(migrated_db: Path) -> None:
    """Nicht als 'weg' plus 'neu' -- sonst sieht jeder Transport wie ein Verlust aus."""
    await _sync([factories.asset(1, location_id=factories.STRUCTURE_ID)])
    ergebnis = await _sync([factories.asset(1, location_id=factories.STATION_ID)])

    assert ergebnis.moved == 1
    assert ergebnis.removed == 0
    assert ergebnis.added == 0
    async with get_sessionmaker()() as session:
        change = (
            (await session.execute(select(AssetChange).where(AssetChange.kind == "moved")))
            .scalars()
            .one()
        )
        assert change.location_before == factories.STRUCTURE_ID
        assert change.location_id == factories.STATION_ID


@respx.mock
async def test_unveraenderter_bestand_schreibt_kein_delta(migrated_db: Path) -> None:
    """Sonst waechst die Tabelle bei jedem Lauf, ohne etwas auszusagen."""
    await _sync([factories.asset(1, quantity=100)])
    ergebnis = await _sync([factories.asset(1, quantity=100)])

    assert ergebnis.total_changes == 0
    async with get_sessionmaker()() as session:
        aenderungen = (await session.execute(select(AssetChange))).scalars().all()
        assert len(aenderungen) == 1, "nur der erste Lauf darf etwas geschrieben haben"


@respx.mock
async def test_304_laesst_die_bestaende_unberuehrt(migrated_db: Path) -> None:
    """Der haeufigste Gutfall im Dauerbetrieb: nichts zu tun."""
    await _sync([factories.asset(1, quantity=100)])

    async with (
        get_sessionmaker()() as session,
        EsiClient(etag_store=InMemoryEtagStore()) as client,
    ):
        respx.get(ASSETS_URL).mock(return_value=httpx.Response(304))
        ergebnis = await AssetService().sync_character(
            session, factories.CHARACTER_ID, client=client, token="egal"
        )

    assert ergebnis.unchanged is True
    assert ergebnis.total_changes == 0
    async with get_sessionmaker()() as session:
        assert len((await session.execute(select(Asset))).scalars().all()) == 1


# -- Standorte ---------------------------------------------------------------
@respx.mock
async def test_container_kette_wird_aufgeloest(migrated_db: Path) -> None:
    """Schiff in Struktur, Container im Schiff, Erz im Container."""
    await _sync(
        [
            factories.asset(500, location_id=factories.STRUCTURE_ID, singleton=True),
            factories.asset(501, location_id=500, location_flag="Cargo", singleton=True),
            factories.asset(502, location_id=501, location_flag="Cargo", quantity=5000),
        ]
    )

    async with get_sessionmaker()() as session:
        assets = {a.item_id: a for a in (await session.execute(select(Asset))).scalars().all()}
        assert assets[500].root_location_id == factories.STRUCTURE_ID
        assert assets[500].depth == 0
        assert assets[502].root_location_id == factories.STRUCTURE_ID
        assert assets[502].depth == 2


@respx.mock
async def test_zyklus_liefert_keinen_erfundenen_ort(migrated_db: Path) -> None:
    """Ein falsches Aggregat ist schlimmer als ein fehlendes.

    Wer die Tiefengrenze erreicht, hat keine Wurzel gefunden, sondern nur
    aufgehoert zu suchen. Solche Zeilen bekommen ``NULL`` und tauchen als
    "unbekannt" auf -- eine fehlende Angabe sieht man, eine falsche glaubt man.
    """
    ergebnis = await _sync(
        [
            factories.asset(700, location_id=701, singleton=True),
            factories.asset(701, location_id=700, singleton=True),
        ]
    )
    assert ergebnis.unresolved == 2

    async with get_sessionmaker()() as session:
        for asset in (await session.execute(select(Asset))).scalars():
            assert asset.root_location_id is None
            assert asset.depth == MAX_CONTAINER_DEPTH


# -- Namen -------------------------------------------------------------------
@respx.mock
async def test_benannte_container_bekommen_ihren_namen(migrated_db: Path) -> None:
    ergebnis = await _sync(
        [factories.asset(600, location_id=factories.STRUCTURE_ID, singleton=True)],
        names=[{"item_id": 600, "name": "Ersatzteile Raitaru"}],
    )
    assert ergebnis.named == 1
    async with get_sessionmaker()() as session:
        asset = (await session.execute(select(Asset).where(Asset.item_id == 600))).scalar_one()
        assert asset.name == "Ersatzteile Raitaru"


@respx.mock
async def test_unbenannte_container_bleiben_ohne_namen(migrated_db: Path) -> None:
    """ESI liefert dafuer den Typnamen oder woertlich "None" -- beides ist kein Name."""
    ergebnis = await _sync(
        [factories.asset(601, singleton=True)],
        names=[{"item_id": 601, "name": "None"}],
    )
    assert ergebnis.named == 0
    async with get_sessionmaker()() as session:
        asset = (await session.execute(select(Asset).where(Asset.item_id == 601))).scalar_one()
        assert asset.name is None


@respx.mock
async def test_gestapelte_items_werden_nicht_nach_namen_gefragt(migrated_db: Path) -> None:
    """Ein Stapel kann keinen Namen tragen -- jede unnoetige ID kostet Budget."""
    route = respx.post(NAMES_URL).mock(return_value=httpx.Response(200, json=[]))
    await _sync([factories.asset(1, quantity=5000, singleton=False)])
    assert route.call_count == 0
