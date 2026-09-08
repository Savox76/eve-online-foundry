#!/usr/bin/env python3
"""Erzeugt das Anwendungssymbol.

Der Plan sieht in ``assets/`` genau eine Vorlage vor, aus der der Rest erzeugt
wird. Dieses Skript ist diese Vorlage-Erzeugung: es schreibt
``assets/app-icon.png`` in 1024x1024 und die PNG-Groessen, die Tauri direkt
einbindet.

Das ``.ico`` fuer Windows entsteht hier mit -- die Installer brauchen es, und
ein Symbol, das nur auf dem Rechner des Entwicklers erzeugt wird, faellt
irgendwann aus dem Tritt. Fuer ``.icns`` unter macOS weiterhin::

    npm --prefix frontend run tauri icon ../assets/app-icon.png

Bewusst ohne Pillow: eine Bildbibliothek als Abhaengigkeit, nur um einmal ein
Sechseck zu zeichnen, waere ein schlechter Tausch. PNG selbst zu schreiben ist
zlib plus vier Bloecke.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GROUND = (0x0B, 0x10, 0x15)
SURFACE = (0x13, 0x1B, 0x22)
ACCENT = (0xEF, 0x8F, 0x42)
COOL = (0x63, 0xA9, 0xC9)

#: Groessen, die ``tauri.conf.json`` unter ``bundle.icon`` auffuehrt.
TAURI_SIZES = {
    "32x32.png": 32,
    "128x128.png": 128,
    "128x128@2x.png": 256,
    "icon.png": 512,
}

#: Groessen im ``.ico``. Die kleinen liegen als unkomprimiertes DIB darin, weil
#: der NSIS-Installer und die Verknuepfungen im Startmenue genau die lesen; die
#: grossen als PNG, sonst waere die Datei ein Vielfaches so gross.
ICO_SIZES = (16, 32, 48, 64, 128, 256)
ICO_ALS_PNG = 128


def _hexagon(cx: float, cy: float, radius: float) -> list[tuple[float, float]]:
    """Sechseck mit flacher Ober- und Unterkante."""
    import math

    return [
        (cx + radius * math.cos(math.radians(angle)), cy + radius * math.sin(math.radians(angle)))
        for angle in range(30, 390, 60)
    ]


def _inside(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    """Punkt-in-Polygon nach dem Strahlensatz-Verfahren."""
    x, y = point
    drin = False
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        if (y1 > y) != (y2 > y):
            schnitt = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < schnitt:
                drin = not drin
    return drin


def render(size: int) -> bytes:
    """Zeichnet das Symbol und liefert die rohen RGBA-Zeilen."""
    rows = bytearray()
    cx = cy = size / 2
    aussen = _hexagon(cx, cy, size * 0.40)
    innen = _hexagon(cx, cy, size * 0.31)

    # Ein Barren: unten breit, oben schmal -- das Ergebnis der Fertigung.
    barren_oben = size * 0.44
    barren_unten = size * 0.62
    barren_halb_unten = size * 0.17
    barren_halb_oben = size * 0.11

    for y in range(size):
        rows.append(0)  # Filtertyp "None" je Zeile
        for x in range(size):
            px = (x + 0.5, y + 0.5)
            farbe = GROUND

            if _inside(px, aussen):
                farbe = SURFACE if _inside(px, innen) else ACCENT

            if barren_oben <= px[1] <= barren_unten:
                anteil = (px[1] - barren_oben) / (barren_unten - barren_oben)
                halb = barren_halb_oben + anteil * (barren_halb_unten - barren_halb_oben)
                if abs(px[0] - cx) <= halb:
                    farbe = ACCENT if anteil > 0.22 else COOL

            rows.extend(farbe)
            rows.append(0xFF)
    return bytes(rows)


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def png_bytes(size: int) -> bytes:
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(render(size), 9))
        + _chunk(b"IEND", b"")
    )


def write_png(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes(size))
    print(f"  {path.relative_to(ROOT)}  ({size}x{size})")


def _dib(size: int) -> bytes:
    """Ein Symbol im BMP-Teil des ICO: Kopf, BGRA von unten nach oben, Maske."""
    roh = render(size)
    stride = size * 4 + 1  # render() setzt je Zeile ein PNG-Filterbyte davor

    xor = bytearray()
    for y in reversed(range(size)):  # DIBs stehen auf dem Kopf
        zeile = roh[y * stride + 1 : (y + 1) * stride]
        for x in range(size):
            r, g, b, a = zeile[x * 4 : x * 4 + 4]
            xor += bytes((b, g, r, a))

    # Die 1-Bit-Maske verlangt das Format auch bei 32 Bit. Sie bleibt leer,
    # weil die Deckkraft schon im Alphakanal steht -- fehlt sie ganz, zeigt
    # Windows das Symbol als schwarzes Rechteck.
    maske = bytes(((size + 31) // 32) * 4 * size)

    kopf = struct.pack(
        "<IiiHHIIiiII",
        40,  # biSize
        size,  # biWidth
        size * 2,  # biHeight -- Bild und Maske uebereinander
        1,  # biPlanes
        32,  # biBitCount
        0,  # biCompression: BI_RGB
        len(xor) + len(maske),  # biSizeImage
        0,
        0,
        0,
        0,
    )
    return kopf + bytes(xor) + maske


def write_ico(path: Path) -> None:
    """Schreibt das Windows-Symbol -- ohne das bauen MSI und NSIS nicht."""
    bilder = [
        (size, png_bytes(size) if size >= ICO_ALS_PNG else _dib(size)) for size in ICO_SIZES
    ]

    verzeichnis = bytearray(struct.pack("<HHH", 0, 1, len(bilder)))
    versatz = 6 + 16 * len(bilder)
    daten = bytearray()
    for size, blob in bilder:
        kante = 0 if size >= 256 else size  # 256 wird als 0 notiert
        verzeichnis += struct.pack("<BBBBHHII", kante, kante, 0, 0, 1, 32, len(blob), versatz)
        versatz += len(blob)
        daten += blob

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(verzeichnis) + bytes(daten))
    groessen = ", ".join(str(s) for s in ICO_SIZES)
    print(f"  {path.relative_to(ROOT)}  ({groessen})")


def main() -> int:
    print("Anwendungssymbol wird erzeugt:")
    write_png(ROOT / "assets" / "app-icon.png", 1024)
    for name, size in TAURI_SIZES.items():
        write_png(ROOT / "src-tauri" / "icons" / name, size)
    write_ico(ROOT / "src-tauri" / "icons" / "icon.ico")
    # Im Entwicklungsbetrieb laeuft die Oberflaeche im Browser und braucht ein
    # eigenes Favicon -- aus derselben Quelle, damit die beiden nicht
    # auseinanderlaufen.
    write_png(ROOT / "frontend" / "public" / "favicon.png", 64)
    print("\nFuer .icns (macOS) danach:\n  npm run tauri icon ../assets/app-icon.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
