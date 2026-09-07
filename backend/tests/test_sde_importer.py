"""Der SDE-Importer gegen die synthetischen Demo-Daten.

Die wichtigste Zusicherung steht ganz unten: bricht ein Import ab, arbeitet
die Anwendung unveraendert mit dem vorherigen Stand weiter. Kapitel 5 fordert
"der alte Datensatz bleibt stehen, bis der neue vollstaendig ist" -- hier wird
nachgewiesen, dass die eine Transaktion das wirklich leistet.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.sde import importer as importer_module
from app.sde.datasets import ACTIVITY_IDS, blueprint_row_id
from app.sde.importer import SdeImportError, active_build, import_sde, report
from app.sde.loader import SdeSource, SdeSourceError, localized


def _rows(db: Path, sql: str) -> list[sqlite3.Row]:
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    try:
        return list(connection.execute(sql))
    finally:
        connection.close()


# -- Loader ------------------------------------------------------------------
def test_lokalisierte_namen_werden_aufgeloest() -> None:
    """Der Export liefert Namen mal als String, mal als Sprachobjekt."""
    assert localized("Tritanium") == "Tritanium"
    assert localized({"en": "Tritanium", "de": "Tritanium"}) == "Tritanium"
    assert localized({"de": "Nur Deutsch"}) == "Nur Deutsch"
    assert localized(None) == ""


def test_fehlende_quelle_meldet_sich_deutlich(tmp_path: Path) -> None:
    with pytest.raises(SdeSourceError, match="Kein Static Data Export"):
        SdeSource(tmp_path / "gibtsnicht")


def test_report_findet_alle_pflichtdateien(demo_sde: Path) -> None:
    gefunden = report(demo_sde)
    assert gefunden["types"] == "types.jsonl"
    assert gefunden["blueprints"] == "blueprints.jsonl"
    assert all(gefunden[name] for name in ("categories", "groups", "regions", "systems"))


# -- Import ------------------------------------------------------------------
def test_import_schreibt_alle_tabellen(migrated_db: Path, demo_sde: Path) -> None:
    counts = import_sde(demo_sde, db_path=migrated_db, build="demo-test")
    assert counts["sde_types"] == 13
    assert counts["sde_categories"] == 3
    assert counts["sde_groups"] == 5
    assert counts["sde_regions"] == 1
    assert counts["sde_systems"] == 3


def test_kaputte_zeile_wird_uebersprungen_nicht_verschluckt(
    migrated_db: Path, demo_sde: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Ein Export mit drei unlesbaren Zeilen bleibt importierbar -- aber nicht unbemerkt."""
    with caplog.at_level("WARNING"):
        import_sde(demo_sde, db_path=migrated_db, build="demo-test")
    assert "unlesbare Zeilen" in caplog.text


def test_blueprint_aktivitaeten_werden_getrennt(migrated_db: Path, demo_sde: Path) -> None:
    """Manufacturing, Invention und Kopieren haben eigene Formeln -- und eigene Zeilen."""
    import_sde(demo_sde, db_path=migrated_db, build="demo-test")
    aktivitaeten = {
        row["activity"]
        for row in _rows(
            migrated_db,
            "SELECT activity FROM sde_blueprints WHERE blueprint_type_id = 9900030",
        )
    }
    assert aktivitaeten == {
        "manufacturing",
        "copying",
        "invention",
        "research_material",
        "research_time",
    }


def test_schluessel_je_aktivitaet_ist_kollisionsfrei() -> None:
    schluessel = {blueprint_row_id(9900030, name) for name in ACTIVITY_IDS}
    assert len(schluessel) == len(ACTIVITY_IDS)
    assert blueprint_row_id(9900030, "manufacturing") != blueprint_row_id(9900031, "manufacturing")


def test_materialien_als_liste_und_als_objekt(migrated_db: Path, demo_sde: Path) -> None:
    """Beide Formen kommen im echten Export vor. Beide muessen laufen."""
    import_sde(demo_sde, db_path=migrated_db, build="demo-test")

    als_liste = _rows(
        migrated_db,
        "SELECT m.type_id, m.quantity FROM sde_blueprint_materials m "
        "JOIN sde_blueprints b ON b.id = m.blueprint_id "
        "WHERE b.blueprint_type_id = 9900030 AND b.activity = 'manufacturing' "
        "ORDER BY m.type_id",
    )
    assert [(r["type_id"], r["quantity"]) for r in als_liste] == [
        (9900001, 32000),
        (9900002, 8000),
        (9900010, 12),
    ]

    als_objekt = _rows(
        migrated_db,
        "SELECT m.type_id, m.quantity FROM sde_blueprint_materials m "
        "JOIN sde_blueprints b ON b.id = m.blueprint_id "
        "WHERE b.blueprint_type_id = 9900031 AND b.activity = 'manufacturing' "
        "ORDER BY m.type_id",
    )
    assert [(r["type_id"], r["quantity"]) for r in als_objekt] == [
        (9900001, 48000),
        (9900003, 6000),
        (9900011, 24),
    ]


def test_invention_traegt_die_grundwahrscheinlichkeit(migrated_db: Path, demo_sde: Path) -> None:
    import_sde(demo_sde, db_path=migrated_db, build="demo-test")
    row = _rows(
        migrated_db,
        "SELECT p.probability FROM sde_blueprint_products p "
        "JOIN sde_blueprints b ON b.id = p.blueprint_id WHERE b.activity = 'invention'",
    )[0]
    assert row["probability"] == pytest.approx(0.34)


def test_pi_schema_kennt_ein_und_ausgang(migrated_db: Path, demo_sde: Path) -> None:
    import_sde(demo_sde, db_path=migrated_db, build="demo-test")
    rows = _rows(
        migrated_db,
        "SELECT type_id, quantity, is_input FROM sde_planet_schematic_types ORDER BY is_input",
    )
    assert [(r["type_id"], bool(r["is_input"])) for r in rows] == [
        (9900041, False),
        (9900040, True),
    ]


def test_build_wird_aktiv_gesetzt(migrated_db: Path, demo_sde: Path) -> None:
    import_sde(
        demo_sde, db_path=migrated_db, build="demo-042", source_url="https://example.invalid"
    )
    build = active_build(migrated_db)
    assert build is not None
    assert build["build"] == "demo-042"
    assert build["row_counts"]["sde_types"] == 13


def test_zweiter_import_loest_den_ersten_ab(migrated_db: Path, demo_sde: Path) -> None:
    import_sde(demo_sde, db_path=migrated_db, build="demo-alt")
    import_sde(demo_sde, db_path=migrated_db, build="demo-neu")
    aktiv = _rows(migrated_db, "SELECT build FROM sde_builds WHERE is_active = 1")
    assert [row["build"] for row in aktiv] == ["demo-neu"]


def test_import_ohne_datenbank_meldet_die_migration(tmp_path: Path, demo_sde: Path) -> None:
    with pytest.raises(SdeImportError, match="alembic upgrade head"):
        import_sde(demo_sde, db_path=tmp_path / "gibtsnicht.db")


def test_fehlende_pflichtdatei_bricht_ab(migrated_db: Path, demo_sde: Path, tmp_path: Path) -> None:
    unvollstaendig = tmp_path / "teilexport"
    unvollstaendig.mkdir()
    for name in ("categories.jsonl", "groups.jsonl"):
        (unvollstaendig / name).write_text((demo_sde / name).read_text(), encoding="utf-8")

    with pytest.raises(SdeImportError, match="Pflichtdatei"):
        import_sde(unvollstaendig, db_path=migrated_db, build="kaputt")


def test_optionale_datei_darf_fehlen(migrated_db: Path, demo_sde: Path, tmp_path: Path) -> None:
    ohne_pi = tmp_path / "ohne-pi"
    ohne_pi.mkdir()
    for source in demo_sde.glob("*.jsonl"):
        if source.name in {"planets.jsonl", "planetSchematics.jsonl"}:
            continue
        (ohne_pi / source.name).write_text(source.read_text(), encoding="utf-8")

    counts = import_sde(ohne_pi, db_path=migrated_db, build="ohne-pi")
    assert counts["sde_types"] == 13
    assert "sde_planets" not in counts


# -- Die Zusicherung ---------------------------------------------------------
def test_abgebrochener_import_laesst_den_alten_stand_stehen(
    migrated_db: Path, demo_sde: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein halb importierter SDE fuehrt zu falschen Rechnungen -- also gibt es ihn nicht.

    Der Import laeuft in einer Transaktion. Bricht er ab, macht SQLite alles
    rueckgaengig: die Typen des vorherigen Standes stehen unveraendert da, und
    der alte Build ist weiterhin der aktive.
    """
    import_sde(demo_sde, db_path=migrated_db, build="stand-alt")
    vorher = _rows(migrated_db, "SELECT COUNT(*) AS n FROM sde_types")[0]["n"]
    assert vorher == 13

    def explodiert(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Datentraeger voll")

    monkeypatch.setattr(importer_module, "_record_build", explodiert)

    with pytest.raises(RuntimeError, match="Datentraeger voll"):
        import_sde(demo_sde, db_path=migrated_db, build="stand-neu")

    nachher = _rows(migrated_db, "SELECT COUNT(*) AS n FROM sde_types")[0]["n"]
    assert nachher == vorher, "Der abgebrochene Import hat den alten Stand beschaedigt"

    build = active_build(migrated_db)
    assert build is not None
    assert build["build"] == "stand-alt"
    assert json.loads(json.dumps(build["row_counts"]))["sde_types"] == 13


def test_import_ruehrt_app_tabellen_nicht_an(migrated_db: Path, demo_sde: Path) -> None:
    """Die Entwurfsregel aus Kapitel 7, als Test.

    Ein SDE-Reimport darf niemals Daten aus ``app_`` beruehren. Steht dieser
    Satz im Schema, ist das Projekt gegen die haeufigste Katastrophe dieser
    Werkzeuggattung immun.
    """
    connection = sqlite3.connect(migrated_db)
    connection.execute(
        "INSERT INTO app_settings (key, value, updated_at) "
        "VALUES ('unersetzlich', 'ja', '2026-09-07')"
    )
    connection.commit()
    connection.close()

    import_sde(demo_sde, db_path=migrated_db, build="demo-test")

    rows = _rows(migrated_db, "SELECT value FROM app_settings WHERE key = 'unersetzlich'")
    assert [row["value"] for row in rows] == ["ja"]
