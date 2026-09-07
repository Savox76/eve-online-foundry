"""SQLAlchemy-Modelle.

SQLite kennt keine Schemata, deshalb trennen Praefixe im Tabellennamen, was in
Postgres eigene Schemata waeren (Kapitel 3 und 7):

``sde_``
    Vollstaendig aus dem Static Data Export erzeugt. Jederzeit wegwerfbar und
    neu importierbar.
``esi_``
    Gespiegelte Spieldaten. Nachladbar, aber teuer -- ein voller Resync kostet
    Stunden Quotenbudget.
``app_``
    Eigene Daten. Nur diese sind unersetzlich und gehoeren ins Backup.

**Die Entwurfsregel dahinter:** Ein SDE-Reimport oder ein kompletter
ESI-Resync darf niemals Daten aus ``app_`` beruehren. Wenn dieser Satz im
Schema stimmt, ist das Projekt gegen die haeufigste Katastrophe dieser
Werkzeuggattung immun.

Nebeneffekt der Praefixe: dieselben Modelle laufen unveraendert auf
PostgreSQL, falls doch ein Corp-Server dazukommt.
"""

from app.models.app_data import AppSetting
from app.models.base import Base
from app.models.esi import (
    Asset,
    AssetChange,
    Character,
    CharacterRole,
    CharacterToken,
    HttpCacheEntry,
    Structure,
    SyncRun,
)
from app.models.sde import (
    SdeBlueprint,
    SdeBlueprintMaterial,
    SdeBlueprintProduct,
    SdeBlueprintSkill,
    SdeBuild,
    SdeCategory,
    SdeGroup,
    SdePlanet,
    SdePlanetSchematic,
    SdePlanetSchematicType,
    SdeRegion,
    SdeStation,
    SdeSystem,
    SdeType,
)

__all__ = [
    "AppSetting",
    "Asset",
    "AssetChange",
    "Base",
    "Character",
    "CharacterRole",
    "CharacterToken",
    "HttpCacheEntry",
    "SdeBlueprint",
    "SdeBlueprintMaterial",
    "SdeBlueprintProduct",
    "SdeBlueprintSkill",
    "SdeBuild",
    "SdeCategory",
    "SdeGroup",
    "SdePlanet",
    "SdePlanetSchematic",
    "SdePlanetSchematicType",
    "SdeRegion",
    "SdeStation",
    "SdeSystem",
    "SdeType",
    "Structure",
    "SyncRun",
]
