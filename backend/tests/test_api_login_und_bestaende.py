"""Die Aussenkante von Phase 1 und dem Durchstich."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from tests import factories


@pytest.fixture
def mit_demo_sde(isolated_data_dir: Path, demo_sde: Path) -> Path:
    """Eine Datenbank mit den synthetischen Static-Data-Testdaten."""
    from app.core.migrate import upgrade_to_head
    from app.core.paths import database_path
    from app.sde.importer import import_sde

    upgrade_to_head()
    import_sde(demo_sde, db_path=database_path(), build="test")
    return database_path()


def _lege_bestand_an(db: Path) -> None:
    """Schreibt Bestaende direkt in die Datei -- ohne ESI, ohne Login."""
    jetzt = dt.datetime.now(dt.UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO esi_characters (character_id, name, owner_hash, connected_at, status)"
                " VALUES (:cid, :name, 'x', :now, 'ok')"
            ),
            {"cid": factories.CHARACTER_ID, "name": factories.CHARACTER_NAME, "now": jetzt},
        )
        zeilen = [
            # Duraluminium direkt in der Station
            (1, 9_900_001, 32_000, factories.STATION_ID, "station", factories.STATION_ID, 0, None),
            # Ein benannter Container in der Station …
            (2, 9_900_010, 1, factories.STATION_ID, "station", factories.STATION_ID, 0, "Kiste A"),
            # … und Cindergrain darin
            (3, 9_900_003, 6_000, 2, "item", factories.STATION_ID, 1, None),
            # Etwas in einer Struktur ohne Docking-Zugriff
            (4, 9_900_002, 8_000, 1_035_000_000_001, "structure", 1_035_000_000_001, 0, None),
        ]
        for item_id, type_id, menge, ort, art, wurzel, tiefe, name in zeilen:
            connection.execute(
                text(
                    "INSERT INTO esi_assets (item_id, owner_type, owner_id, type_id, quantity,"
                    " location_id, location_flag, location_type, is_singleton, is_blueprint_copy,"
                    " root_location_id, depth, name, fetched_at)"
                    " VALUES (:i, 'character', :o, :t, :q, :l, 'Hangar', :a, :s, 0, :r, :d, :n, :f)"
                ),
                {
                    "i": item_id,
                    "o": factories.CHARACTER_ID,
                    "t": type_id,
                    "q": menge,
                    "l": ort,
                    "a": art,
                    "s": 1 if name else 0,
                    "r": wurzel,
                    "d": tiefe,
                    "n": name,
                    "f": jetzt,
                },
            )
        connection.execute(
            text(
                "INSERT INTO esi_asset_changes (owner_type, owner_id, item_id, type_id,"
                " location_id, kind, quantity_before, quantity_after, observed_at)"
                " VALUES ('character', :o, 1, 9900001, :l, 'quantity', 34000, 32000, :f)"
            ),
            {"o": factories.CHARACTER_ID, "l": factories.STATION_ID, "f": jetzt},
        )
    engine.dispose()


# -- Scopes und Anmeldung ----------------------------------------------------
def test_scope_pakete_werden_gestaffelt_angeboten(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Ein erster Login, der alles anfragt, erzeugt ein unlesbares Consent-Fenster."""
    antwort = client.get("/api/v1/auth/scopes", headers=auth_headers)
    assert antwort.status_code == 200

    pakete = {eintrag["tier"]: eintrag for eintrag in antwort.json()}
    assert "publicData" in pakete["base"]["scopes"]
    assert pakete["base"]["description"]
    # Corp-Scopes nennen die In-Game-Rolle, ohne die sie wirkungslos sind.
    assert pakete["corp"]["required_roles"]["esi-assets.read_corporation_assets.v1"] == "Director"


def test_anmeldung_ohne_client_id_meldet_das_deutlich(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    antwort = client.post("/api/v1/auth/login", json={"tiers": ["base"]}, headers=auth_headers)
    assert antwort.status_code == 503
    assert "Client-ID" in antwort.json()["detail"]


def test_unbekanntes_scope_paket_wird_abgelehnt(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    antwort = client.post(
        "/api/v1/auth/login", json={"tiers": ["gibtsnicht"]}, headers=auth_headers
    )
    assert antwort.status_code == 400


def test_unbekannter_anmeldeversuch_ist_ein_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    assert client.get("/api/v1/auth/login/xyz", headers=auth_headers).status_code == 404


def test_ohne_charaktere_ist_die_liste_leer(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    antwort = client.get("/api/v1/auth/characters", headers=auth_headers)
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["characters"] == []
    # Wo die Tokens liegen wuerden, gehoert sichtbar gemacht.
    assert daten["token_storage"] in {"keyring", "encrypted-file"}


def test_unbekannten_charakter_entfernen_ist_ein_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    assert client.delete("/api/v1/auth/characters/9000999", headers=auth_headers).status_code == 404


def test_bestaende_eines_unbekannten_charakters(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    antwort = client.post("/api/v1/assets/sync?character_id=9000999", headers=auth_headers)
    assert antwort.status_code == 404


# -- Bestandstabelle ---------------------------------------------------------
def test_bestandstabelle_loest_typen_und_orte_auf(
    mit_demo_sde: Path, client: TestClient, auth_headers: dict[str, str]
) -> None:
    _lege_bestand_an(mit_demo_sde)

    antwort = client.get("/api/v1/assets", headers=auth_headers)
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["total"] == 4

    zeilen = {zeile["item_id"]: zeile for zeile in daten["rows"]}
    assert zeilen[1]["type_name"] == "Duraluminium"
    assert zeilen[1]["group_name"] == "Demo Minerals"
    assert zeilen[1]["location_name"] == "Tenvar IV - Demo Assembly Plant"
    # Volumen mal Menge -- die Frage "passt das in einen Epithal?".
    assert zeilen[1]["total_volume"] == pytest.approx(320.0)

    # Was im Container liegt, nennt den Container beim Namen statt eine Item-ID.
    assert zeilen[3]["container_name"] == "Kiste A"
    assert zeilen[3]["depth"] == 1

    # Eine Struktur ohne Docking-Zugriff bekommt einen Rueckfallnamen, keine
    # leere Zelle -- die saehe aus wie ein Fehler.
    assert zeilen[4]["location_name"] == "Unbekannte Struktur #1035000000001"

    # Datenstand gehoert in jede Ansicht.
    assert daten["fetched_at"] is not None


def test_suche_filtert_auf_den_typnamen(
    mit_demo_sde: Path, client: TestClient, auth_headers: dict[str, str]
) -> None:
    _lege_bestand_an(mit_demo_sde)
    antwort = client.get("/api/v1/assets?search=cinder", headers=auth_headers)
    zeilen = antwort.json()["rows"]
    assert len(zeilen) == 1
    assert zeilen[0]["type_name"] == "Cindergrain"


def test_filter_auf_einen_ort(
    mit_demo_sde: Path, client: TestClient, auth_headers: dict[str, str]
) -> None:
    _lege_bestand_an(mit_demo_sde)
    antwort = client.get(f"/api/v1/assets?location_id={factories.STATION_ID}", headers=auth_headers)
    assert antwort.json()["total"] == 3


def test_orte_werden_zusammengefasst(
    mit_demo_sde: Path, client: TestClient, auth_headers: dict[str, str]
) -> None:
    _lege_bestand_an(mit_demo_sde)
    antwort = client.get("/api/v1/assets/locations", headers=auth_headers)
    orte = {eintrag["name"]: eintrag for eintrag in antwort.json()}

    assert orte["Tenvar IV - Demo Assembly Plant"]["stacks"] == 3
    assert orte["Tenvar IV - Demo Assembly Plant"]["items"] == 38_001
    assert "Unbekannte Struktur #1035000000001" in orte


def test_delta_ansicht_zeigt_die_differenz(
    mit_demo_sde: Path, client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Die taegliche Kontrollfrage: was hat sich seit gestern veraendert?"""
    _lege_bestand_an(mit_demo_sde)
    antwort = client.get("/api/v1/assets/changes", headers=auth_headers)
    zeilen = antwort.json()["rows"]

    assert len(zeilen) == 1
    assert zeilen[0]["kind"] == "quantity"
    assert zeilen[0]["type_name"] == "Duraluminium"
    assert zeilen[0]["delta"] == -2000, "weniger geworden heisst negativ"


def test_bestandstabelle_braucht_ein_sitzungsgeheimnis(client: TestClient) -> None:
    assert client.get("/api/v1/assets").status_code == 401
