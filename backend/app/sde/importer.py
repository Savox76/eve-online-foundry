"""Der SDE-Importer.

Aufruf::

    python -m app.sde.importer --source ../demo/sde --build demo-001
    python -m app.sde.importer --source ~/Downloads/eve-...-jsonl.zip --report

**Wie "der alte Datensatz bleibt stehen, bis der neue vollstaendig ist"
(Kapitel 5) hier umgesetzt ist:** der gesamte Import laeuft in *einer*
Transaktion. Bricht er in der Mitte ab -- kaputte Datei, voller Datentraeger,
Strom weg --, macht SQLite den ganzen Vorgang rueckgaengig und die
Anwendung arbeitet unveraendert mit dem vorherigen Stand weiter. Es gibt
keinen Zwischenzustand, in dem halb importierte Typen zu falschen Rechnungen
fuehren.

``PRAGMA defer_foreign_keys`` schiebt die Fremdschluesselpruefung ans Ende der
Transaktion. Ohne das muesste innerhalb der Transaktion in strenger
Abhaengigkeitsreihenfolge geloescht und eingefuegt werden -- geprueft wird so
trotzdem, nur eben einmal am Schluss.

Geschrieben wird bewusst mit ``sqlite3`` statt ueber das ORM: ein Vollimport
sind Millionen Zeilen, und ``executemany`` ist dafuer um Groessenordnungen
schneller als einzelne ORM-Objekte.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.paths import database_path
from app.sde.datasets import DATASETS, Dataset
from app.sde.loader import SdeSource, SdeSourceError

logger = logging.getLogger(__name__)

#: Zeilen je ``executemany``. Gross genug, dass der Aufwand je Aufruf nicht
#: ins Gewicht faellt, klein genug, dass der Speicher flach bleibt.
BATCH_SIZE = 5_000


class SdeImportError(RuntimeError):
    """Der Import ist fehlgeschlagen. Die Datenbank ist unveraendert."""


def report(source_path: Path) -> dict[str, str | None]:
    """Sagt, welche Dateien gefunden wurden -- ohne etwas zu schreiben.

    Der erste Aufruf bei einem neuen Export. CCP hat die Benennung zwischen
    Formaten schon geaendert; das hier vorher zu sehen ist billiger, als es
    mitten im Import zu merken.
    """
    with SdeSource(source_path) as source:
        return {dataset.name: source.find(dataset.filenames) for dataset in DATASETS}


def import_sde(
    source_path: Path,
    *,
    db_path: Path | None = None,
    build: str | None = None,
    source_url: str = "",
) -> dict[str, int]:
    """Importiert einen Export vollstaendig. Liefert die Zeilenzahl je Tabelle."""
    target = db_path or database_path()
    if not target.exists():
        raise SdeImportError(
            f"Keine Datenbank unter {target}. Erst `alembic upgrade head` laufen lassen."
        )

    build_name = build or _derive_build_name(source_path)
    started = time.monotonic()
    counts: dict[str, int] = defaultdict(int)

    connection = sqlite3.connect(target, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("BEGIN IMMEDIATE")
        # Ab hier bis COMMIT sieht die Anwendung weiterhin den alten Stand.
        connection.execute("PRAGMA defer_foreign_keys=ON")

        with SdeSource(source_path) as source:
            _clear_tables(connection)
            for dataset in DATASETS:
                member = source.find(dataset.filenames)
                if member is None:
                    if dataset.required:
                        raise SdeImportError(
                            f"Pflichtdatei fuer '{dataset.name}' fehlt im Export. "
                            f"Erwartet wurde eine von: {', '.join(dataset.filenames)}. "
                            "Mit --report nachsehen, was tatsaechlich enthalten ist."
                        )
                    logger.warning(
                        "Optionales Dataset '%s' fehlt im Export -- uebersprungen.", dataset.name
                    )
                    continue
                written = _import_dataset(connection, source, dataset, member)
                for table, rows in written.items():
                    counts[table] += rows

        _record_build(connection, build_name, source_url, dict(counts))
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()

    logger.info(
        "SDE-Import '%s' abgeschlossen: %d Zeilen in %.1f s",
        build_name,
        sum(counts.values()),
        time.monotonic() - started,
    )
    return dict(counts)


def _clear_tables(connection: sqlite3.Connection) -> None:
    """Leert alle ``sde_``-Tabellen -- und ausschliesslich diese.

    ``esi_`` und ``app_`` werden hier nicht angefasst. Das ist die
    Entwurfsregel aus Kapitel 7 und der Grund, warum ein Reimport nicht
    gefaehrlich ist.
    """
    for dataset in reversed(DATASETS):
        for table in reversed(dataset.tables):
            # `table` stammt ausschliesslich aus DATASETS, einer festen
            # Konstante im Code. Fremdeingabe kann hier nicht landen, und
            # SQLite erlaubt an dieser Stelle keinen Parameter.
            connection.execute(f"DELETE FROM {table}")  # nosec B608


def _import_dataset(
    connection: sqlite3.Connection, source: SdeSource, dataset: Dataset, member: str
) -> dict[str, int]:
    buffers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    written: dict[str, int] = defaultdict(int)

    for raw in source.read_lines(member):
        for table, row in dataset.expand(raw):
            buffers[table].append(row)
            if len(buffers[table]) >= BATCH_SIZE:
                written[table] += _flush(connection, table, buffers[table])
                buffers[table].clear()

    for table, rows in buffers.items():
        if rows:
            written[table] += _flush(connection, table, rows)

    logger.info(
        "%s aus %s: %s",
        dataset.name,
        member,
        ", ".join(f"{table}={count}" for table, count in sorted(written.items())) or "leer",
    )
    return dict(written)


def _flush(connection: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> int:
    columns = list(rows[0])
    placeholders = ", ".join(f":{column}" for column in columns)
    statement = f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    connection.executemany(statement, rows)
    return len(rows)


def _record_build(
    connection: sqlite3.Connection, build: str, source_url: str, counts: dict[str, int]
) -> None:
    """Schreibt den Build-Eintrag und macht ihn zum aktiven Stand."""
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
    connection.execute("UPDATE sde_builds SET is_active = 0")
    connection.execute(
        """
        INSERT INTO sde_builds (build, source_url, started_at, completed_at, row_counts, is_active)
        VALUES (:build, :source_url, :now, :now, :counts, 1)
        ON CONFLICT(build) DO UPDATE SET
            source_url = excluded.source_url,
            completed_at = excluded.completed_at,
            row_counts = excluded.row_counts,
            is_active = 1
        """,
        {
            "build": build,
            "source_url": source_url,
            "now": now,
            "counts": json.dumps(counts, sort_keys=True),
        },
    )


def active_build(db_path: Path | None = None) -> dict[str, Any] | None:
    """Welcher SDE-Stand gilt gerade. ``None`` = noch keiner importiert."""
    target = db_path or database_path()
    if not target.exists():
        return None
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT build, source_url, completed_at, row_counts "
            "FROM sde_builds WHERE is_active = 1 ORDER BY completed_at DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        # Tabelle gibt es noch nicht -- die Migration lief noch nicht.
        return None
    finally:
        connection.close()
    if row is None:
        return None
    return {
        "build": row["build"],
        "source_url": row["source_url"],
        "completed_at": row["completed_at"],
        "row_counts": json.loads(row["row_counts"] or "{}"),
    }


def _derive_build_name(source_path: Path) -> str:
    stem = source_path.stem or source_path.name
    return f"{stem}-{datetime.now(UTC):%Y%m%d}"


def _iter_report_lines(found: dict[str, str | None]) -> Iterator[str]:
    for dataset in DATASETS:
        member = found.get(dataset.name)
        mark = "gefunden " if member else ("FEHLT    " if dataset.required else "fehlt (optional)")
        yield f"  {mark}  {dataset.name:<20} {member or ', '.join(dataset.filenames)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.sde.importer",
        description="Importiert einen EVE Static Data Export (JSONL) in die Foundry-Datenbank.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="ZIP-Archiv des Exports oder ein Verzeichnis mit .jsonl-Dateien",
    )
    parser.add_argument("--db", type=Path, default=None, help="Abweichender Datenbankpfad")
    parser.add_argument("--build", default=None, help="Kennung des Exports")
    parser.add_argument("--source-url", default="", help="Herkunfts-URL fuer das Protokoll")
    parser.add_argument(
        "--report",
        action="store_true",
        help="Nur nachsehen, welche Dateien der Export enthaelt -- schreibt nichts",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        if args.report:
            print(f"Export: {args.source}")
            for line in _iter_report_lines(report(args.source)):
                print(line)
            return 0

        counts = import_sde(
            args.source, db_path=args.db, build=args.build, source_url=args.source_url
        )
        print(f"Importiert: {sum(counts.values())} Zeilen")
        for table, count in sorted(counts.items()):
            print(f"  {count:>10,}  {table}")
        return 0
    except (SdeImportError, SdeSourceError) as exc:
        print(f"Import fehlgeschlagen: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
