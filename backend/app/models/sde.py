"""Static-Data-Export-Tabellen (Praefix ``sde_``).

Vollstaendig aus dem Export erzeugt und jederzeit wegwerfbar. Es gibt hier
absichtlich **keine** Fremdschluessel auf ``esi_``- oder ``app_``-Tabellen:
ein Reimport soll ``DELETE FROM sde_*`` sein duerfen, ohne irgendwo anders
etwas mitzureissen.

Ein Import laeuft versioniert: der alte Datensatz bleibt aktiv, bis der neue
vollstaendig ist (Kapitel 5 und 18). ``sde_builds`` haelt fest, welcher Stand
gerade gilt.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class SdeBuild(Base):
    """Welcher Export-Stand liegt in der Datenbank.

    ``completed_at`` ist der Schalter: solange er ``NULL`` ist, laeuft der
    Import noch und der Datensatz gilt als unvollstaendig.
    """

    __tablename__ = "sde_builds"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Build-Nummer bzw. Kennung des Exports, wie CCP sie ausliefert.
    build: Mapped[str] = mapped_column(String(64), unique=True)
    source_url: Mapped[str] = mapped_column(Text, default="")
    #: Pruefsumme des Archivs -- beantwortet "habe ich genau diesen schon?"
    checksum: Mapped[str | None] = mapped_column(String(128), default=None)
    started_at: Mapped[dt.datetime] = mapped_column(default=utcnow)
    completed_at: Mapped[dt.datetime | None] = mapped_column(default=None)
    row_counts: Mapped[str] = mapped_column(Text, default="{}")
    is_active: Mapped[bool] = mapped_column(default=False)


class SdeCategory(Base):
    __tablename__ = "sde_categories"

    category_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    published: Mapped[bool] = mapped_column(default=True)


class SdeGroup(Base):
    __tablename__ = "sde_groups"

    group_id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("sde_categories.category_id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), index=True)
    published: Mapped[bool] = mapped_column(default=True)


class SdeType(Base):
    """Ein Item-Typ. Die zentrale Tabelle des gesamten Werkzeugs."""

    __tablename__ = "sde_types"

    type_id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("sde_groups.group_id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(256), index=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    #: m3 je Einheit -- fuer "passt das in einen Epithal?" (Kapitel 14).
    volume: Mapped[float | None] = mapped_column(default=None)
    packaged_volume: Mapped[float | None] = mapped_column(default=None)
    mass: Mapped[float | None] = mapped_column(default=None)
    portion_size: Mapped[int] = mapped_column(default=1)
    market_group_id: Mapped[int | None] = mapped_column(default=None, index=True)
    published: Mapped[bool] = mapped_column(default=True, index=True)

    __table_args__ = (Index("ix_sde_types_published_name", "published", "name"),)


class SdeBlueprint(Base):
    """Blueprint-Aktivitaet.

    Eine Zeile je Blueprint **und Aktivitaet** -- ein Blueprint kann
    ``manufacturing``, ``copying``, ``invention``, ``research_material`` und
    ``research_time`` zugleich haben, mit jeweils eigener Zeit und eigenen
    Materialien. Die Engine wird von Anfang an nach Aktivitaet getrennt
    gebaut, statt Sonderfaelle in eine Funktion zu pressen (Kapitel 8).
    """

    __tablename__ = "sde_blueprints"

    id: Mapped[int] = mapped_column(primary_key=True)
    blueprint_type_id: Mapped[int] = mapped_column(index=True)
    activity: Mapped[str] = mapped_column(String(32), index=True)
    #: Sekunden je Lauf, vor allen Skill- und Strukturboni.
    time_seconds: Mapped[int] = mapped_column(Integer, default=0)
    max_production_limit: Mapped[int | None] = mapped_column(default=None)

    __table_args__ = (
        Index("ix_sde_blueprints_type_activity", "blueprint_type_id", "activity", unique=True),
    )


class SdeBlueprintMaterial(Base):
    """Was eine Aktivitaet je Lauf verbraucht.

    ``quantity`` ist die **Grundmenge ohne ME-Abzug**. Das ist wichtig: der
    EIV fuer die Job-Kosten rechnet mit genau dieser unveraenderten Menge,
    waehrend der Materialbedarf den ME-Abzug bekommt (Kapitel 8).
    """

    __tablename__ = "sde_blueprint_materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    blueprint_id: Mapped[int] = mapped_column(
        ForeignKey("sde_blueprints.id", ondelete="CASCADE"), index=True
    )
    type_id: Mapped[int] = mapped_column(index=True)
    quantity: Mapped[int] = mapped_column(Integer)


class SdeBlueprintProduct(Base):
    """Was dabei herauskommt.

    ``probability`` ist bei Invention die Grundwahrscheinlichkeit aus dem SDE
    -- Skills, Decryptor und Strukturboni kommen erst in der Rechnung dazu.
    """

    __tablename__ = "sde_blueprint_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    blueprint_id: Mapped[int] = mapped_column(
        ForeignKey("sde_blueprints.id", ondelete="CASCADE"), index=True
    )
    type_id: Mapped[int] = mapped_column(index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    probability: Mapped[float | None] = mapped_column(default=None)


class SdeBlueprintSkill(Base):
    """Welche Skills die Aktivitaet ueberhaupt erlaubt."""

    __tablename__ = "sde_blueprint_skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    blueprint_id: Mapped[int] = mapped_column(
        ForeignKey("sde_blueprints.id", ondelete="CASCADE"), index=True
    )
    type_id: Mapped[int] = mapped_column(index=True)
    level: Mapped[int] = mapped_column(Integer)


class SdeRegion(Base):
    __tablename__ = "sde_regions"

    region_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)


class SdeSystem(Base):
    __tablename__ = "sde_systems"

    system_id: Mapped[int] = mapped_column(primary_key=True)
    region_id: Mapped[int] = mapped_column(
        ForeignKey("sde_regions.region_id", ondelete="CASCADE"), index=True
    )
    constellation_id: Mapped[int | None] = mapped_column(default=None, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    #: Der gerundete Wert, den das Spiel anzeigt. Der Security-Multiplikator
    #: der Strukturboni haengt daran (Null und WH hoeher als Highsec).
    security_status: Mapped[float | None] = mapped_column(default=None)


class SdeStation(Base):
    """NPC-Stationen. Spielerstrukturen kommen aus ESI, nicht aus dem SDE."""

    __tablename__ = "sde_stations"

    station_id: Mapped[int] = mapped_column(primary_key=True)
    system_id: Mapped[int] = mapped_column(
        ForeignKey("sde_systems.system_id", ondelete="CASCADE"), index=True
    )
    region_id: Mapped[int | None] = mapped_column(default=None, index=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    type_id: Mapped[int | None] = mapped_column(default=None)


class SdePlanet(Base):
    __tablename__ = "sde_planets"

    planet_id: Mapped[int] = mapped_column(primary_key=True)
    system_id: Mapped[int] = mapped_column(
        ForeignKey("sde_systems.system_id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), index=True)
    #: Barren, Gas, Lava ... bestimmt, welche P0-Rohstoffe abbaubar sind.
    type_id: Mapped[int | None] = mapped_column(default=None, index=True)


class SdePlanetSchematic(Base):
    """PI-Schema: was eine Fabrik-Pin in welcher Zeit herstellt."""

    __tablename__ = "sde_planet_schematics"

    schematic_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    cycle_time_seconds: Mapped[int] = mapped_column(Integer, default=0)


class SdePlanetSchematicType(Base):
    """Ein- und Ausgang eines Schemas."""

    __tablename__ = "sde_planet_schematic_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    schematic_id: Mapped[int] = mapped_column(
        ForeignKey("sde_planet_schematics.schematic_id", ondelete="CASCADE"), index=True
    )
    type_id: Mapped[int] = mapped_column(index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    is_input: Mapped[bool] = mapped_column(default=True)
