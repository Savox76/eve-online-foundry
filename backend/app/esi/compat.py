"""Kompatibilitaetsdatum.

ESI hat versionierte Pfade (``/v1/``, ``/v5/``) durch ein datumsbasiertes
Modell abgeloest. Jeder Request schickt ``X-Compatibility-Date``. Ohne den
Header nutzt ESI das **aelteste** verfuegbare Datum -- also den Stand, den
niemand will. Zukunftsdaten werden abgelehnt; der Stichtag rollt taeglich um
11:00 UTC.

Das Datum steht als eine Konstante in ``core/config.py``. Diese Datei setzt sie
durch und prueft sie beim Start: ein Datum, das aus der Zukunft stammt oder
sich der Ein-Jahres-Grenze naehert, faellt hier auf und nicht erst, wenn eine
Route wegbricht.
"""

from __future__ import annotations

import datetime as dt
import logging

from app.core.config import ESI_COMPATIBILITY_DATE

logger = logging.getLogger(__name__)

COMPATIBILITY_HEADER = "X-Compatibility-Date"

#: CCP sichert mindestens ein Jahr Rueckwaertskompatibilitaet zu.
GUARANTEED_DAYS = 365
#: Ab hier warnen -- rund zwei Monate Vorlauf, um in Ruhe anzuheben.
WARN_AFTER_DAYS = 300


class CompatibilityDateError(ValueError):
    """Das konfigurierte Kompatibilitaetsdatum ist unbrauchbar."""


def parse_compatibility_date(value: str = ESI_COMPATIBILITY_DATE) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise CompatibilityDateError(
            f"ESI_COMPATIBILITY_DATE ist kein ISO-Datum: {value!r}"
        ) from exc


def check_compatibility_date(
    value: str = ESI_COMPATIBILITY_DATE, *, today: dt.date | None = None
) -> int:
    """Prueft das Datum und liefert sein Alter in Tagen.

    Wirft bei einem Zukunftsdatum -- ESI wuerde solche Requests ablehnen, und
    das beim Start zu merken ist deutlich billiger als mitten im Sync.
    Ein alterndes Datum wird nur geloggt: die Routen funktionieren noch, aber
    der Umstellungstermin rueckt naeher.
    """
    parsed = parse_compatibility_date(value)
    now = today or dt.datetime.now(dt.UTC).date()
    age = (now - parsed).days

    if age < 0:
        raise CompatibilityDateError(
            f"ESI_COMPATIBILITY_DATE {value} liegt in der Zukunft -- ESI lehnt das ab."
        )
    if age >= GUARANTEED_DAYS:
        logger.error(
            "Kompatibilitaetsdatum %s ist %d Tage alt und ausserhalb der zugesicherten "
            "Rueckwaertskompatibilitaet. Routen koennen jederzeit wegbrechen -- anheben "
            "und gegen esi.evetech.net/meta/openapi.json pruefen.",
            value,
            age,
        )
    elif age >= WARN_AFTER_DAYS:
        logger.warning(
            "Kompatibilitaetsdatum %s ist %d Tage alt. Anheben einplanen (Label esi-change).",
            value,
            age,
        )
    return age
