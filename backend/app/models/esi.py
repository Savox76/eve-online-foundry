"""Gespiegelte ESI-Daten (Praefix ``esi_``).

Nachladbar, aber teuer: ein voller Resync kostet Stunden Quotenbudget. Die
einzige Ausnahme von "nachladbar" steht weiter unten -- ``AssetChange``.

**Was hier bewusst NICHT steht: der Refresh Token.** Der liegt im
Schluesselbund des Systems (siehe ``esi/tokens.py``). In der Datenbank steht
nur, was zu ihm bekannt ist: welche Scopes er traegt, wann er zuletzt erneuert
wurde und ob er noch gilt. Eine Datenbankdatei wandert in Backups und auf
USB-Sticks; ein Refresh Token hat dort nichts verloren.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class HttpCacheEntry(Base):
    """ETag und Ablaufzeitpunkt je Abrufschluessel.

    Caching ist bei ESI Pflicht (Kapitel 6): ``Expires`` verhindert den Abruf
    ganz, ``ETag`` macht ihn billig. Die Tabelle ist reiner Zwischenspeicher --
    sie zu leeren kostet nur Quotenbudget, keine Daten.
    """

    __tablename__ = "esi_http_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    etag: Mapped[str | None] = mapped_column(String(256), default=None)
    expires_at: Mapped[dt.datetime | None] = mapped_column(default=None)
    updated_at: Mapped[dt.datetime] = mapped_column(default=utcnow)


class SyncRun(Base):
    """Audit-Log je Abruf.

    Ohne dieses Log ist ein Quotenproblem nicht diagnostizierbar (Kapitel 6).
    Protokolliert werden Route, Entitaet, Statuscode, ETag, verbrauchte Tokens
    und Dauer.

    **Was hier niemals landet:** Mailinhalte. Die Mail-Tabellen sind die
    einzigen im ganzen System mit dieser Sonderregel (Kapitel 11).
    """

    __tablename__ = "esi_sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    route: Mapped[str] = mapped_column(String(128), index=True)
    #: ``character``, ``corporation`` oder ``public``.
    owner_type: Mapped[str] = mapped_column(String(32), default="public", index=True)
    owner_id: Mapped[int | None] = mapped_column(default=None, index=True)
    #: Bleibt im Modell, damit ein spaeterer Corp-Server andocken kann, statt
    #: einen Umbau zu erzwingen (Kapitel 7).
    corporation_id: Mapped[int | None] = mapped_column(default=None, index=True)

    started_at: Mapped[dt.datetime] = mapped_column(default=utcnow, index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    status_code: Mapped[int | None] = mapped_column(Integer, default=None)
    #: 304 oder frischer Cache -- der haeufigste Gutfall im Dauerbetrieb.
    unchanged: Mapped[bool] = mapped_column(default=False)
    etag: Mapped[str | None] = mapped_column(String(256), default=None)
    tokens_spent: Mapped[int] = mapped_column(Integer, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, default=0)
    error_limit_remain: Mapped[int | None] = mapped_column(Integer, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    __table_args__ = (Index("ix_esi_sync_runs_route_started", "route", "started_at"),)


class Character(Base):
    """Ein verbundener Charakter."""

    __tablename__ = "esi_characters"

    character_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    corporation_id: Mapped[int | None] = mapped_column(default=None, index=True)
    alliance_id: Mapped[int | None] = mapped_column(default=None, index=True)

    #: Aendert sich beim Charakter-Transfer. Weicht der Claim beim naechsten
    #: Login ab, wurde der Charakter verkauft -- dann sind alle Tokens sofort
    #: zu verwerfen, sonst zeigt Foundry fremde Assets an (Kapitel 4).
    owner_hash: Mapped[str] = mapped_column(String(128), default="")

    connected_at: Mapped[dt.datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(default=None)

    #: ``ok`` oder ``needs_reauth``. Im zweiten Fall steht in ``status_reason``,
    #: warum -- das gehoert in die Oberflaeche, nicht in ein Log.
    status: Mapped[str] = mapped_column(String(32), default="ok", index=True)
    status_reason: Mapped[str | None] = mapped_column(Text, default=None)


class CharacterToken(Base):
    """Was ueber den Refresh Token eines Charakters bekannt ist -- nicht der Token selbst."""

    __tablename__ = "esi_character_tokens"

    character_id: Mapped[int] = mapped_column(
        ForeignKey("esi_characters.character_id", ondelete="CASCADE"), primary_key=True
    )
    #: Leerzeichengetrennt, wie im ``scp``-Claim. Sagt, welche Routen dieser
    #: Token ueberhaupt bedienen kann.
    scopes: Mapped[str] = mapped_column(Text, default="")
    #: Wo der Refresh Token liegt: ``keyring`` oder ``encrypted-file``.
    storage: Mapped[str] = mapped_column(String(32), default="keyring")
    access_expires_at: Mapped[dt.datetime | None] = mapped_column(default=None)
    last_refresh_at: Mapped[dt.datetime | None] = mapped_column(default=None)
    #: Zaehlt aufeinanderfolgende Fehlversuche. Ein einzelner Ausfall des
    #: Login-Dienstes soll den Charakter nicht abmelden.
    refresh_failures: Mapped[int] = mapped_column(Integer, default=0)

    def scope_list(self) -> tuple[str, ...]:
        return tuple(scope for scope in self.scopes.split(" ") if scope)


class CharacterRole(Base):
    """In-Game-Rollen eines Charakters in seiner Corp.

    Ohne die passende Rolle antwortet die zugehoerige Corp-Route mit 403, egal
    wie sauber der Scope erteilt wurde. Verliert man die Rolle, versiegt der
    Corp-Sync -- und das gehoert sichtbar gemeldet, nicht als leere Liste
    angezeigt (Kapitel 18).
    """

    __tablename__ = "esi_character_roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("esi_characters.character_id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(64))
    #: ``roles``, ``roles_at_hq``, ``roles_at_base`` oder ``roles_at_other``.
    scope: Mapped[str] = mapped_column(String(32), default="roles")
    fetched_at: Mapped[dt.datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        Index("ix_esi_character_roles_char_role", "character_id", "scope", "role", unique=True),
    )


class Structure(Base):
    """Spielerstrukturen. NPC-Stationen stehen im SDE.

    ``access_denied`` ist der Grund, warum es diese Tabelle gibt: eine Struktur
    ohne Docking-Zugriff antwortet mit 403. Das wird hier vermerkt, damit sie
    nicht bei jedem Lauf erneut abgefragt wird und das Fehlerbudget kostet.
    """

    __tablename__ = "esi_structures"

    structure_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    system_id: Mapped[int | None] = mapped_column(default=None, index=True)
    type_id: Mapped[int | None] = mapped_column(default=None)
    owner_corporation_id: Mapped[int | None] = mapped_column(default=None)
    access_denied: Mapped[bool] = mapped_column(default=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(default=utcnow)


class Asset(Base):
    """Der aktuelle Bestand.

    ``location_id`` ist der unterschaetzteste Teil des ganzen Werkzeugs: er
    kann eine NPC-Station sein, eine Spielerstruktur, ein Sonnensystem -- oder
    die ``item_id`` eines anderen Assets, also ein Container oder ein Schiff.
    ``root_location_id`` ist das Ergebnis, nachdem die Elternkette bis zu einer
    echten Location hochgelaufen wurde (Kapitel 5).
    """

    __tablename__ = "esi_assets"

    item_id: Mapped[int] = mapped_column(primary_key=True)
    owner_type: Mapped[str] = mapped_column(String(32), default="character", index=True)
    owner_id: Mapped[int] = mapped_column(index=True)
    corporation_id: Mapped[int | None] = mapped_column(default=None, index=True)

    type_id: Mapped[int] = mapped_column(index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    location_id: Mapped[int] = mapped_column(index=True)
    #: ``Hangar``, ``CorpSAG1``…``CorpSAG7``, ``Cargo``, ``AssetSafety`` …
    location_flag: Mapped[str] = mapped_column(String(64), default="", index=True)
    #: ``station``, ``structure``, ``solar_system``, ``item``, ``other``
    location_type: Mapped[str] = mapped_column(String(32), default="other")
    is_singleton: Mapped[bool] = mapped_column(default=False)
    is_blueprint_copy: Mapped[bool] = mapped_column(default=False)

    #: Aufgeloest, ``NULL`` solange die Kette nicht aufgeht.
    root_location_id: Mapped[int | None] = mapped_column(default=None, index=True)
    #: Wie tief im Container-Baum. 0 = liegt direkt an einer Location.
    depth: Mapped[int] = mapped_column(Integer, default=0)
    #: Name eines benannten Containers oder Schiffs, falls vergeben.
    name: Mapped[str | None] = mapped_column(String(256), default=None)

    fetched_at: Mapped[dt.datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index("ix_esi_assets_owner_type_id", "owner_type", "owner_id", "type_id"),
        Index("ix_esi_assets_root_type", "root_location_id", "type_id"),
    )


class AssetChange(Base):
    """Was sich seit dem letzten Sync geaendert hat.

    **Diese Tabelle ist der Grund, warum die Entscheidung frueh faellt.** Der
    Asset-Sync laeuft ohnehin; wer dabei den alten Stand einfach ueberschreibt,
    wirft eine Historie weg, die er geschenkt bekaeme -- und die sich spaeter
    *nicht* rekonstruieren laesst (Kapitel 7).

    ``esi_assets`` bleibt der aktuelle Stand fuer schnelle Abfragen, diese
    Tabelle waechst langsam und beantwortet trotzdem: was hat sich seit gestern
    veraendert, wie viel Material hat ein Projekt tatsaechlich verbraucht, und
    wo sind die 2000 Morphite geblieben.

    Ein Delta allein sagt nur, dass etwas weg ist. Erst der Abgleich mit den
    Industrie-Jobs desselben Zeitraums macht daraus eine Aussage -- deshalb
    steht hier ``job_id``, sobald Phase 3 die Jobs mitbringt.
    """

    __tablename__ = "esi_asset_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_type: Mapped[str] = mapped_column(String(32), default="character", index=True)
    owner_id: Mapped[int] = mapped_column(index=True)
    corporation_id: Mapped[int | None] = mapped_column(default=None, index=True)

    item_id: Mapped[int] = mapped_column(index=True)
    type_id: Mapped[int] = mapped_column(index=True)
    location_id: Mapped[int | None] = mapped_column(default=None)
    root_location_id: Mapped[int | None] = mapped_column(default=None)

    #: ``added``, ``removed``, ``quantity``, ``moved``
    kind: Mapped[str] = mapped_column(String(16), index=True)
    quantity_before: Mapped[int | None] = mapped_column(Integer, default=None)
    quantity_after: Mapped[int | None] = mapped_column(Integer, default=None)
    location_before: Mapped[int | None] = mapped_column(default=None)

    #: Fuer den Abgleich mit den Industrie-Jobs, ab Phase 3.
    job_id: Mapped[int | None] = mapped_column(default=None, index=True)
    observed_at: Mapped[dt.datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index("ix_esi_asset_changes_owner_observed", "owner_type", "owner_id", "observed_at"),
    )
