"""Katalog der ESI-Routen, die Foundry benutzt.

Der Sinn dieser Datei ist, dass kein Pfad irgendwo im Code als String-Literal
auftaucht. Wenn CCP das Kompatibilitaetsdatum anhebt und sich eine Route
aendert, ist genau eine Datei zu pruefen.

``group`` ist die *lokale* Annahme fuer das Rate-Limit-Budget. Die Wahrheit
steht im ``X-Ratelimit-Group``-Header der Antwort; bis der da ist, wird nach
dieser Annahme gebucht.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RouteGroup(StrEnum):
    """Lokale Vorab-Zuordnung fuers Budget."""

    ASSETS = "assets"
    BLUEPRINTS = "blueprints"
    INDUSTRY = "industry"
    MARKETS = "markets"
    UNIVERSE = "universe"
    CHARACTER = "character"
    CORPORATION = "corporation"
    PLANETS = "planets"
    FITTINGS = "fittings"
    MAIL = "mail"
    UI = "ui"


@dataclass(frozen=True, slots=True)
class Route:
    """Eine ESI-Route mit allem, was der Client ueber sie wissen muss."""

    name: str
    path: str
    group: RouteGroup
    #: ``False`` = oeffentlich, kein Token noetig.
    authenticated: bool = True
    #: Liefert die Route Seiten ueber ``X-Pages``?
    paginated: bool = False
    #: Cache-Dauer laut ESI, nur zur Dokumentation -- durchgesetzt wird
    #: ``Expires`` aus der Antwort.
    esi_cache: str = ""
    method: str = "GET"

    def format(self, **params: object) -> str:
        return self.path.format(**params)


# -- Bestaende ---------------------------------------------------------------
CHARACTER_ASSETS = Route(
    "character_assets",
    "/characters/{character_id}/assets/",
    RouteGroup.ASSETS,
    paginated=True,
    esi_cache="1h",
)
CHARACTER_ASSET_NAMES = Route(
    "character_asset_names",
    "/characters/{character_id}/assets/names/",
    RouteGroup.ASSETS,
    method="POST",
)
CORPORATION_ASSETS = Route(
    "corporation_assets",
    "/corporations/{corporation_id}/assets/",
    RouteGroup.ASSETS,
    paginated=True,
    esi_cache="1h",
)
CORPORATION_ASSET_NAMES = Route(
    "corporation_asset_names",
    "/corporations/{corporation_id}/assets/names/",
    RouteGroup.ASSETS,
    method="POST",
)

# -- Blueprints und Industrie ------------------------------------------------
CHARACTER_BLUEPRINTS = Route(
    "character_blueprints",
    "/characters/{character_id}/blueprints/",
    RouteGroup.BLUEPRINTS,
    paginated=True,
    esi_cache="1h",
)
CORPORATION_BLUEPRINTS = Route(
    "corporation_blueprints",
    "/corporations/{corporation_id}/blueprints/",
    RouteGroup.BLUEPRINTS,
    paginated=True,
    esi_cache="1h",
)
CHARACTER_INDUSTRY_JOBS = Route(
    "character_industry_jobs",
    "/characters/{character_id}/industry/jobs/",
    RouteGroup.INDUSTRY,
    esi_cache="5m",
)
CORPORATION_INDUSTRY_JOBS = Route(
    "corporation_industry_jobs",
    "/corporations/{corporation_id}/industry/jobs/",
    RouteGroup.INDUSTRY,
    paginated=True,
    esi_cache="5m",
)
INDUSTRY_SYSTEMS = Route(
    "industry_systems",
    "/industry/systems/",
    RouteGroup.INDUSTRY,
    authenticated=False,
    esi_cache="1h",
)
INDUSTRY_FACILITIES = Route(
    "industry_facilities",
    "/industry/facilities/",
    RouteGroup.INDUSTRY,
    authenticated=False,
    esi_cache="1h",
)

# -- Markt -------------------------------------------------------------------
MARKET_PRICES = Route(
    "market_prices",
    "/markets/prices/",
    RouteGroup.MARKETS,
    authenticated=False,
    esi_cache="1h",
)
MARKET_ORDERS = Route(
    "market_orders",
    "/markets/{region_id}/orders/",
    RouteGroup.MARKETS,
    authenticated=False,
    paginated=True,
    esi_cache="5m",
)
#: Liefert **einen Typ pro Request**. Fuer den Scanner damit unbrauchbar --
#: der arbeitet ueber die Bulk-Dumps von EVE Ref (Kapitel 10). Diese Route
#: bleibt fuer den Live-Check eines einzelnen Typs vor dem Auftrag.
MARKET_HISTORY = Route(
    "market_history",
    "/markets/{region_id}/history/",
    RouteGroup.MARKETS,
    authenticated=False,
    esi_cache="1d",
)

# -- Universum ---------------------------------------------------------------
#: Antwortet ohne Docking-Zugriff mit 403. Das ist ein erwarteter Zustand,
#: kein Fehler -- siehe ``EsiForbidden`` in ``esi/errors.py``.
UNIVERSE_STRUCTURE = Route(
    "universe_structure",
    "/universe/structures/{structure_id}/",
    RouteGroup.UNIVERSE,
)
UNIVERSE_NAMES = Route(
    "universe_names",
    "/universe/names/",
    RouteGroup.UNIVERSE,
    authenticated=False,
    method="POST",
)

# -- Charakter ---------------------------------------------------------------
CHARACTER_PUBLIC = Route(
    "character_public",
    "/characters/{character_id}/",
    RouteGroup.CHARACTER,
    authenticated=False,
    esi_cache="1d",
)
CHARACTER_ROLES = Route(
    "character_roles",
    "/characters/{character_id}/roles/",
    RouteGroup.CHARACTER,
    esi_cache="1h",
)
CHARACTER_SKILLS = Route(
    "character_skills",
    "/characters/{character_id}/skills/",
    RouteGroup.CHARACTER,
    esi_cache="2h",
)

# -- Planetare Industrie -----------------------------------------------------
CHARACTER_PLANETS = Route(
    "character_planets",
    "/characters/{character_id}/planets/",
    RouteGroup.PLANETS,
    esi_cache="10m",
)
CHARACTER_PLANET_DETAIL = Route(
    "character_planet_detail",
    "/characters/{character_id}/planets/{planet_id}/",
    RouteGroup.PLANETS,
)
CORPORATION_CUSTOMS_OFFICES = Route(
    "corporation_customs_offices",
    "/corporations/{corporation_id}/customs_offices/",
    RouteGroup.PLANETS,
    paginated=True,
    esi_cache="1h",
)

# -- Fittings ----------------------------------------------------------------
CHARACTER_FITTINGS = Route(
    "character_fittings",
    "/characters/{character_id}/fittings/",
    RouteGroup.FITTINGS,
    esi_cache="5m",
)

ALL_ROUTES: tuple[Route, ...] = tuple(
    value for value in list(globals().values()) if isinstance(value, Route)
)

ROUTES_BY_NAME: dict[str, Route] = {route.name: route for route in ALL_ROUTES}
