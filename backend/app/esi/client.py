"""Der eine ESI-Client.

Es gibt genau einen im Prozess, und aller externe Verkehr laeuft durch ihn.
Das ist keine Stilfrage: Rate Limit und Fehlerbudget gelten pro Anwendung, und
sie lassen sich nur einhalten, wenn ein einziger Zaehler alle Abrufe sieht --
ueber alle Charaktere und Corps hinweg (Kapitel 3 und 6).

Was der Client von sich aus tut, ohne dass ein Aufrufer daran denken muss:

* ``User-Agent`` und ``X-Compatibility-Date`` an **jedem** Request
* ``Expires`` beachten -- ein Abruf vor Ablauf wird gar nicht erst gestellt
* ``ETag`` speichern und als ``If-None-Match`` zurueckschicken
* Buchung im gemeinsamen Budget, vor und nach dem Request
* seitenweise Abrufe zusammensetzen und dabei ``Last-Modified`` gegenpruefen
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any, Self

import httpx

from app.core.config import ESI_BASE_URL, ESI_COMPATIBILITY_DATE, get_settings
from app.core.ratelimit import EsiBudget, get_budget
from app.esi.cache import CacheEntry, EtagStore, InMemoryEtagStore, parse_http_date
from app.esi.compat import COMPATIBILITY_HEADER
from app.esi.errors import (
    EsiError,
    EsiErrorLimited,
    EsiForbidden,
    EsiNotFound,
    EsiPaginationError,
    EsiRateLimited,
    EsiServerError,
)
from app.esi.routes import Route

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


@dataclass(slots=True)
class EsiResponse:
    """Das Ergebnis eines Abrufs.

    ``not_modified`` ist der haeufigste Gutfall im Dauerbetrieb und der
    eigentliche Zweck des ETag-Cachings: nichts zu tun ist die schnellste Art,
    aktuell zu sein.
    """

    data: Any
    status_code: int
    not_modified: bool = False
    from_cache: bool = False
    etag: str | None = None
    expires_at: dt.datetime | None = None
    last_modified: str | None = None
    pages: int = 1
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def unchanged(self) -> bool:
        """Wahr, wenn der Abruf keine neuen Daten gebracht hat."""
        return self.not_modified or self.from_cache


class EsiClient:
    """Async-Client um ``httpx`` mit Budget, Cache und Kompatibilitaetsdatum."""

    def __init__(
        self,
        *,
        base_url: str = ESI_BASE_URL,
        budget: EsiBudget | None = None,
        etag_store: EtagStore | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        compatibility_date: str = ESI_COMPATIBILITY_DATE,
    ) -> None:
        settings = get_settings()
        self._budget = budget or get_budget()
        self._store = etag_store or InMemoryEtagStore()
        self._compatibility_date = compatibility_date
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=DEFAULT_TIMEOUT,
            transport=transport,
            follow_redirects=False,
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "application/json",
                COMPATIBILITY_HEADER: compatibility_date,
            },
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- Einzelabruf --------------------------------------------------------
    async def request(
        self,
        route: Route,
        *,
        token: str | None = None,
        params: dict[str, Any] | None = None,
        json: Any = None,
        page: int | None = None,
        use_cache: bool = True,
        path_params: dict[str, object] | None = None,
    ) -> EsiResponse:
        """Ein Abruf, vollstaendig gebucht und gecached.

        Pfadparameter kommen als Dictionary, nicht als ``**kwargs``. Das ist
        Absicht: ein Pfadparameter, der zufaellig ``token`` oder ``params``
        heisst, wuerde sonst stillschweigend das falsche Argument belegen.
        """
        path = route.format(**(path_params or {}))
        query = dict(params or {})
        if page is not None:
            query["page"] = page
        cache_key = _cache_key(route.method, path, query)

        entry = await self._store.get(cache_key) if use_cache else None
        if entry is not None and entry.is_fresh():
            logger.debug("ESI %s: noch gueltig bis %s -- kein Abruf", route.name, entry.expires_at)
            return EsiResponse(
                data=None,
                status_code=304,
                from_cache=True,
                etag=entry.etag,
                expires_at=entry.expires_at,
            )

        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if entry is not None and entry.etag:
            headers["If-None-Match"] = entry.etag

        await self._budget.acquire(route.group.value)
        try:
            response = await self._client.request(
                route.method, path, params=query, json=json, headers=headers
            )
        except httpx.HTTPError as exc:
            # Ein Transportfehler hat keine Antwort und damit keine Header --
            # er kostet nichts im Budget und wird nicht gebucht.
            raise EsiServerError(f"ESI nicht erreichbar: {exc}", route=route.name) from exc

        await self._budget.observe(
            status_code=response.status_code,
            group=route.group.value,
            headers=dict(response.headers),
        )
        return await self._handle(route, response, cache_key, use_cache=use_cache)

    async def _handle(
        self, route: Route, response: httpx.Response, cache_key: str, *, use_cache: bool
    ) -> EsiResponse:
        status = response.status_code
        etag = response.headers.get("etag")
        expires_at = parse_http_date(response.headers.get("expires"))
        last_modified = response.headers.get("last-modified")
        pages = int(response.headers.get("x-pages", "1") or 1)

        if status == 304:
            if use_cache:
                await self._store.set(cache_key, CacheEntry(etag=etag, expires_at=expires_at))
            return EsiResponse(
                data=None,
                status_code=304,
                not_modified=True,
                etag=etag,
                expires_at=expires_at,
                last_modified=last_modified,
                pages=pages,
                headers=dict(response.headers),
            )

        if status == 420:
            reset = _float(response.headers.get("x-esi-error-limit-reset")) or 60.0
            raise EsiErrorLimited(
                "ESI-Fehlerbudget aufgebraucht -- alle Routen sind vorerst zu.",
                reset_after=reset,
                route=route.name,
            )
        if status == 429:
            retry = _float(response.headers.get("retry-after")) or 60.0
            raise EsiRateLimited(
                f"Rate Limit fuer Gruppe {route.group.value} erreicht.",
                retry_after=retry,
                route=route.name,
            )
        if status == 403:
            raise EsiForbidden(
                f"Kein Zugriff auf {route.name}. Fehlt eine In-Game-Rolle oder "
                "Docking-Zugriff auf die Struktur?",
                status_code=403,
                route=route.name,
            )
        if status == 404:
            raise EsiNotFound(f"{route.name} lieferte 404.", status_code=404, route=route.name)
        if status >= 500:
            raise EsiServerError(
                f"{route.name} lieferte {status}.", status_code=status, route=route.name
            )
        if status >= 400:
            raise EsiError(
                f"{route.name} lieferte {status}: {response.text[:200]}",
                status_code=status,
                route=route.name,
            )

        if use_cache and (etag or expires_at):
            await self._store.set(cache_key, CacheEntry(etag=etag, expires_at=expires_at))

        return EsiResponse(
            data=response.json() if response.content else None,
            status_code=status,
            etag=etag,
            expires_at=expires_at,
            last_modified=last_modified,
            pages=pages,
            headers=dict(response.headers),
        )

    # -- Seitenweiser Abruf -------------------------------------------------
    async def request_all_pages(
        self,
        route: Route,
        *,
        token: str | None = None,
        params: dict[str, Any] | None = None,
        max_pages: int = 100,
        path_params: dict[str, object] | None = None,
    ) -> EsiResponse:
        """Holt alle Seiten und setzt sie zu einer Liste zusammen.

        ``Last-Modified`` muss ueber alle Seiten identisch sein. Weicht es ab,
        hat sich der Datensatz mitten im Abruf geaendert -- die Seiten passen
        dann nicht zusammen und der ganze Abruf wird verworfen (Kapitel 6).
        """
        first = await self.request(
            route, token=token, params=params, page=1, path_params=path_params
        )
        if first.unchanged:
            return first

        items: list[Any] = list(first.data or [])
        total = min(first.pages, max_pages)
        if first.pages > max_pages:
            logger.warning(
                "%s meldet %d Seiten, es werden %d geholt.", route.name, first.pages, max_pages
            )

        for page in range(2, total + 1):
            following = await self.request(
                route,
                token=token,
                params=params,
                page=page,
                use_cache=False,
                path_params=path_params,
            )
            if following.last_modified != first.last_modified:
                raise EsiPaginationError(
                    f"{route.name}: Last-Modified aendert sich zwischen Seite 1 "
                    f"({first.last_modified}) und {page} ({following.last_modified}). "
                    "Der Datensatz hat sich mitten im Abruf geaendert.",
                    route=route.name,
                )
            items.extend(following.data or [])

        first.data = items
        return first


def _cache_key(method: str, path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{method} {path}"
    ordered = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return f"{method} {path}?{ordered}"


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
