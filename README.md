# New Eden Foundry

Ein Industrie-Werkzeug für EVE Online als eigenständige Anwendung für Windows,
Linux und macOS. Login über EVE SSO, kein Server, kein Browser.

> **Persönliches Projekt.** Keine Zusage auf Support, keine Zusage auf
> Verfügbarkeit. Fehlerberichte sind willkommen — siehe aber den Hinweis zu
> Corp-Daten weiter unten.

## Was es beantworten soll

- **Was haben wir?** Alle Assets über Charaktere, Corp-Hangars und Strukturen
  hinweg, an einer Stelle durchsuchbar.
- **Was können wir bauen?** Blueprints mit ME/TE, Standort und Verfügbarkeit;
  Produktionsketten bis auf Mineral-Ebene aufgelöst.
- **Was fehlt?** Bedarf aus Doktrinen und Projekten gegen den realen Bestand
  gerechnet, inklusive laufender Jobs.
- **Lohnt sich das?** Materialkosten plus Job-Kosten gegen den Marktpreis, pro
  Zwischenprodukt entscheidbar.

Was es ausdrücklich **nicht** wird: Killboard, Auth-Portal für Discord/Mumble,
Marktbot oder Ersatz für Alliance Auth und SeAT.

## Stand

**Phase 0 — Fundament.** Die Anwendung startet, migriert ihre Datenbank
selbst, importiert den Static Data Export und zeigt ihren Betriebszustand.
Fachlogik gibt es noch keine; die acht Tabs stehen als Navigation und sagen,
ab welcher Phase sie Inhalt bekommen.

| | |
|---|---|
| Schale | Tauri 2 · Rust |
| Backend | FastAPI · SQLAlchemy 2 · SQLite · APScheduler |
| Oberfläche | React · Vite · TypeScript · Tailwind · TanStack Query |
| Bündelung | PyInstaller als Tauri-Sidecar |

Der Phasenplan und die fachlichen Kapitel stehen im Masterplan; der jeweils
aktuelle Architekturstand in [`docs/architecture.md`](docs/architecture.md) —
**das Repository ist die Wahrheit, der Masterplan der Entwurf.**

## Loslegen

```bash
# Backend
cd backend
uv venv && uv pip install -e ".[dev]"
.venv/bin/uvicorn "app.main:create_app" --factory --reload --port 8000

# Static Data (synthetische Demo-Daten, Sekunden statt Minuten)
.venv/bin/python -m app.sde.importer --source ../demo/sde --build demo-001

# Oberfläche
cd ../frontend && npm install && npm run dev
```

Ausführlich, inklusive Fenster statt Browser: [`docs/runbook.md`](docs/runbook.md).

### Vor dem ersten Commit

```bash
pip install pre-commit
pre-commit install && pre-commit install --hook-type commit-msg
```

Der gitleaks-Hook ist die eine Vorkehrung, die sich **nicht nachholen lässt**:
was einmal in der Historie eines öffentlichen Repositorys steht, ist innerhalb
von Minuten abgeerntet.

## Zwei Regeln, die nicht verhandelbar sind

### Keine echten Corp-Daten im Repository

Corp-Daten sind in EVE Aufklärungsmaterial. Echte Struktur-IDs, Standorte,
Bestandshöhen oder Doktrin-Fittings sind genau die Information, nach der
Gegner suchen — und aus der Historie eines öffentlichen Repositorys bekommt
man sie nicht wieder heraus.

**Testfixtures und Screenshots verwenden ausnahmslos die synthetischen Daten
aus [`demo/`](demo/README.md).** Fehlerberichte mit echten Beständen gehören
in den Discord, nicht in den öffentlichen Issue-Tracker.

### Keine Automatisierung des Clients

ESI kann nichts auslösen — keine Marktorder, keinen Industrie-Job, keinen
Contract. Was es kann, ist im Client ein Fenster öffnen oder einen Wegpunkt
setzen. Dafür gilt:

> Jeder UI-Aufruf ist die unmittelbare Folge eines Klicks durch den Besitzer
> des Charakters. Nie zeitgesteuert, nie aus dem Scheduler, nie gebündelt, nie
> für einen fremden Charakter.

Und für Mail: gesendet wird ausschließlich, was ein Mensch getippt und
abgeschickt hat. Foundry verschickt niemals von sich aus eine Mail.

Beides ausführlich in [`docs/esi-notes.md`](docs/esi-notes.md).

## Mitarbeiten

- **Trunk-based:** `main` ist geschützt, kurze Feature-Branches
  (`feat/asset-sync`), Merge per PR.
- **Conventional Commits:** `feat:`, `fix:`, `perf:`, `refactor:`, `chore:` —
  plus der eigene Typ `esi:` für alles, was eine ESI-Änderung auslöst. Daraus
  entsteht der Changelog, und `esi:` macht sichtbar, welche Releases
  fremdverursacht waren.
- **Jede Idee wird ein Issue, kein Branch.** Feature-Kriechen ist das
  realistischste Risiko dieses Projekts.

Die Prüfungen aus `ci.yml` lokal:

```bash
cd backend  && .venv/bin/ruff check app tests && .venv/bin/mypy app && .venv/bin/pytest
cd frontend && npm run lint && npm run typecheck && npm run test && npm run build
cd src-tauri && cargo fmt --check && cargo clippy --all-targets -- -D warnings
```

## Lizenz

[MIT](LICENSE) für den Quelltext dieses Projekts.

EVE Online und alle zugehörigen Marken sind Eigentum von CCP hf. Dieses
Werkzeug ist ein Drittanbieter-Produkt unter dem EVE Developer License
Agreement: nichtkommerziell, kein Entgelt für den Zugang, ausdrückliche
Zustimmung der Spieler zur Datenverarbeitung. CCP kann den Zugang jederzeit
entziehen.
