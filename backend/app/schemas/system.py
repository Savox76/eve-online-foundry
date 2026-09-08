"""Antwortmodelle fuer Gesundheit und Betriebszustand."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Worauf die Tauri-Schale beim Start wartet.

    Bewusst ohne Sitzungsgeheimnis erreichbar und bewusst inhaltsarm: die
    Schale muss wissen, ob der Sidecar da ist, sonst nichts.
    """

    status: str = Field(examples=["ok"])
    version: str
    database_revision: str | None = Field(
        default=None, description="Alembic-Revision, auf der die Datenbank steht"
    )


class SdeBuildInfo(BaseModel):
    """Welcher Static-Data-Stand gerade gilt."""

    build: str
    source_url: str = ""
    completed_at: str | None = None
    row_counts: dict[str, int] = Field(default_factory=dict)


class RateLimitGroupInfo(BaseModel):
    limit: int
    remaining: float
    window_seconds: float
    blocked_seconds_left: float


class RateLimitInfo(BaseModel):
    """Der Verbrauch, sichtbar gemacht.

    Ohne diese Ansicht ist ein Quotenproblem nicht diagnostizierbar -- man
    sieht nur, dass "nichts mehr geht" (Kapitel 6 und 18).
    """

    error_remain: int | None = Field(
        default=None, description="Restliches ESI-Fehlerbudget; None vor dem ersten Abruf"
    )
    breaker_seconds_left: float = Field(
        default=0.0, description="Wie lange der Circuit Breaker noch pausiert; 0 = offen"
    )
    groups: dict[str, RateLimitGroupInfo] = Field(default_factory=dict)


class CompatibilityInfo(BaseModel):
    """Stand des Kompatibilitaetsdatums."""

    date: str
    age_days: int
    guaranteed_days: int
    #: ``ok``, ``warn`` (Anheben einplanen) oder ``expired``.
    state: str


class SyncRunInfo(BaseModel):
    id: int
    route: str
    owner_type: str
    owner_id: int | None = None
    started_at: dt.datetime
    duration_ms: int | None = None
    status_code: int | None = None
    unchanged: bool = False
    tokens_spent: int = 0
    rows_written: int = 0
    error: str | None = None


class StatusResponse(BaseModel):
    """Alles, was der Admin-Bereich zum Betriebszustand zeigt."""

    version: str
    database_revision: str | None = None
    database_path: str
    data_dir: str = Field(description="Ordner mit Datenbank, Sicherungen und Zwischenspeicher")
    portable: bool = Field(
        default=False,
        description="Ob die Daten neben der Anwendung liegen statt in der Systemablage",
    )
    sde: SdeBuildInfo | None = None
    compatibility: CompatibilityInfo
    rate_limit: RateLimitInfo
    recent_syncs: list[SyncRunInfo] = Field(default_factory=list)
