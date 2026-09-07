"""ESI-Scopes, gestaffelt statt auf einen Schlag.

Ein erster Login, der alles anfragt, erzeugt ein unlesbares Consent-Fenster.
Deshalb Pakete: das Basispaket beim Verbinden eines Charakters, alles weitere
bewusst und einzeln nachgefordert (Kapitel 4).

Die Scope-Strings sind der Stand der offiziellen Dokumentation vom September
2026 und gehoeren vor dem Bau gegen ``esi.evetech.net/meta/openapi.json``
geprueft -- das ist die einzige verbindliche Quelle.
"""

from __future__ import annotations

from enum import StrEnum


class ScopeTier(StrEnum):
    """Wann ein Scope angefragt wird."""

    BASE = "base"
    FITTINGS = "fittings"
    COMFORT = "comfort"
    MAIL = "mail"
    PLANETS = "planets"
    CORP = "corp"
    OPTIONAL = "optional"


#: Ohne diese sieben Scopes ist ein Charakter fuer Foundry nicht nutzbar.
BASE_SCOPES: tuple[str, ...] = (
    "publicData",
    "esi-assets.read_assets.v1",
    "esi-characters.read_blueprints.v1",
    "esi-industry.read_character_jobs.v1",
    "esi-skills.read_skills.v1",
    "esi-universe.read_structures.v1",
    "esi-characters.read_corporation_roles.v1",
)

FITTING_SCOPES: tuple[str, ...] = ("esi-fittings.read_fittings.v1",)

#: Ingame-Fernsteuerung. Nur als unmittelbare Folge eines Klicks aufrufen --
#: siehe die Bauregel in ``docs/esi-notes.md``.
COMFORT_SCOPES: tuple[str, ...] = (
    "esi-ui.open_window.v1",
    "esi-ui.write_waypoint.v1",
)

#: Optional und je Charakter. Wer sie nicht erteilt, verliert keine andere
#: Funktion. Mails sind ausserdem die einzigen Daten, die nie in Logs oder
#: Fehlermeldungen auftauchen duerfen.
MAIL_SCOPES: tuple[str, ...] = (
    "esi-mail.read_mail.v1",
    "esi-mail.send_mail.v1",
    "esi-mail.organize_mail.v1",
)

PLANET_SCOPES: tuple[str, ...] = ("esi-planets.manage_planets.v1",)

#: Brauchen zusaetzlich die passende In-Game-Rolle. Fehlt sie, antwortet ESI
#: mit 403 -- das gehoert sichtbar gemeldet, nicht als leere Liste angezeigt.
CORP_SCOPES: tuple[str, ...] = (
    "esi-assets.read_corporation_assets.v1",
    "esi-corporations.read_blueprints.v1",
    "esi-corporations.read_divisions.v1",
    "esi-industry.read_corporation_jobs.v1",
    "esi-corporations.read_structures.v1",
    "esi-contracts.read_corporation_contracts.v1",
    "esi-markets.read_corporation_orders.v1",
    "esi-planets.read_customs_offices.v1",
)

OPTIONAL_SCOPES: tuple[str, ...] = ("esi-markets.structure_markets.v1",)

SCOPES_BY_TIER: dict[ScopeTier, tuple[str, ...]] = {
    ScopeTier.BASE: BASE_SCOPES,
    ScopeTier.FITTINGS: FITTING_SCOPES,
    ScopeTier.COMFORT: COMFORT_SCOPES,
    ScopeTier.MAIL: MAIL_SCOPES,
    ScopeTier.PLANETS: PLANET_SCOPES,
    ScopeTier.CORP: CORP_SCOPES,
    ScopeTier.OPTIONAL: OPTIONAL_SCOPES,
}

ALL_SCOPES: frozenset[str] = frozenset(
    scope for scopes in SCOPES_BY_TIER.values() for scope in scopes
)

#: In-Game-Rolle je Corp-Scope. Ohne sie antwortet die Route mit 403, egal wie
#: sauber der Scope erteilt wurde.
REQUIRED_CORP_ROLE: dict[str, str] = {
    "esi-assets.read_corporation_assets.v1": "Director",
    "esi-corporations.read_blueprints.v1": "Director",
    "esi-corporations.read_divisions.v1": "Director",
    "esi-industry.read_corporation_jobs.v1": "Factory_Manager",
    "esi-corporations.read_structures.v1": "Station_Manager",
    "esi-planets.read_customs_offices.v1": "Director",
}


def scopes_for(*tiers: ScopeTier) -> tuple[str, ...]:
    """Scope-Liste fuer eine Auswahl von Paketen, ohne Dubletten."""
    seen: dict[str, None] = {}
    for tier in tiers:
        for scope in SCOPES_BY_TIER[tier]:
            seen.setdefault(scope, None)
    return tuple(seen)


def normalize_scp_claim(claim: object) -> tuple[str, ...]:
    """Normalisiert den ``scp``-Claim aus dem Access Token.

    Der Fallstrick, der fast jeden erwischt: bei **genau einem** gewaehrten
    Scope liefert das JWT einen String statt eines Arrays. Wer das nicht
    normalisiert, bekommt beim ersten Minimal-Login eine Liste einzelner
    Buchstaben und sucht den Fehler an der falschen Stelle (Kapitel 4).
    """
    if claim is None:
        return ()
    if isinstance(claim, str):
        return (claim,) if claim else ()
    if isinstance(claim, list | tuple | set):
        return tuple(str(item) for item in claim)
    raise TypeError(f"Unerwarteter scp-Claim: {type(claim).__name__}")


def missing_scopes(granted: object, required: tuple[str, ...]) -> tuple[str, ...]:
    """Welche der geforderten Scopes fehlen."""
    have = set(normalize_scp_claim(granted))
    return tuple(scope for scope in required if scope not in have)
