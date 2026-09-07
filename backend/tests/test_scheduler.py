"""Zeitplaene.

Die eine Regel, die sonst irgendwann verletzt wird: kein Intervall unter der
ESI-Cache-Dauer. Ein Abruf davor liefert garantiert dieselben Daten und kostet
trotzdem Budget.
"""

from __future__ import annotations

import pytest

from app.workers.scheduler import DEFAULT_SCHEDULES, Schedule, SyncScheduler


def test_alle_vorgaben_liegen_ueber_der_cache_dauer() -> None:
    for schedule in DEFAULT_SCHEDULES:
        schedule.validate()  # wirft, wenn eine Vorgabe zu kurz ist


def test_zu_kurzes_intervall_wird_abgelehnt() -> None:
    zu_kurz = Schedule("assets", interval_minutes=30, esi_cache_minutes=60)
    with pytest.raises(ValueError, match="Cache-Dauer"):
        zu_kurz.validate()


def test_scheduler_verweigert_zu_kurze_zeitplaene() -> None:
    async def job() -> None:  # pragma: no cover -- wird nie ausgefuehrt
        return None

    scheduler = SyncScheduler()
    with pytest.raises(ValueError, match="Cache-Dauer"):
        scheduler.register(Schedule("jobs", interval_minutes=1, esi_cache_minutes=5), job)


def test_registrierte_zeitplaene_tragen_jitter() -> None:
    """Zehn Zeitplaene auf :00 sind ein Ansturm, zehn gestreute sind Verkehr."""

    async def job() -> None:  # pragma: no cover
        return None

    scheduler = SyncScheduler()
    scheduler.register(Schedule("assets", interval_minutes=70, esi_cache_minutes=60), job)
    assert scheduler.schedules["assets"].jitter_seconds > 0


def test_asset_intervall_liegt_ueber_dem_esi_cache() -> None:
    """70 Minuten bei einer Stunde Cache -- so steht es in Kapitel 6."""
    assets = next(s for s in DEFAULT_SCHEDULES if s.name == "assets")
    assert assets.interval_minutes == 70
    assert assets.esi_cache_minutes == 60
