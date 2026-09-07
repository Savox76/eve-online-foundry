#!/usr/bin/env python3
"""Buendelt das Backend als Sidecar-Binaerdatei fuer die Tauri-Schale.

Der Stolperstein, der jeden einmal erwischt: **der Dateiname muss das
Rust-Target-Triple tragen.** Tauri sucht ``binaries/foundry-backend-<triple>``
und findet ohne das Suffix schlicht nichts -- ohne verwertbare Fehlermeldung,
die Anwendung startet einfach ohne Backend.

Aufruf::

    python scripts/build_sidecar.py            # baut fuer diese Plattform
    python scripts/build_sidecar.py --check    # sagt nur, wie die Datei heissen muss
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TARGET_DIR = ROOT / "src-tauri" / "binaries"
BINARY_STEM = "foundry-backend"


def target_triple() -> str:
    """Das Target-Triple, das ``rustc`` fuer diese Plattform meldet."""
    try:
        output = subprocess.run(
            ["rustc", "-vV"], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            "rustc liess sich nicht aufrufen -- ohne Rust-Toolchain ist das "
            f"Target-Triple nicht zu ermitteln: {exc}"
        ) from exc

    for line in output.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("rustc -vV meldet kein 'host:' -- unerwartete Ausgabe.")


def sidecar_name(triple: str) -> str:
    suffix = ".exe" if triple.endswith("windows-msvc") or sys.platform == "win32" else ""
    return f"{BINARY_STEM}-{triple}{suffix}"


def build(triple: str) -> Path:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    ziel = TARGET_DIR / sidecar_name(triple)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        BINARY_STEM,
        "--distpath",
        str(TARGET_DIR),
        "--workpath",
        str(BACKEND / "build"),
        "--specpath",
        str(BACKEND / "build"),
        "--clean",
        "--noconfirm",
        # Alembic laedt die Migrationen zur Laufzeit ueber das Dateisystem --
        # ohne diese Daten migriert die gebuendelte Anwendung nicht und startet
        # damit gar nicht.
        "--add-data",
        f"{BACKEND / 'alembic'}{';' if sys.platform == 'win32' else ':'}alembic",
        "--add-data",
        f"{BACKEND / 'alembic.ini'}{';' if sys.platform == 'win32' else ':'}.",
        # Was PyInstaller ueber dynamische Importe nicht findet.
        "--hidden-import",
        "aiosqlite",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.protocols.http.h11_impl",
        "--hidden-import",
        "uvicorn.lifespan.on",
        str(BACKEND / "app" / "main.py"),
    ]

    print("PyInstaller:", " ".join(command))
    subprocess.run(command, check=True, cwd=BACKEND)

    gebaut = TARGET_DIR / (BINARY_STEM + (".exe" if sys.platform == "win32" else ""))
    if not gebaut.exists():
        raise SystemExit(f"PyInstaller hat {gebaut} nicht erzeugt.")

    if ziel.exists():
        ziel.unlink()
    gebaut.rename(ziel)
    ziel.chmod(0o755)
    return ziel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Nur den erwarteten Dateinamen ausgeben, nichts bauen",
    )
    args = parser.parse_args(argv)

    triple = target_triple()
    if args.check:
        print(f"Target-Triple: {triple}")
        print(f"Tauri erwartet: src-tauri/binaries/{sidecar_name(triple)}")
        return 0

    ziel = build(triple)
    print(f"\nSidecar gebaut: {ziel.relative_to(ROOT)}")
    print("Die Schale findet sie ueber 'externalBin' in tauri.conf.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
