"""Das ESI-Budget: zwei Grenzen gleichzeitig einhalten.

CCP setzt zwei voneinander unabhaengige Mechanismen durch (Kapitel 6), und wer
nur einen davon beachtet, wird trotzdem gesperrt:

**Rate Limit** -- ein Token-Budget je Routengruppe (``X-Ratelimit-Group``) in
einem gleitenden Fenster, typisch ``150/15m``. Die Kosten haengen am Status:

    ============  ======
    Antwort       Kosten
    ============  ======
    2xx              2
    3xx              1   <- ein 304 ist halb so teuer wie ein 200
    4xx              5   <- ein Client-Fehler kostet mehr als zwei Erfolge
    5xx              0
    ============  ======

Sauberes Caching zahlt sich damit doppelt aus, schlampiges Fehlerverhalten
bestraft sich doppelt.

**Error Limit** -- 100 Nicht-2xx/3xx-Antworten pro Minute, danach ``420`` auf
*allen* Routen. Der Zaehler ist global, nicht pro Route.

Beide Zaehler gelten pro Anwendung, nicht pro Charakter. Deshalb gibt es genau
ein ``EsiBudget`` im Prozess, durch das aller ESI-Verkehr laeuft -- der
Asset-Sync von Charakter A und der Preisabruf von Charakter B teilen sich
dasselbe Budget.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: Kosten je Statusklasse, aus der ESI-Dokumentation.
COST_2XX = 2
COST_3XX = 1
COST_4XX = 5
COST_5XX = 0

#: Bis die erste Antwort die echten Werte liefert, wird konservativ gerechnet.
DEFAULT_LIMIT = 150
DEFAULT_WINDOW_SECONDS = 900.0

#: Faellt ``X-ESI-Error-Limit-Remain`` darunter, wird pausiert. Nicht erst bei
#: 0 reagieren: zwischen Messung und naechstem Request liegen Antworten, die
#: schon unterwegs sind.
ERROR_LIMIT_THRESHOLD = 20

#: Obergrenze fuer eine einzelne Wartezeit. Laenger heisst: es stimmt etwas
#: nicht, und das gehoert gemeldet statt stillschweigend ausgesessen.
MAX_SLEEP_SECONDS = 300.0


def request_cost(status_code: int) -> int:
    """Was eine Antwort im Rate-Limit-Budget kostet."""
    if 200 <= status_code < 300:
        return COST_2XX
    if 300 <= status_code < 400:
        return COST_3XX
    if 400 <= status_code < 500:
        return COST_4XX
    return COST_5XX


def counts_against_error_limit(status_code: int) -> bool:
    """Alles ausser 2xx und 3xx zaehlt gegen das Fehlerbudget."""
    return not 200 <= status_code < 400


def jitter(base_seconds: float, spread: float = 0.15) -> float:
    """Streut einen Zeitplan, damit nicht alle Charaktere gleichzeitig aufschlagen.

    Feste Minuten sind der zuverlaessigste Weg, ein Rate Limit zu reissen:
    zehn Zeitplaene auf ``:00`` sind ein Ansturm, zehn gestreute sind Verkehr.
    """
    # Der Jitter streut Zeitplaene, er schuetzt nichts -- ein
    # kryptographischer Generator waere hier teurer, nicht sicherer.
    return base_seconds * (1.0 + random.uniform(-spread, spread))  # nosec B311


@dataclass
class _GroupBucket:
    """Token-Budget einer Routengruppe."""

    limit: int = DEFAULT_LIMIT
    window_seconds: float = DEFAULT_WINDOW_SECONDS
    remaining: float = float(DEFAULT_LIMIT)
    updated_at: float = field(default_factory=time.monotonic)
    blocked_until: float = 0.0

    @property
    def refill_per_second(self) -> float:
        return self.limit / self.window_seconds if self.window_seconds > 0 else 0.0

    def refill(self, now: float) -> None:
        elapsed = max(0.0, now - self.updated_at)
        self.remaining = min(float(self.limit), self.remaining + elapsed * self.refill_per_second)
        self.updated_at = now

    def wait_seconds_for(self, cost: int, now: float) -> float:
        """Wie lange bis ``cost`` Tokens da sind. 0.0 heisst: sofort."""
        blocked = max(0.0, self.blocked_until - now)
        if self.remaining >= cost:
            return blocked
        rate = self.refill_per_second
        if rate <= 0:  # pragma: no cover -- nur bei kaputten Headern
            return max(blocked, MAX_SLEEP_SECONDS)
        return max(blocked, (cost - self.remaining) / rate)


class EsiBudget:
    """Der gemeinsame Zaehler fuer allen ESI-Verkehr des Prozesses."""

    def __init__(self, *, error_threshold: int = ERROR_LIMIT_THRESHOLD) -> None:
        self._groups: dict[str, _GroupBucket] = {}
        self._lock = asyncio.Lock()
        self._error_threshold = error_threshold
        self._error_remain: int | None = None
        self._breaker_until: float = 0.0

    # -- Zustand ------------------------------------------------------------
    @property
    def error_remain(self) -> int | None:
        """Zuletzt gemeldetes Restfehlerbudget, ``None`` vor der ersten Antwort."""
        return self._error_remain

    def breaker_seconds_left(self) -> float:
        """Wie lange der Circuit Breaker noch haelt. 0.0 heisst: offen."""
        return max(0.0, self._breaker_until - time.monotonic())

    def snapshot(self) -> dict[str, object]:
        """Fuer die Rate-Limit-Ansicht im Admin-Bereich."""
        now = time.monotonic()
        return {
            "error_remain": self._error_remain,
            "breaker_seconds_left": round(self.breaker_seconds_left(), 1),
            "groups": {
                name: {
                    "limit": bucket.limit,
                    "remaining": round(bucket.remaining, 1),
                    "window_seconds": bucket.window_seconds,
                    "blocked_seconds_left": round(max(0.0, bucket.blocked_until - now), 1),
                }
                for name, bucket in sorted(self._groups.items())
            },
        }

    # -- Vor dem Request ----------------------------------------------------
    async def acquire(self, group: str, *, assumed_cost: int = COST_2XX) -> None:
        """Wartet, bis Budget fuer einen Request der Gruppe frei ist.

        Gerechnet wird mit den Kosten einer *erfolgreichen* Antwort. Wird es
        ein Fehler, korrigiert ``observe`` nach unten -- lieber einmal zu
        vorsichtig als einmal gesperrt.
        """
        while True:
            async with self._lock:
                now = time.monotonic()
                breaker_wait = max(0.0, self._breaker_until - now)
                bucket = self._groups.setdefault(group, _GroupBucket())
                bucket.refill(now)
                group_wait = bucket.wait_seconds_for(assumed_cost, now)
                wait = max(breaker_wait, group_wait)
                if wait <= 0.0:
                    bucket.remaining -= assumed_cost
                    return
            capped = min(wait, MAX_SLEEP_SECONDS)
            logger.info(
                "ESI-Budget: warte %.1f s (Gruppe %s, Fehlerbudget %s)",
                capped,
                group,
                self._error_remain,
            )
            await asyncio.sleep(capped)

    # -- Nach der Antwort ---------------------------------------------------
    async def observe(
        self,
        *,
        status_code: int,
        group: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Bucht die tatsaechlichen Kosten und uebernimmt die Server-Wahrheit."""
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        async with self._lock:
            now = time.monotonic()
            bucket = self._groups.setdefault(
                headers.get("x-ratelimit-group", group), _GroupBucket()
            )
            bucket.refill(now)

            # Differenz zwischen angenommenen und echten Kosten nachbuchen.
            bucket.remaining -= request_cost(status_code) - COST_2XX

            limit = _int_header(headers, "x-ratelimit-limit")
            if limit and limit > 0:
                bucket.limit = limit
            window = _int_header(headers, "x-ratelimit-reset")
            if window and window > 0:
                bucket.window_seconds = float(window)

            # Der Server kennt den Stand besser als wir. Bei Abweichung gilt
            # der kleinere Wert -- ein zu optimistischer Zaehler ist genau der
            # Fehler, der zur Sperre fuehrt.
            reported = _int_header(headers, "x-ratelimit-remaining")
            if reported is not None:
                bucket.remaining = min(bucket.remaining, float(reported))
            bucket.remaining = max(0.0, bucket.remaining)

            if status_code == 429:
                retry_after = _float_header(headers, "retry-after") or 60.0
                bucket.blocked_until = now + retry_after
                logger.warning(
                    "ESI antwortet 429 fuer Gruppe %s -- pausiere %.0f s",
                    bucket_name(headers, group),
                    retry_after,
                )

            self._observe_error_limit(status_code, headers, now)

    def _observe_error_limit(self, status_code: int, headers: dict[str, str], now: float) -> None:
        remain = _int_header(headers, "x-esi-error-limit-remain")
        reset = _float_header(headers, "x-esi-error-limit-reset")
        if remain is not None:
            self._error_remain = remain

        if status_code == 420:
            # Das Fehlerbudget ist aufgebraucht. Ab hier antwortet ESI auf
            # *jeder* Route mit 420, bis der Zaehler zurueckgesetzt wird.
            self._breaker_until = now + (reset or 60.0)
            logger.error(
                "ESI-Fehlerbudget aufgebraucht (420) -- alle Abrufe pausieren %.0f s",
                reset or 60.0,
            )
            return

        if remain is not None and remain < self._error_threshold:
            self._breaker_until = max(self._breaker_until, now + (reset or 60.0))
            logger.warning(
                "ESI-Fehlerbudget auf %s (Schwelle %s) -- pausiere %.0f s",
                remain,
                self._error_threshold,
                reset or 60.0,
            )


def bucket_name(headers: dict[str, str], fallback: str) -> str:
    return headers.get("x-ratelimit-group", fallback)


def _int_header(headers: dict[str, str], name: str) -> int | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _float_header(headers: dict[str, str], name: str) -> float | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


_budget: EsiBudget | None = None


def get_budget() -> EsiBudget:
    """Das eine Budget des Prozesses."""
    global _budget
    if _budget is None:
        _budget = EsiBudget()
    return _budget


def reset_budget() -> None:
    """Nur fuer Tests."""
    global _budget
    _budget = None
