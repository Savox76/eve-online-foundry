"""Konfiguration.

Zwei Werte in dieser Datei sind keine Einstellung, sondern eine Entscheidung,
und stehen deshalb als Konstante im Code statt in einer .env:

``ESI_COMPATIBILITY_DATE``
    ESI hat die ``/v1/``-, ``/v5/``-Pfade durch ein datumsbasiertes Modell
    abgeloest. Ohne den Header nutzt ESI das *aelteste* verfuegbare Datum --
    das will man nie. Als Konstante wird das Anheben ein bewusster, testbarer
    Commit statt eines schleichenden Drifts (Kapitel 6).

``TRADE_HUBS``
    Die fuenf Handelszentren. Eine Konfigurationsdatei dafuer pflegt niemand,
    und die IDs aendern sich nicht (Kapitel 10).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__

# ---------------------------------------------------------------------------
# ESI-Konstanten
# ---------------------------------------------------------------------------

#: Wird bei JEDEM ESI-Request als ``X-Compatibility-Date`` gesetzt.
#: CCP sichert mindestens ein Jahr Rueckwaertskompatibilitaet zu; halbjaehrlich
#: pruefen und dann bewusst anheben. Issue-Label dafuer: ``esi-change``.
ESI_COMPATIBILITY_DATE = "2026-09-01"

ESI_BASE_URL = "https://esi.evetech.net"
SSO_BASE_URL = "https://login.eveonline.com"
SSO_AUTHORIZE_URL = f"{SSO_BASE_URL}/v2/oauth/authorize"
SSO_TOKEN_URL = f"{SSO_BASE_URL}/v2/oauth/token"
SSO_JWKS_URL = f"{SSO_BASE_URL}/oauth/jwks"
SSO_ISSUERS = frozenset({"login.eveonline.com", "https://login.eveonline.com"})
SSO_EXPECTED_AUDIENCE = "EVE Online"

REPOSITORY_URL = "https://github.com/Savox76/eve-online-foundry"


@dataclass(frozen=True, slots=True)
class TradeHub:
    """Ein Handelszentrum. Station *und* Region, weil beide gebraucht werden."""

    name: str
    region_id: int
    region_name: str
    station_id: int


#: Der Scanner deckt genau diese fuenf ab -- nicht ganz New Eden (Kapitel 10).
TRADE_HUBS: tuple[TradeHub, ...] = (
    TradeHub("Jita", 10000002, "The Forge", 60003760),
    TradeHub("Amarr", 10000043, "Domain", 60008494),
    TradeHub("Dodixie", 10000032, "Sinq Laison", 60011866),
    TradeHub("Rens", 10000030, "Heimatar", 60004588),
    TradeHub("Hek", 10000042, "Metropolis", 60005686),
)


# ---------------------------------------------------------------------------
# Einstellungen
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Aus Umgebung und ``.env`` gelesen, Praefix ``FOUNDRY_``."""

    model_config = SettingsConfigDict(
        env_prefix="FOUNDRY_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- Netz ---------------------------------------------------------------
    #: Nur Loopback. Ein Bind auf 0.0.0.0 macht die Anwendung netzweit
    #: erreichbar und ist hier immer ein Fehler (Kapitel 18).
    host: Literal["127.0.0.1", "localhost", "::1"] = "127.0.0.1"
    port: int = 8000

    #: Von der Tauri-Schale beim Start erzeugt und durchgereicht. Leer heisst:
    #: Entwicklungsbetrieb, das Backend erzeugt selbst eins.
    session_secret: str = ""

    # -- ESI / SSO ----------------------------------------------------------
    #: Oeffentlich. Native Anwendungen haben kein Client Secret (Kapitel 4).
    esi_client_id: str = ""
    sso_callback_port: int = 8765
    #: Kontaktadresse im User-Agent. Ohne sie ist der User-Agent unvollstaendig.
    contact_email: str = ""

    # -- Betrieb ------------------------------------------------------------
    data_dir: str = ""
    log_level: str = "INFO"

    #: Nur fuer Tests: ueberspringt Migration, Scheduler und Instanzsperre.
    testing: bool = Field(default=False, exclude=True)

    @property
    def sso_callback_url(self) -> str:
        """Muss im Developers-Portal exakt so eingetragen sein."""
        return f"http://localhost:{self.sso_callback_port}/callback"

    @property
    def user_agent(self) -> str:
        """Pflicht, nicht Hoeflichkeit (Kapitel 6).

        CCP kuendigt Sperren fuer Anwendungen an, die sich nicht identifizieren.
        Fehlt die Kontaktadresse, steht das ausdruecklich drin, statt die Zeile
        stillschweigend kuerzer zu machen -- sonst faellt es nie auf.
        """
        contact = self.contact_email or "no-contact-configured"
        return f"NewEdenFoundry/{__version__} ({contact}; +{REPOSITORY_URL}) httpx"


_settings: Settings | None = None


def get_settings() -> Settings:
    """Zwischengespeicherte Einstellungen."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_cache() -> None:
    """Nur fuer Tests."""
    global _settings
    _settings = None
