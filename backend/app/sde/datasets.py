"""Was aus welcher Export-Datei in welche Tabelle wandert.

Eine Datei, eine Wahrheit. Wenn CCP ein Feld umbenennt, ist genau hier zu
korrigieren -- nicht in einem Importer voller Sonderfaelle.

.. warning::
   Die Dateinamen und Feldnamen sind der Stand der offiziellen Dokumentation
   und **vor dem ersten echten Import gegen den tatsaechlichen Export zu
   pruefen**. Genau dafuer gibt es ``python -m app.sde.importer --report``:
   es sagt, welche Kandidaten gefunden wurden und welche nicht, ohne etwas zu
   schreiben. Deshalb steht ueberall eine Kandidaten*liste* statt eines festen
   Namens, und deshalb ist jeder Mapper tolerant gegenueber fehlenden Feldern.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from app.sde.loader import first_of, localized

#: EVEs eigene Aktivitaets-IDs. Sie sind stabil und werden hier gebraucht, um
#: fuer jede Blueprint-Aktivitaet einen deterministischen Primaerschluessel zu
#: bilden -- ohne Rueckfrage an die Datenbank und damit ohne Round-Trip je Zeile.
ACTIVITY_IDS: dict[str, int] = {
    "manufacturing": 1,
    "research_time": 3,
    "research_material": 4,
    "copying": 5,
    "invention": 8,
    "reaction": 9,
}

#: Faktor fuer den zusammengesetzten Schluessel. 16 > groesste Aktivitaets-ID,
#: damit ``type_id * 16 + activity_id`` kollisionsfrei bleibt.
_ACTIVITY_STRIDE = 16


def blueprint_row_id(blueprint_type_id: int, activity: str) -> int:
    """Deterministischer Schluessel fuer eine Blueprint-Aktivitaet."""
    return blueprint_type_id * _ACTIVITY_STRIDE + ACTIVITY_IDS.get(activity, 0)


Row = tuple[str, dict[str, Any]]
Mapper = Callable[[dict[str, Any]], Iterator[Row]]


@dataclass(frozen=True, slots=True)
class Dataset:
    """Eine Export-Datei und was sie fuellt."""

    name: str
    #: Kandidaten fuer den Dateinamen im Export, in Reihenfolge der Praeferenz.
    filenames: tuple[str, ...]
    #: Tabellen, die dieses Dataset schreibt -- in Abhaengigkeitsreihenfolge.
    tables: tuple[str, ...]
    expand: Mapper
    #: Fehlt die Datei, ist das kein Fehler (etwa PI-Schemata in einem
    #: Teilexport). Fehlt eine mit ``required=True``, bricht der Import ab.
    required: bool = True
    description: str = field(default="")


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _key(row: dict[str, Any], *names: str) -> int | None:
    """Die ID einer Zeile.

    Der JSONL-Export legt sie in ``_key``; aeltere Formate benennen sie
    ausdruecklich (``typeID``, ``type_id``). Beides wird akzeptiert.
    """
    return _int(first_of(row, "_key", *names))


# ---------------------------------------------------------------------------
# Mapper
# ---------------------------------------------------------------------------


def map_category(row: dict[str, Any]) -> Iterator[Row]:
    category_id = _key(row, "categoryID", "category_id")
    if category_id is None:
        return
    yield (
        "sde_categories",
        {
            "category_id": category_id,
            "name": localized(first_of(row, "name", "categoryName")),
            "published": bool(first_of(row, "published") or False),
        },
    )


def map_group(row: dict[str, Any]) -> Iterator[Row]:
    group_id = _key(row, "groupID", "group_id")
    category_id = _int(first_of(row, "categoryID", "category_id"))
    if group_id is None or category_id is None:
        return
    yield (
        "sde_groups",
        {
            "group_id": group_id,
            "category_id": category_id,
            "name": localized(first_of(row, "name", "groupName")),
            "published": bool(first_of(row, "published") or False),
        },
    )


def map_type(row: dict[str, Any]) -> Iterator[Row]:
    type_id = _key(row, "typeID", "type_id")
    group_id = _int(first_of(row, "groupID", "group_id"))
    if type_id is None or group_id is None:
        return
    yield (
        "sde_types",
        {
            "type_id": type_id,
            "group_id": group_id,
            "name": localized(first_of(row, "name", "typeName")),
            "description": localized(first_of(row, "description")) or None,
            "volume": _float(first_of(row, "volume")),
            "packaged_volume": _float(first_of(row, "packagedVolume", "packaged_volume")),
            "mass": _float(first_of(row, "mass")),
            "portion_size": _int(first_of(row, "portionSize", "portion_size")) or 1,
            "market_group_id": _int(first_of(row, "marketGroupID", "market_group_id")),
            "published": bool(first_of(row, "published") or False),
        },
    )


def map_blueprint(row: dict[str, Any]) -> Iterator[Row]:
    """Faechert eine Blueprint-Zeile auf vier Tabellen auf.

    Der Export verschachtelt alle Aktivitaeten eines Blueprints in ein
    ``activities``-Objekt. Getrennt wird hier, nicht spaeter in der Engine:
    Manufacturing, Invention, Kopieren und Reaktionen haben unterschiedliche
    Formeln und gehoeren deshalb schon im Schema auseinander (Kapitel 8).
    """
    blueprint_type_id = _key(row, "blueprintTypeID", "blueprint_type_id")
    if blueprint_type_id is None:
        return
    activities = first_of(row, "activities") or {}
    if not isinstance(activities, dict):
        return
    max_runs = _int(first_of(row, "maxProductionLimit", "max_production_limit"))

    for activity, payload in activities.items():
        if not isinstance(payload, dict):
            continue
        row_id = blueprint_row_id(blueprint_type_id, activity)
        yield (
            "sde_blueprints",
            {
                "id": row_id,
                "blueprint_type_id": blueprint_type_id,
                "activity": activity,
                "time_seconds": _int(first_of(payload, "time")) or 0,
                "max_production_limit": max_runs,
            },
        )
        yield from _blueprint_children(row_id, payload)


def _blueprint_children(row_id: int, payload: dict[str, Any]) -> Iterator[Row]:
    for index, material in enumerate(_as_list(payload.get("materials"))):
        type_id = _int(first_of(material, "typeID", "type_id", "_key"))
        quantity = _int(first_of(material, "quantity"))
        if type_id is None or quantity is None:
            continue
        yield (
            "sde_blueprint_materials",
            {
                "id": row_id * 1000 + index,
                "blueprint_id": row_id,
                "type_id": type_id,
                "quantity": quantity,
            },
        )

    for index, product in enumerate(_as_list(payload.get("products"))):
        type_id = _int(first_of(product, "typeID", "type_id", "_key"))
        quantity = _int(first_of(product, "quantity"))
        if type_id is None or quantity is None:
            continue
        yield (
            "sde_blueprint_products",
            {
                "id": row_id * 1000 + index,
                "blueprint_id": row_id,
                "type_id": type_id,
                "quantity": quantity,
                "probability": _float(first_of(product, "probability")),
            },
        )

    for index, skill in enumerate(_as_list(payload.get("skills"))):
        type_id = _int(first_of(skill, "typeID", "type_id", "_key"))
        level = _int(first_of(skill, "level"))
        if type_id is None or level is None:
            continue
        yield (
            "sde_blueprint_skills",
            {
                "id": row_id * 1000 + index,
                "blueprint_id": row_id,
                "type_id": type_id,
                "level": level,
            },
        )


def _as_list(value: Any) -> list[dict[str, Any]]:
    """Nimmt Liste oder ID-indiziertes Objekt entgegen.

    Der Export verwendet beides -- Listen in den neueren Dateien, Objekte mit
    der Typ-ID als Schluessel in aelteren.
    """
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        merged: list[dict[str, Any]] = []
        for key, item in value.items():
            if isinstance(item, dict):
                merged.append({"typeID": _int(key), **item})
        return merged
    return []


def map_region(row: dict[str, Any]) -> Iterator[Row]:
    region_id = _key(row, "regionID", "region_id")
    if region_id is None:
        return
    yield (
        "sde_regions",
        {"region_id": region_id, "name": localized(first_of(row, "name", "regionName"))},
    )


def map_system(row: dict[str, Any]) -> Iterator[Row]:
    system_id = _key(row, "solarSystemID", "system_id")
    region_id = _int(first_of(row, "regionID", "region_id"))
    if system_id is None or region_id is None:
        return
    yield (
        "sde_systems",
        {
            "system_id": system_id,
            "region_id": region_id,
            "constellation_id": _int(first_of(row, "constellationID", "constellation_id")),
            "name": localized(first_of(row, "name", "solarSystemName")),
            "security_status": _float(first_of(row, "security", "securityStatus")),
        },
    )


def map_station(row: dict[str, Any]) -> Iterator[Row]:
    station_id = _key(row, "stationID", "station_id")
    system_id = _int(first_of(row, "solarSystemID", "system_id"))
    if station_id is None or system_id is None:
        return
    yield (
        "sde_stations",
        {
            "station_id": station_id,
            "system_id": system_id,
            "region_id": _int(first_of(row, "regionID", "region_id")),
            "name": localized(first_of(row, "name", "stationName")),
            "type_id": _int(first_of(row, "stationTypeID", "type_id")),
        },
    )


def map_planet(row: dict[str, Any]) -> Iterator[Row]:
    planet_id = _key(row, "planetID", "planet_id")
    system_id = _int(first_of(row, "solarSystemID", "system_id"))
    if planet_id is None or system_id is None:
        return
    yield (
        "sde_planets",
        {
            "planet_id": planet_id,
            "system_id": system_id,
            "name": localized(first_of(row, "name", "planetName")),
            "type_id": _int(first_of(row, "typeID", "type_id")),
        },
    )


def map_planet_schematic(row: dict[str, Any]) -> Iterator[Row]:
    schematic_id = _key(row, "schematicID", "schematic_id")
    if schematic_id is None:
        return
    yield (
        "sde_planet_schematics",
        {
            "schematic_id": schematic_id,
            "name": localized(first_of(row, "name", "schematicName")),
            "cycle_time_seconds": _int(first_of(row, "cycleTime", "cycle_time")) or 0,
        },
    )
    for index, entry in enumerate(_as_list(first_of(row, "types"))):
        type_id = _int(first_of(entry, "typeID", "type_id"))
        quantity = _int(first_of(entry, "quantity"))
        if type_id is None or quantity is None:
            continue
        yield (
            "sde_planet_schematic_types",
            {
                "id": schematic_id * 1000 + index,
                "schematic_id": schematic_id,
                "type_id": type_id,
                "quantity": quantity,
                "is_input": bool(first_of(entry, "isInput", "is_input")),
            },
        )


# ---------------------------------------------------------------------------
# Der Katalog. Reihenfolge ist Abhaengigkeitsreihenfolge.
# ---------------------------------------------------------------------------
DATASETS: tuple[Dataset, ...] = (
    Dataset(
        "categories",
        ("categories.jsonl", "invCategories.jsonl", "categoryIDs.jsonl"),
        ("sde_categories",),
        map_category,
        description="Item-Kategorien",
    ),
    Dataset(
        "groups",
        ("groups.jsonl", "invGroups.jsonl", "groupIDs.jsonl"),
        ("sde_groups",),
        map_group,
        description="Item-Gruppen",
    ),
    Dataset(
        "types",
        ("types.jsonl", "invTypes.jsonl", "typeIDs.jsonl"),
        ("sde_types",),
        map_type,
        description="Item-Typen",
    ),
    Dataset(
        "blueprints",
        ("blueprints.jsonl", "industryBlueprints.jsonl"),
        (
            "sde_blueprints",
            "sde_blueprint_materials",
            "sde_blueprint_products",
            "sde_blueprint_skills",
        ),
        map_blueprint,
        description="Blueprints je Aktivitaet, mit Materialien, Produkten und Skills",
    ),
    Dataset(
        "regions",
        ("regions.jsonl", "mapRegions.jsonl"),
        ("sde_regions",),
        map_region,
        description="Regionen",
    ),
    Dataset(
        "systems",
        ("solarSystems.jsonl", "mapSolarSystems.jsonl", "systems.jsonl"),
        ("sde_systems",),
        map_system,
        description="Sonnensysteme",
    ),
    Dataset(
        "stations",
        ("stations.jsonl", "npcStations.jsonl", "staStations.jsonl"),
        ("sde_stations",),
        map_station,
        description="NPC-Stationen",
    ),
    Dataset(
        "planets",
        ("planets.jsonl", "mapPlanets.jsonl"),
        ("sde_planets",),
        map_planet,
        required=False,
        description="Planeten (fuer PI)",
    ),
    Dataset(
        "planet_schematics",
        ("planetSchematics.jsonl", "planetSchematic.jsonl"),
        ("sde_planet_schematics", "sde_planet_schematic_types"),
        map_planet_schematic,
        required=False,
        description="PI-Schemata",
    ),
)

DATASETS_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in DATASETS}

#: Loeschreihenfolge: Kinder vor Eltern. Wird beim Reimport gebraucht.
ALL_TABLES_IN_ORDER: tuple[str, ...] = tuple(
    table for dataset in DATASETS for table in dataset.tables
)
