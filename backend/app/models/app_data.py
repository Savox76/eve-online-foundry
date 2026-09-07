"""Eigene Daten (Praefix ``app_``).

Nur diese Tabellen sind unersetzlich und gehoeren ins Backup. Ein SDE-Reimport
oder ein kompletter ESI-Resync darf sie niemals beruehren.

Phase 0 braucht davon genau eine: einen Schluessel-Wert-Speicher fuer
Betriebszustand, der eine Neuinstallation ueberleben soll. Doktrinen,
Projekte, Preisprofile und Bauregeln kommen in den Phasen 4 bis 7 dazu.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class AppSetting(Base):
    """Schluessel-Wert-Speicher fuer Einstellungen und Betriebszustand.

    Bewusst getrennt von ``.env``: hier steht, was die *Anwendung* sich merkt
    (etwa wann zuletzt ein SDE-Import lief), nicht was der Benutzer einstellt.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[dt.datetime] = mapped_column(default=utcnow)
