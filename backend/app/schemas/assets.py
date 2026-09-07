"""Antwortmodelle fuer Bestaende."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class AssetRow(BaseModel):
    """Eine Zeile der Bestandstabelle."""

    item_id: int
    type_id: int
    type_name: str = ""
    group_name: str = ""
    quantity: int
    volume: float | None = None
    #: Menge mal Volumen je Einheit — die Frage "passt das in einen Epithal?".
    total_volume: float | None = None

    location_id: int
    location_type: str
    location_flag: str = ""
    root_location_id: int | None = None
    #: Aufgeloest, sonst der Rueckfall "Unbekannte Struktur #1035…".
    location_name: str = ""
    #: Wie tief im Container-Baum. 0 = liegt direkt an einer Location.
    depth: int = 0
    container_name: str | None = None
    is_singleton: bool = False
    is_blueprint_copy: bool = False
    fetched_at: dt.datetime


class AssetListResponse(BaseModel):
    rows: list[AssetRow] = Field(default_factory=list)
    total: int = 0
    #: Wie viele Zeilen keinen Wurzelort haben. Sichtbar gemacht, weil eine
    #: unaufgeloeste Kette jedes Aggregat darueber verfaelschen wuerde.
    unresolved: int = 0
    #: Datenstand. In einem Werkzeug mit einstuendigem Cache eine Kernangabe.
    fetched_at: dt.datetime | None = None


class AssetChangeRow(BaseModel):
    id: int
    kind: str = Field(examples=["added", "removed", "quantity", "moved"])
    item_id: int
    type_id: int
    type_name: str = ""
    quantity_before: int | None = None
    quantity_after: int | None = None
    #: Differenz, wo eine sinnvoll ist. Negativ heisst: weniger geworden.
    delta: int | None = None
    location_id: int | None = None
    location_name: str = ""
    location_before: int | None = None
    observed_at: dt.datetime


class AssetChangeListResponse(BaseModel):
    rows: list[AssetChangeRow] = Field(default_factory=list)
    total: int = 0


class LocationSummary(BaseModel):
    """Ein Wurzelort mit dem, was dort liegt."""

    location_id: int | None
    name: str
    location_type: str = ""
    items: int = 0
    stacks: int = 0


class SyncResultResponse(BaseModel):
    character_id: int
    unchanged: bool = False
    fetched: int = 0
    added: int = 0
    removed: int = 0
    quantity_changes: int = 0
    moved: int = 0
    named: int = 0
    unresolved: int = 0
