"""Wo der Refresh Token liegt -- und wo er niemals liegt."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.esi.tokens import (
    EncryptedFileTokenStore,
    MemoryTokenStore,
    get_token_store,
    keyring_available,
    set_token_store,
)


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    set_token_store(None)


def test_verschluesselte_datei_haelt_und_gibt_zurueck(isolated_data_dir: Path) -> None:
    store = EncryptedFileTokenStore(isolated_data_dir)
    store.save(9_000_001, "refresh-abc")
    assert store.load(9_000_001) == "refresh-abc"


def test_der_token_steht_nirgends_im_klartext(isolated_data_dir: Path) -> None:
    """Der eigentliche Zweck der Rueckfallebene.

    Sie schuetzt nicht gegen jemanden, der die Datei lesen kann -- der
    Schluessel liegt daneben. Sie schuetzt dagegen, dass der Token in einem
    Backup, einem Screenshot oder einem Bugreport auftaucht.
    """
    store = EncryptedFileTokenStore(isolated_data_dir)
    store.save(9_000_001, "streng-geheimer-refresh-token")

    for datei in isolated_data_dir.iterdir():
        assert b"streng-geheimer" not in datei.read_bytes(), f"{datei.name} enthaelt Klartext"


def test_dateien_sind_nur_fuer_den_besitzer_lesbar(isolated_data_dir: Path) -> None:
    store = EncryptedFileTokenStore(isolated_data_dir)
    store.save(9_000_001, "refresh-abc")
    for name in ("tokens.enc", "token-key"):
        assert (isolated_data_dir / name).stat().st_mode & 0o777 == 0o600


def test_mehrere_charaktere_stoeren_sich_nicht(isolated_data_dir: Path) -> None:
    store = EncryptedFileTokenStore(isolated_data_dir)
    store.save(9_000_001, "erster")
    store.save(9_000_002, "zweiter")
    store.delete(9_000_001)
    assert store.load(9_000_001) is None
    assert store.load(9_000_002) == "zweiter"


def test_loeschen_eines_unbekannten_charakters_ist_kein_fehler(isolated_data_dir: Path) -> None:
    EncryptedFileTokenStore(isolated_data_dir).delete(9_000_999)


def test_neuer_token_ersetzt_den_alten(isolated_data_dir: Path) -> None:
    """CCP tauscht den Refresh Token bei jedem Refresh aus."""
    store = EncryptedFileTokenStore(isolated_data_dir)
    store.save(9_000_001, "refresh-eins")
    store.save(9_000_001, "refresh-zwei")
    assert store.load(9_000_001) == "refresh-zwei"


def test_unpassender_schluessel_verwirft_die_datei(
    isolated_data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Meist ein kopiertes Datenverzeichnis.

    Ein Refresh Token, den wir nicht entschluesseln koennen, ist wertlos --
    ihn liegen zu lassen wuerde nur bei jedem Start denselben Fehler
    erzeugen.
    """
    store = EncryptedFileTokenStore(isolated_data_dir)
    store.save(9_000_001, "refresh-abc")

    from cryptography.fernet import Fernet

    (isolated_data_dir / "token-key").write_bytes(Fernet.generate_key())

    with caplog.at_level("ERROR"):
        assert EncryptedFileTokenStore(isolated_data_dir).load(9_000_001) is None
    assert "neu zu verbinden" in caplog.text


def test_ohne_schluesselbund_greift_die_rueckfallebene(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Und sie meldet sich -- niemand soll sie fuer den Normalfall halten."""
    monkeypatch.setattr("app.esi.tokens.keyring_available", lambda: False)
    with caplog.at_level("WARNING"):
        store = get_token_store()
    assert store.kind == "encrypted-file"
    assert "Rueckfallebene" in caplog.text


def test_mit_schluesselbund_wird_er_genommen(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.esi.tokens.keyring_available", lambda: True)
    assert get_token_store().kind == "keyring"


def test_schluesselbund_wird_ausprobiert_nicht_nur_befragt() -> None:
    """``keyring`` meldet auch dann ein Backend, wenn kein Dienst dahintersteht.

    Der Aufruf darf deshalb unter keinen Umstaenden werfen -- er muss eine
    Antwort liefern, auch auf einem Rechner ohne Desktop-Sitzung.
    """
    assert isinstance(keyring_available(), bool)


def test_speicher_im_arbeitsspeicher_ueberlebt_nichts() -> None:
    store = MemoryTokenStore()
    store.save(9_000_001, "fluechtig")
    assert store.load(9_000_001) == "fluechtig"
    assert MemoryTokenStore().load(9_000_001) is None
