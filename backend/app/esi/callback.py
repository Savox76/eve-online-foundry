"""Der kurzlebige Listener auf dem Callback-Port.

Ablauf: Listener oeffnen, Systembrowser starten, den einen Aufruf mit ``code``
und ``state`` entgegennehmen, ``state`` pruefen, Listener sofort wieder
schliessen (Kapitel 4).

Zwei Eigenschaften sind wichtiger, als sie aussehen:

* **Fester Port.** Die SSO weist jede Callback-URL zurueck, die nicht exakt so
  im Developers-Portal steht. Ein zufaelliger Port funktioniert deshalb nicht.
* **Nur an die Loopback-Adresse binden.** Sonst nimmt der Listener den Code von
  irgendwoher im Netz entgegen.

Der Listener lebt genau einen Login lang. Ein dauerhaft offener Port waere eine
unnoetige Angriffsflaeche fuer eine Anwendung, die sich vielleicht einmal pro
Woche anmeldet.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

logger = logging.getLogger(__name__)

#: Nach so langer Zeit ohne Rueckkehr aus dem Browser wird abgebrochen. Fuenf
#: Minuten reichen fuer Anmeldung samt Zwei-Faktor; laenger offen zu bleiben
#: bringt nichts, weil der Nutzer den Versuch dann ohnehin abgebrochen hat.
DEFAULT_TIMEOUT_SECONDS = 300.0


class CallbackError(Exception):
    """Der Callback kam nicht, kam falsch, oder kam mit einer Ablehnung."""


@dataclass(frozen=True, slots=True)
class CallbackResult:
    code: str
    state: str


_PAGE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>{title}</title>
<style>
 body{{background:#0b1015;color:#dce5ec;font:16px/1.6 system-ui,sans-serif;
      display:grid;place-items:center;height:100vh;margin:0}}
 div{{text-align:center;max-width:34rem;padding:0 1.5rem}}
 h1{{font-size:1.35rem;margin:0 0 .5rem;color:{color}}}
 p{{color:#8ea0ae;margin:0}}
</style></head>
<body><div><h1>{title}</h1><p>{message}</p></div></body></html>"""


def _page(title: str, message: str, color: str) -> bytes:
    body = _PAGE.format(title=title, message=message, color=color).encode("utf-8")
    head = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        # Diese Seite gehoert in keinen Verlauf und in keinen Cache.
        "Cache-Control: no-store\r\n\r\n"
    ).encode("ascii")
    return head + body


SUCCESS_PAGE = _page(
    "Charakter verbunden",
    "Dieses Fenster kann geschlossen werden — weiter geht es in New Eden Foundry.",
    "#5cb98d",
)
FAILURE_PAGE = _page(
    "Anmeldung fehlgeschlagen",
    "New Eden Foundry hat den Rückruf nicht annehmen können. Bitte in der "
    "Anwendung erneut versuchen.",
    "#e0736c",
)


class CallbackListener:
    """Nimmt genau einen Callback entgegen und macht wieder zu."""

    def __init__(self, port: int, *, expected_state: str, host: str = "127.0.0.1") -> None:
        self._port = port
        self._host = host
        self._expected_state = expected_state
        self._result: asyncio.Future[CallbackResult] | None = None
        self._server: asyncio.AbstractServer | None = None

    async def __aenter__(self) -> CallbackListener:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.stop()

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._result = loop.create_future()
        try:
            self._server = await asyncio.start_server(self._handle, self._host, self._port)
        except OSError as exc:
            raise CallbackError(
                f"Der Callback-Port {self._port} ist belegt. Laeuft noch ein "
                f"Anmeldeversuch? ({exc})"
            ) from exc
        logger.info("Callback-Listener auf http://%s:%d bereit.", self._host, self._port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("Callback-Listener geschlossen.")

    async def wait(self, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> CallbackResult:
        if self._result is None:  # pragma: no cover -- start() vergessen
            raise CallbackError("Der Listener wurde nicht gestartet.")
        try:
            return await asyncio.wait_for(asyncio.shield(self._result), timeout)
        except TimeoutError as exc:
            raise CallbackError(
                f"Keine Rueckkehr aus dem Browser innerhalb von {timeout:.0f} s."
            ) from exc

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
            target = _request_target(request_line)
            params = parse_qs(urlsplit(target).query)

            page = FAILURE_PAGE
            try:
                result = self._interpret(params)
            except CallbackError as exc:
                self._fail(exc)
            else:
                page = SUCCESS_PAGE
                self._succeed(result)

            writer.write(page)
            await writer.drain()
        except (TimeoutError, ConnectionError, ValueError) as exc:  # pragma: no cover
            logger.warning("Callback-Verbindung abgebrochen: %s", exc)
        finally:
            writer.close()

    def _interpret(self, params: dict[str, list[str]]) -> CallbackResult:
        if "error" in params:
            beschreibung = params.get("error_description", [""])[0]
            raise CallbackError(
                f"Die Anmeldung wurde abgelehnt: {params['error'][0]} {beschreibung}".strip()
            )

        code = params.get("code", [""])[0]
        state = params.get("state", [""])[0]
        if not code or not state:
            raise CallbackError("Der Rueckruf enthaelt weder Code noch State.")

        import secrets

        if not secrets.compare_digest(state, self._expected_state):
            # Ein fremder ``state`` heisst: dieser Rueckruf gehoert nicht zu
            # unserem Anmeldeversuch. Er wird verworfen, nicht verwertet.
            raise CallbackError("Der State passt nicht zum Anmeldeversuch.")

        return CallbackResult(code=code, state=state)

    def _succeed(self, result: CallbackResult) -> None:
        if self._result is not None and not self._result.done():
            self._result.set_result(result)

    def _fail(self, error: CallbackError) -> None:
        if self._result is not None and not self._result.done():
            self._result.set_exception(error)


def _request_target(request_line: bytes) -> str:
    """Holt den Pfad samt Query aus der Anfragezeile."""
    parts = request_line.decode("latin-1").split(" ")
    if len(parts) < 2:
        raise ValueError("Unlesbare HTTP-Anfragezeile")
    return parts[1]
