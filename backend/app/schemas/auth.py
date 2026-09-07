"""Antwortmodelle rund um Charaktere und Anmeldung.

**Was hier nie auftaucht: ein Token.** Weder Access noch Refresh. Die
Oberflaeche braucht keinen -- sie spricht ausschliesslich mit dem eigenen
Backend, und das haelt die Tokens.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class ScopeTierInfo(BaseModel):
    """Ein Scope-Paket, wie es die Oberflaeche zur Auswahl anbietet."""

    tier: str
    label: str
    description: str
    scopes: list[str]
    #: In-Game-Rolle je Scope, falls eine noetig ist.
    required_roles: dict[str, str] = Field(default_factory=dict)


class LoginStartRequest(BaseModel):
    """Welche Pakete angefragt werden sollen.

    Gestaffelt statt auf einen Schlag: ein erster Login, der alles anfragt,
    erzeugt ein unlesbares Consent-Fenster (Kapitel 4).
    """

    tiers: list[str] = Field(default_factory=lambda: ["base"])


class LoginStartResponse(BaseModel):
    id: str
    #: Im **Systembrowser** oeffnen, nicht in einem eingebetteten Fenster --
    #: der Nutzer soll die echte Adresszeile von CCP sehen.
    url: str


class LoginStatusResponse(BaseModel):
    id: str
    state: str = Field(examples=["waiting", "done", "failed"])
    character_id: int | None = None
    character_name: str = ""
    error: str | None = None
    started_at: dt.datetime


class CharacterInfo(BaseModel):
    character_id: int
    name: str
    corporation_id: int | None = None
    alliance_id: int | None = None
    status: str
    status_reason: str | None = None
    connected_at: dt.datetime
    last_seen_at: dt.datetime | None = None

    scopes: list[str] = Field(default_factory=list)
    #: ``keyring`` oder ``encrypted-file`` — gehoert sichtbar gemacht, damit
    #: niemand die Rueckfallebene fuer den Normalfall haelt.
    token_storage: str = ""
    access_expires_at: dt.datetime | None = None
    last_refresh_at: dt.datetime | None = None

    roles: list[str] = Field(default_factory=list)
    #: Erteilte Corp-Scopes, denen die passende In-Game-Rolle fehlt. Ohne sie
    #: antwortet die Route mit 403 — als leere Liste anzuzeigen waere eine
    #: stille Luege (Kapitel 18).
    scopes_without_role: dict[str, str] = Field(default_factory=dict)


class CharacterListResponse(BaseModel):
    characters: list[CharacterInfo] = Field(default_factory=list)
    token_storage: str = ""
