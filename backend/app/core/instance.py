"""Einzelinstanz.

Startet die Anwendung ein zweites Mal, streiten zwei Prozesse um dieselbe
SQLite-Datei (Kapitel 18). WAL und ``busy_timeout`` federn das ab, loesen es
aber nicht: zwei Scheduler wuerden denselben ESI-Abruf doppelt fahren und das
gemeinsame Fehlerbudget verbrennen.

Die Sperre haengt an einem Betriebssystem-Lock auf einer Datei, nicht an einer
PID-Datei. Der Unterschied zaehlt: ein abgestuerzter Prozess gibt sein Lock
sofort frei, eine PID-Datei bleibt liegen und sperrt den naechsten Start aus.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from types import TracebackType

from app.core.paths import lock_path

logger = logging.getLogger(__name__)


class AlreadyRunningError(RuntimeError):
    """Eine andere Instanz haelt die Sperre."""


class InstanceLock:
    """Kontextmanager um ein exklusives Dateilock."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or lock_path()
        self._handle: int | None = None

    def acquire(self) -> None:
        handle = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            self._lock(handle)
        except OSError as exc:
            os.close(handle)
            raise AlreadyRunningError(
                f"New Eden Foundry laeuft bereits (Sperre: {self._path})."
            ) from exc
        os.truncate(handle, 0)
        os.write(handle, str(os.getpid()).encode("ascii"))
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            self._unlock(self._handle)
        finally:
            os.close(self._handle)
            self._handle = None

    # -- plattformabhaengiger Teil -----------------------------------------
    @staticmethod
    def _lock(handle: int) -> None:
        if sys.platform == "win32":  # pragma: no cover -- plattformabhaengig
            import msvcrt

            msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(handle: int) -> None:
        if sys.platform == "win32":  # pragma: no cover -- plattformabhaengig
            import msvcrt

            os.lseek(handle, 0, os.SEEK_SET)
            msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_UN)

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
