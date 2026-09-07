"""Der ESI-Client gegen einen nachgebauten Server.

Geprueft wird genau das, was CCP durchsetzt und was sich sonst erst im
Dauerbetrieb zeigt: Header an jedem Request, ETag-Umlauf, ``Expires`` als
Abrufsperre, Seitenkonsistenz und der Umgang mit 403.
"""

from __future__ import annotations

import datetime as dt
from email.utils import format_datetime

import httpx
import pytest
import respx

from app.core.config import ESI_BASE_URL, ESI_COMPATIBILITY_DATE
from app.esi.cache import InMemoryEtagStore
from app.esi.client import EsiClient
from app.esi.errors import EsiForbidden, EsiPaginationError
from app.esi.routes import CHARACTER_ASSETS, MARKET_PRICES, UNIVERSE_STRUCTURE


def _http_date(offset_seconds: int) -> str:
    return format_datetime(
        dt.datetime.now(dt.UTC) + dt.timedelta(seconds=offset_seconds), usegmt=True
    )


@pytest.fixture
def store() -> InMemoryEtagStore:
    return InMemoryEtagStore()


@respx.mock
async def test_jeder_request_traegt_kompatibilitaetsdatum_und_user_agent(
    store: InMemoryEtagStore,
) -> None:
    route = respx.get(f"{ESI_BASE_URL}/markets/prices/").mock(
        return_value=httpx.Response(200, json=[])
    )
    async with EsiClient(etag_store=store) as client:
        await client.request(MARKET_PRICES)

    request = route.calls.last.request
    assert request.headers["X-Compatibility-Date"] == ESI_COMPATIBILITY_DATE
    assert request.headers["User-Agent"].startswith("NewEdenFoundry/")
    assert "example.invalid" in request.headers["User-Agent"]


@respx.mock
async def test_etag_wird_gespeichert_und_zurueckgeschickt(store: InMemoryEtagStore) -> None:
    route = respx.get(f"{ESI_BASE_URL}/markets/prices/").mock(
        side_effect=[
            httpx.Response(200, json=[{"type_id": 1}], headers={"ETag": '"abc"'}),
            httpx.Response(304, headers={"ETag": '"abc"'}),
        ]
    )
    async with EsiClient(etag_store=store) as client:
        first = await client.request(MARKET_PRICES)
        assert first.data == [{"type_id": 1}]
        second = await client.request(MARKET_PRICES)

    assert route.calls[1].request.headers["If-None-Match"] == '"abc"'
    assert second.not_modified is True
    assert second.unchanged is True
    assert second.data is None


@respx.mock
async def test_gueltiges_expires_verhindert_den_abruf_ganz(store: InMemoryEtagStore) -> None:
    """Vor Ablauf gibt es keine neuen Daten -- ein Abruf waere reine Verschwendung."""
    route = respx.get(f"{ESI_BASE_URL}/markets/prices/").mock(
        return_value=httpx.Response(200, json=[], headers={"Expires": _http_date(3600)})
    )
    async with EsiClient(etag_store=store) as client:
        await client.request(MARKET_PRICES)
        second = await client.request(MARKET_PRICES)

    assert route.call_count == 1, "Der zweite Abruf haette gar nicht stattfinden duerfen"
    assert second.from_cache is True
    assert second.unchanged is True


@respx.mock
async def test_abgelaufenes_expires_erlaubt_den_abruf(store: InMemoryEtagStore) -> None:
    route = respx.get(f"{ESI_BASE_URL}/markets/prices/").mock(
        return_value=httpx.Response(200, json=[], headers={"Expires": _http_date(-10)})
    )
    async with EsiClient(etag_store=store) as client:
        await client.request(MARKET_PRICES)
        await client.request(MARKET_PRICES)
    assert route.call_count == 2


@respx.mock
async def test_seiten_werden_zusammengesetzt(store: InMemoryEtagStore) -> None:
    stamp = _http_date(-60)
    respx.get(f"{ESI_BASE_URL}/characters/42/assets/", params={"page": "1"}).mock(
        return_value=httpx.Response(
            200, json=[{"item_id": 1}], headers={"X-Pages": "2", "Last-Modified": stamp}
        )
    )
    respx.get(f"{ESI_BASE_URL}/characters/42/assets/", params={"page": "2"}).mock(
        return_value=httpx.Response(
            200, json=[{"item_id": 2}], headers={"X-Pages": "2", "Last-Modified": stamp}
        )
    )
    async with EsiClient(etag_store=store) as client:
        response = await client.request_all_pages(
            CHARACTER_ASSETS, path_params={"character_id": 42}
        )
    assert response.data == [{"item_id": 1}, {"item_id": 2}]


@respx.mock
async def test_abweichendes_last_modified_verwirft_den_abruf(
    store: InMemoryEtagStore,
) -> None:
    """Die Seiten passen dann nicht zusammen -- lieber nichts als Halbes."""
    respx.get(f"{ESI_BASE_URL}/characters/42/assets/", params={"page": "1"}).mock(
        return_value=httpx.Response(
            200, json=[{"item_id": 1}], headers={"X-Pages": "2", "Last-Modified": _http_date(-600)}
        )
    )
    respx.get(f"{ESI_BASE_URL}/characters/42/assets/", params={"page": "2"}).mock(
        return_value=httpx.Response(
            200, json=[{"item_id": 2}], headers={"X-Pages": "2", "Last-Modified": _http_date(-10)}
        )
    )
    async with EsiClient(etag_store=store) as client:
        with pytest.raises(EsiPaginationError, match="Last-Modified"):
            await client.request_all_pages(CHARACTER_ASSETS, path_params={"character_id": 42})


@respx.mock
async def test_403_auf_einer_struktur_ist_ein_eigener_fehler(
    store: InMemoryEtagStore,
) -> None:
    """Eine Struktur ohne Docking-Zugriff darf nicht den ganzen Sync anhalten."""
    respx.get(f"{ESI_BASE_URL}/universe/structures/1035000000000/").mock(
        return_value=httpx.Response(403, json={"error": "Forbidden"})
    )
    async with EsiClient(etag_store=store) as client:
        with pytest.raises(EsiForbidden) as exc:
            await client.request(UNIVERSE_STRUCTURE, path_params={"structure_id": 1035000000000})
    assert exc.value.route == "universe_structure"
    assert exc.value.status_code == 403


@respx.mock
async def test_budget_wird_aus_den_antwortheadern_gefuehrt(store: InMemoryEtagStore) -> None:
    from app.core.ratelimit import EsiBudget

    budget = EsiBudget()
    respx.get(f"{ESI_BASE_URL}/markets/prices/").mock(
        return_value=httpx.Response(
            200,
            json=[],
            headers={
                "X-Ratelimit-Group": "markets",
                "X-Ratelimit-Limit": "150",
                "X-Ratelimit-Remaining": "42",
                "X-ESI-Error-Limit-Remain": "99",
            },
        )
    )
    async with EsiClient(etag_store=store, budget=budget) as client:
        await client.request(MARKET_PRICES)

    snapshot = budget.snapshot()
    assert snapshot["error_remain"] == 99
    assert snapshot["groups"]["markets"]["remaining"] == 42.0
