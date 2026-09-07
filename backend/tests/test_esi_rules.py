"""Die Regeln, die CCP durchsetzt.

Kompatibilitaetsdatum, Scope-Normalisierung, Kostentabelle und Circuit
Breaker. Alles hier hat denselben Hintergrund: CCP kuendigt Sperren fuer
Anwendungen an, die Caching umgehen oder sich nicht identifizieren.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.core.config import Settings
from app.core.ratelimit import (
    COST_2XX,
    COST_3XX,
    COST_4XX,
    COST_5XX,
    EsiBudget,
    counts_against_error_limit,
    jitter,
    request_cost,
)
from app.esi.compat import (
    GUARANTEED_DAYS,
    WARN_AFTER_DAYS,
    CompatibilityDateError,
    check_compatibility_date,
)
from app.esi.scopes import BASE_SCOPES, ScopeTier, missing_scopes, normalize_scp_claim, scopes_for


# -- Kompatibilitaetsdatum ---------------------------------------------------
def test_zukunftsdatum_wird_abgelehnt() -> None:
    """ESI lehnt Zukunftsdaten ab -- das soll beim Start auffallen, nicht im Sync."""
    with pytest.raises(CompatibilityDateError, match="Zukunft"):
        check_compatibility_date("2026-12-01", today=dt.date(2026, 9, 7))


def test_kein_iso_datum_wird_abgelehnt() -> None:
    with pytest.raises(CompatibilityDateError):
        check_compatibility_date("01.09.2026")


def test_alter_wird_in_tagen_gemeldet() -> None:
    assert check_compatibility_date("2026-09-01", today=dt.date(2026, 9, 7)) == 6


def test_alterndes_datum_warnt_aber_bricht_nicht_ab(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Die Routen laufen noch -- gemeldet gehoert es trotzdem."""
    base = dt.date(2026, 9, 7)
    old = base - dt.timedelta(days=WARN_AFTER_DAYS + 1)
    with caplog.at_level("WARNING"):
        age = check_compatibility_date(old.isoformat(), today=base)
    assert age > WARN_AFTER_DAYS
    assert "esi-change" in caplog.text


def test_ueberfaelliges_datum_wird_als_fehler_geloggt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    base = dt.date(2026, 9, 7)
    ancient = base - dt.timedelta(days=GUARANTEED_DAYS + 10)
    with caplog.at_level("ERROR"):
        check_compatibility_date(ancient.isoformat(), today=base)
    assert "Rueckwaertskompatibilitaet" in caplog.text


# -- User-Agent --------------------------------------------------------------
def test_user_agent_enthaelt_version_kontakt_und_repo() -> None:
    """Pflicht, nicht Hoeflichkeit (Kapitel 6)."""
    agent = Settings(contact_email="pilot@example.invalid").user_agent
    assert agent.startswith("NewEdenFoundry/")
    assert "pilot@example.invalid" in agent
    assert "github.com/Savox76" in agent


def test_fehlende_kontaktadresse_faellt_im_user_agent_auf() -> None:
    """Stillschweigend kuerzen waere schlimmer -- dann faellt es nie auf."""
    assert "no-contact-configured" in Settings(contact_email="").user_agent


# -- Scopes ------------------------------------------------------------------
def test_scp_claim_als_string_wird_zur_liste() -> None:
    """Der Fallstrick: bei genau einem Scope liefert das JWT einen String."""
    assert normalize_scp_claim("publicData") == ("publicData",)


def test_scp_claim_als_liste_bleibt_liste() -> None:
    assert normalize_scp_claim(["a", "b"]) == ("a", "b")


def test_leerer_scp_claim_ist_leer() -> None:
    assert normalize_scp_claim(None) == ()
    assert normalize_scp_claim("") == ()


def test_fehlende_scopes_werden_benannt() -> None:
    fehlt = missing_scopes("publicData", BASE_SCOPES)
    assert "esi-assets.read_assets.v1" in fehlt
    assert "publicData" not in fehlt


def test_scope_pakete_sind_dublettenfrei() -> None:
    kombiniert = scopes_for(ScopeTier.BASE, ScopeTier.BASE, ScopeTier.CORP)
    assert len(kombiniert) == len(set(kombiniert))


# -- Kosten ------------------------------------------------------------------
@pytest.mark.parametrize(
    ("status", "kosten"),
    [(200, COST_2XX), (204, COST_2XX), (304, COST_3XX), (403, COST_4XX), (500, COST_5XX)],
)
def test_kostentabelle(status: int, kosten: int) -> None:
    assert request_cost(status) == kosten


def test_ein_304_ist_billiger_als_ein_200() -> None:
    """Der ganze Grund, warum sauberes Caching sich doppelt auszahlt."""
    assert request_cost(304) < request_cost(200)


def test_ein_client_fehler_kostet_mehr_als_zwei_erfolge() -> None:
    assert request_cost(400) > 2 * request_cost(304)


@pytest.mark.parametrize(
    ("status", "zaehlt"), [(200, False), (304, False), (400, True), (500, True)]
)
def test_fehlerbudget_zaehlt_nur_nicht_2xx_3xx(status: int, zaehlt: bool) -> None:
    assert counts_against_error_limit(status) is zaehlt


def test_jitter_bleibt_in_der_spanne() -> None:
    """Feste Minuten sind der zuverlaessigste Weg, ein Rate Limit zu reissen."""
    werte = [jitter(600, spread=0.2) for _ in range(200)]
    assert all(480 <= wert <= 720 for wert in werte)
    assert len(set(werte)) > 100  # gestreut, nicht konstant


# -- Budget ------------------------------------------------------------------
async def test_budget_uebernimmt_die_server_wahrheit() -> None:
    """Bei Abweichung gilt der kleinere Wert -- der Server kennt den Stand."""
    budget = EsiBudget()
    await budget.acquire("assets")
    await budget.observe(
        status_code=200,
        group="assets",
        headers={"X-Ratelimit-Limit": "150", "X-Ratelimit-Remaining": "7"},
    )
    assert budget.snapshot()["groups"]["assets"]["remaining"] == 7.0


async def test_breaker_schliesst_vor_dem_nullpunkt() -> None:
    """Nicht erst bei 0 reagieren: unterwegs sind noch Antworten."""
    budget = EsiBudget(error_threshold=20)
    await budget.observe(
        status_code=200,
        group="assets",
        headers={"X-ESI-Error-Limit-Remain": "12", "X-ESI-Error-Limit-Reset": "45"},
    )
    assert budget.error_remain == 12
    assert budget.breaker_seconds_left() > 40


async def test_breaker_bleibt_offen_solange_das_budget_reicht() -> None:
    budget = EsiBudget(error_threshold=20)
    await budget.observe(
        status_code=200, group="assets", headers={"X-ESI-Error-Limit-Remain": "95"}
    )
    assert budget.breaker_seconds_left() == 0.0


async def test_420_sperrt_alle_gruppen() -> None:
    """Nach einem 420 antwortet ESI auf *jeder* Route mit 420."""
    budget = EsiBudget()
    await budget.observe(status_code=420, group="assets", headers={"X-ESI-Error-Limit-Reset": "58"})
    assert budget.breaker_seconds_left() > 50


async def test_429_pausiert_nur_die_betroffene_gruppe() -> None:
    budget = EsiBudget()
    await budget.observe(status_code=429, group="markets", headers={"Retry-After": "30"})
    snapshot = budget.snapshot()["groups"]
    assert snapshot["markets"]["blocked_seconds_left"] > 25
    assert budget.breaker_seconds_left() == 0.0


async def test_gruppe_aus_dem_header_sticht_die_annahme_aus() -> None:
    """Die Wahrheit steht im X-Ratelimit-Group-Header, nicht in unserer Tabelle."""
    budget = EsiBudget()
    await budget.observe(
        status_code=200,
        group="assets",
        headers={"X-Ratelimit-Group": "bulk", "X-Ratelimit-Remaining": "3"},
    )
    assert "bulk" in budget.snapshot()["groups"]
