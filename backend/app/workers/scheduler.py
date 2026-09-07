"""Der Zeitplan-Dienst.

Zwei Regeln stecken fest verdrahtet drin, weil beide sonst irgendwann vergessen
werden:

**Jitter statt fester Minuten.** Zehn Zeitplaene, die alle auf ``:00`` stehen,
sind ein Ansturm auf ESI und reissen zuverlaessig das Rate Limit. Jeder Job
bekommt deshalb eine Streuung.

**Intervalle laenger als der ESI-Cache.** Ein Abruf vor Ablauf von ``Expires``
liefert garantiert dieselben Daten und kostet trotzdem Budget. Die Vorgaben
unten liegen deshalb durchgaengig ueber der jeweiligen Cache-Dauer
(Kapitel 6).
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

AsyncJob = Callable[[], Coroutine[Any, Any, None]]


@dataclass(frozen=True, slots=True)
class Schedule:
    """Ein geplanter Lauf.

    ``esi_cache_minutes`` ist keine Deko: ``validate`` prueft damit, dass das
    Intervall nicht unter der Cache-Dauer liegt.
    """

    name: str
    interval_minutes: float
    esi_cache_minutes: float = 0.0
    jitter_seconds: int = 300
    #: Beim Start sofort einmal laufen, statt ein volles Intervall zu warten.
    run_on_startup: bool = True

    def validate(self) -> None:
        if self.esi_cache_minutes and self.interval_minutes < self.esi_cache_minutes:
            raise ValueError(
                f"Zeitplan '{self.name}': Intervall {self.interval_minutes} min liegt unter "
                f"der ESI-Cache-Dauer {self.esi_cache_minutes} min. Der Abruf koennte gar "
                "keine neuen Daten liefern und wuerde nur Budget kosten."
            )


#: Die Vorgaben aus Kapitel 6. Die Jobs dazu entstehen in Phase 2 und spaeter;
#: die Tabelle steht hier, damit Intervall und Cache-Dauer an einer Stelle
#: nebeneinander stehen und nicht auseinanderlaufen.
DEFAULT_SCHEDULES: tuple[Schedule, ...] = (
    Schedule("assets", interval_minutes=70, esi_cache_minutes=60),
    Schedule("blueprints", interval_minutes=70, esi_cache_minutes=60),
    Schedule("industry_jobs", interval_minutes=10, esi_cache_minutes=5),
    Schedule("cost_indices", interval_minutes=60 * 24, esi_cache_minutes=60),
    Schedule("reference_prices", interval_minutes=60 * 24, esi_cache_minutes=60),
    Schedule("market_depth", interval_minutes=60, esi_cache_minutes=30),
    Schedule("market_history", interval_minutes=60 * 24, esi_cache_minutes=60 * 24),
    Schedule("scanner_rebuild", interval_minutes=60 * 24, run_on_startup=False),
    Schedule("pi_colonies", interval_minutes=30, esi_cache_minutes=10),
    Schedule("skills_and_roles", interval_minutes=60 * 6, esi_cache_minutes=60),
)


class SyncScheduler:
    """Duenne Schale um APScheduler.

    Der Zweck der Schale ist die Durchsetzung der beiden Regeln oben: ein Job
    laesst sich hier nicht ohne Jitter und nicht mit einem zu kurzen Intervall
    registrieren.
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._registered: dict[str, Schedule] = {}

    def register(self, schedule: Schedule, job: AsyncJob) -> None:
        schedule.validate()
        self._registered[schedule.name] = schedule

        extra: dict[str, Any] = {}
        if schedule.run_on_startup:
            # Eine Desktop-Anwendung laeuft nur, wenn jemand sie startet. Ein
            # Zeitplan, der erst nach einem vollen Intervall zum ersten Mal
            # feuert, hat bei einer Sitzung von zwanzig Minuten nie gefeuert.
            # Deshalb: beim Start einmal sofort, danach im Intervall.
            extra["next_run_time"] = dt.datetime.now(dt.UTC)

        self._scheduler.add_job(
            job,
            trigger=IntervalTrigger(minutes=schedule.interval_minutes),
            id=schedule.name,
            name=schedule.name,
            jitter=schedule.jitter_seconds,
            max_instances=1,
            # Verpasste Laeufe werden zusammengefasst, nicht nachgeholt. Nach
            # zwei Wochen Standby will niemand vierzehn Asset-Syncs am Stueck.
            coalesce=True,
            misfire_grace_time=None,
            **extra,
        )
        logger.info(
            "Zeitplan '%s' registriert: alle %.0f min (+/- %ds Jitter)",
            schedule.name,
            schedule.interval_minutes,
            schedule.jitter_seconds,
        )

    def start(self) -> None:
        if not self._registered:
            logger.info("Keine Zeitplaene registriert -- der Scheduler laeuft leer mit.")
        self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    @property
    def schedules(self) -> dict[str, Schedule]:
        return dict(self._registered)


_scheduler: SyncScheduler | None = None


def get_scheduler() -> SyncScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = SyncScheduler()
    return _scheduler


def reset_scheduler() -> None:
    """Nur fuer Tests."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown()
    _scheduler = None
