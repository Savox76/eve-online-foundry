"""Der kurzlebige Listener auf dem Callback-Port."""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from app.esi.callback import CallbackError, CallbackListener


def freier_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def _rufe_auf(port: int, query: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=5.0) as client:
        return await client.get(f"http://127.0.0.1:{port}/callback{query}")


async def test_rueckruf_wird_entgegengenommen() -> None:
    port = freier_port()
    async with CallbackListener(port, expected_state="der-state") as listener:
        warten = asyncio.create_task(listener.wait(timeout=5))
        antwort = await _rufe_auf(port, "?code=der-code&state=der-state")
        ergebnis = await warten

    assert ergebnis.code == "der-code"
    assert antwort.status_code == 200
    assert "geschlossen werden" in antwort.text
    # Die Seite gehoert in keinen Cache und in keinen Verlauf.
    assert antwort.headers["cache-control"] == "no-store"


async def test_fremder_state_wird_verworfen() -> None:
    """Sonst koennte jemand einen eigenen Autorisierungscode unterschieben."""
    port = freier_port()
    async with CallbackListener(port, expected_state="unser-state") as listener:
        warten = asyncio.create_task(listener.wait(timeout=5))
        antwort = await _rufe_auf(port, "?code=fremder-code&state=fremder-state")
        with pytest.raises(CallbackError, match="State"):
            await warten
    assert "fehlgeschlagen" in antwort.text


async def test_ablehnung_durch_den_nutzer_wird_gemeldet() -> None:
    port = freier_port()
    async with CallbackListener(port, expected_state="s") as listener:
        warten = asyncio.create_task(listener.wait(timeout=5))
        await _rufe_auf(port, "?error=access_denied&error_description=Abgelehnt&state=s")
        with pytest.raises(CallbackError, match="abgelehnt"):
            await warten


async def test_rueckruf_ohne_code_wird_verworfen() -> None:
    port = freier_port()
    async with CallbackListener(port, expected_state="s") as listener:
        warten = asyncio.create_task(listener.wait(timeout=5))
        await _rufe_auf(port, "")
        with pytest.raises(CallbackError, match="weder Code noch State"):
            await warten


async def test_ohne_rueckkehr_wird_abgebrochen() -> None:
    port = freier_port()
    async with CallbackListener(port, expected_state="s") as listener:
        with pytest.raises(CallbackError, match="Rueckkehr"):
            await listener.wait(timeout=0.2)


async def test_belegter_port_meldet_sich_deutlich() -> None:
    """Fester Port heisst: er kann belegt sein. Das gehoert erklaert."""
    port = freier_port()
    async with CallbackListener(port, expected_state="s"):
        with pytest.raises(CallbackError, match="belegt"):
            await CallbackListener(port, expected_state="s").start()


async def test_der_port_ist_danach_wieder_frei() -> None:
    """Ein dauerhaft offener Port waere eine unnoetige Angriffsflaeche."""
    port = freier_port()
    listener = CallbackListener(port, expected_state="s")
    await listener.start()
    await listener.stop()

    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))  # wirft, wenn noch belegt


async def test_listener_bindet_nur_an_loopback() -> None:
    """Sonst naehme er den Code von irgendwoher im Netz entgegen."""
    port = freier_port()
    async with CallbackListener(port, expected_state="s"):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Auf einer anderen lokalen Adresse muss derselbe Port frei sein.
            probe.bind(("127.0.0.2", port))
