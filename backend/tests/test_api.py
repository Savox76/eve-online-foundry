"""Die Aussenkante: Gesundheitscheck und Absicherung des Loopback-Servers."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_ist_ohne_geheimnis_erreichbar(client: TestClient) -> None:
    """Die Schale fragt /health ab, bevor sie ein Geheimnis kennt."""
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database_revision"] == "0001_fundament"


def test_api_ohne_geheimnis_wird_abgewiesen(client: TestClient) -> None:
    """Ein fremder Prozess auf demselben Rechner kommt nicht durch."""
    response = client.get("/api/v1/admin/status")
    assert response.status_code == 401


def test_api_mit_falschem_geheimnis_wird_abgewiesen(client: TestClient) -> None:
    response = client.get("/api/v1/admin/status", headers={"X-Foundry-Session": "falsch"})
    assert response.status_code == 401


def test_status_liefert_betriebszustand(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/admin/status", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["database_revision"] == "0001_fundament"
    # Ohne Import gibt es noch keinen SDE-Stand -- und das muss sichtbar sein,
    # statt als leeres Objekt durchzugehen.
    assert payload["sde"] is None
    assert payload["compatibility"]["state"] == "ok"
    assert payload["rate_limit"]["error_remain"] is None


def test_keine_cors_middleware_registriert(client: TestClient) -> None:
    """Kein CORS ist hier eine Entscheidung, kein Versehen (Kapitel 18).

    Waere eine permissive CORS-Middleware aktiv, koennte eine beliebige
    Webseite im Browser die lokale API auslesen.
    """
    response = client.get("/health", headers={"Origin": "https://example.invalid"})
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}
