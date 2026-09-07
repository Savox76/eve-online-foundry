"""Gespiegelte ESI-Daten (Praefix ``esi_``).

Phase 0 legt hier nur an, was die Sync-Engine selbst braucht: den HTTP-Cache
und das Audit-Log. Charaktere, Bestaende, Blueprints und Jobs kommen in Phase
1 und 2 dazu -- inklusive ``esi_asset_changes``, das laut Kapitel 7 von Anfang
an mitgeschrieben werden muss, weil es sich nicht rueckwirkend nachholen
laesst.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Index, Integer, String, Text
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
