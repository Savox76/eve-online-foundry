# Runbook

Was zu tun ist, wenn etwas nicht läuft — und wie man es zum Laufen bringt.

## Entwicklungsbetrieb

### Einmalig

```bash
# Backend
cd backend
uv venv && uv pip install -e ".[dev]"

# Frontend
cd ../frontend && npm install

# Schutz vor dem ersten Commit (Kapitel 16 — lässt sich nicht nachholen)
pip install pre-commit && pre-commit install && pre-commit install --hook-type commit-msg
```

### Starten

Drei Fenster, in dieser Reihenfolge:

```bash
# 1) Backend — legt die Datenbank an und migriert sie beim Start
cd backend
.venv/bin/uvicorn "app.main:create_app" --factory --reload --port 8000

# 2) Static Data importieren (einmalig, mit Demo-Daten in Sekunden)
.venv/bin/python -m app.sde.importer --source ../demo/sde --build demo-001

# 3) Frontend — der Vite-Proxy holt sich das Sitzungsgeheimnis selbst
cd ../frontend && npm run dev        # :5173
```

Die Oberfläche liegt dann auf <http://localhost:5173>.

**Wichtig:** Erst das Backend, dann `npm run dev`. Der Vite-Proxy liest das
Sitzungsgeheimnis beim Start aus dem Datenverzeichnis; existiert es noch
nicht, kommen alle API-Antworten als `401` zurück. In dem Fall reicht ein
Neustart des Vite-Servers.

### Mit Fenster statt im Browser

```bash
# Sidecar bündeln (dauert ein paar Minuten)
backend/.venv/bin/python scripts/build_sidecar.py

# Schale starten
cd src-tauri && cargo tauri dev
```

Unter Linux braucht die Schale Systembibliotheken:

```bash
sudo apt-get install -y libwebkit2gtk-4.1-dev libsoup-3.0-dev \
  libappindicator3-dev librsvg2-dev patchelf
```

## Wo die Daten liegen

| System | Pfad |
|---|---|
| Windows | `%LOCALAPPDATA%\NewEdenFoundry` |
| macOS | `~/Library/Application Support/NewEdenFoundry` |
| Linux | `~/.local/share/NewEdenFoundry` (bzw. `$XDG_DATA_HOME`) |

`FOUNDRY_DATA_DIR` sticht das aus — nützlich zum Testen mit einem leeren
Stand.

| Datei | Inhalt |
|---|---|
| `foundry.db` | Die eine Datenbank. Plus `-wal` und `-shm` im Betrieb. |
| `backups/` | Sicherungen vor Migrationen, die letzten zehn. |
| `sde-cache/` | Heruntergeladene Static-Data-Exporte. Jederzeit löschbar. |
| `foundry.lock` | Sperrdatei der Einzelinstanz. |
| `session-secret` | Nur im Entwicklungsbetrieb ohne Schale. |

**Ins Backup gehört genau eine Datei:** `foundry.db`. Alles andere ist
nachladbar — der SDE per Import, die ESI-Daten per Resync.

## Static Data importieren

```bash
cd backend

# Erst nachsehen, was der Export enthält — schreibt nichts
.venv/bin/python -m app.sde.importer --source ~/Downloads/eve-...-jsonl.zip --report

# Dann importieren
.venv/bin/python -m app.sde.importer \
    --source ~/Downloads/eve-...-jsonl.zip \
    --build 2026-09-expansion \
    --source-url https://developers.eveonline.com/static-data/
```

Der Export liegt offiziell unter
<https://developers.eveonline.com/static-data/> — **JSON Lines**, nicht YAML:
zeilenweise streambar, kein Speicherproblem.

Der Import läuft in einer Transaktion. Bricht er ab, ist die Datenbank
unverändert und der vorherige Stand weiterhin aktiv. Zwei Importe gleichzeitig
gibt es nicht — der zweite wartet auf die Schreibsperre.

## Fehlerbilder

### „New Eden Foundry läuft bereits"

Eine zweite Instanz hält die Dateisperre. Normalerweise löst sich das von
selbst: das Lock hängt am Prozess, ein abgestürzter Prozess gibt es sofort
frei. Bleibt die Meldung, läuft tatsächlich noch ein Backend — unter Linux
und macOS zu finden mit:

```bash
cat "$HOME/.local/share/NewEdenFoundry/foundry.lock"   # die PID
```

### Die Anwendung startet nach einem Update nicht

Das ist Absicht: eine fehlgeschlagene Migration bricht den Start ab, statt mit
halbem Schema weiterzurechnen. Die Fehlermeldung nennt den Pfad der Sicherung,
die **vor** der Migration angelegt wurde. Zum Zurückrollen:

```bash
cd ~/.local/share/NewEdenFoundry
mv foundry.db foundry.db.kaputt
cp backups/foundry-v0.1.0-0001_fundament-20260907-120000.db foundry.db
```

Dann die vorherige Version der Anwendung installieren und den Fehler melden.

### Alle API-Antworten sind `401`

Das Fenster schickt kein oder ein falsches Sitzungsgeheimnis mit.

- **Mit Schale:** Anwendung neu starten. Das Geheimnis entsteht bei jedem
  Start neu.
- **Ohne Schale:** Backend zuerst starten, dann `npm run dev` neu starten.

### `420` oder alles hängt

Das ESI-Fehlerbudget ist aufgebraucht; ESI antwortet auf allen Routen mit
`420`. Der Circuit Breaker pausiert selbständig bis zum Reset. Nachsehen:

```bash
curl -s -H "X-Foundry-Session: $(cat ~/.local/share/NewEdenFoundry/session-secret)" \
     http://127.0.0.1:8000/api/v1/admin/rate-limit | python3 -m json.tool
```

Steht `error_remain` dauerhaft niedrig, produziert etwas systematisch Fehler —
meist eine Struktur ohne Docking-Zugriff, die bei jedem Lauf erneut abgefragt
wird. Ins Sync-Log sehen: `/api/v1/admin/status` listet die letzten Läufe mit
Statuscode.

### Das Kompatibilitätsdatum ist abgelaufen

Der Betriebszustand zeigt es gelb ab 300 Tagen und rot ab 365. Vorgehen:

1. Gegen `https://esi.evetech.net/meta/openapi.json` prüfen, was sich geändert
   hat.
2. `ESI_COMPATIBILITY_DATE` in `backend/app/core/config.py` anheben.
3. Tests laufen lassen, Commit mit Typ `esi:`, Issue-Label `esi-change`.

### Die Datenbank ist gesperrt

`database is locked` trotz WAL heißt fast immer: zwei Prozesse. Der
`busy_timeout` von 5 Sekunden fängt kurze Überschneidungen ab; alles darüber
ist ein echtes Problem und kein Wartezustand.

## Prüfungen vor dem Commit

```bash
# Backend
cd backend
.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests
.venv/bin/mypy app
.venv/bin/pytest --cov=app

# Frontend
cd ../frontend
npm run lint && npm run typecheck && npm run test && npm run build

# Schale
cd ../src-tauri
cargo fmt --check && cargo clippy --all-targets -- -D warnings
```

Genau diese Befehle laufen auch in `ci.yml`. Wer sie lokal grün hat, hat sie
auch dort grün.

## Release

`release-please` hält dauerhaft einen Release-PR offen. Beim Merge entstehen
Tag, Release und Changelog-Abschnitt — sonst nichts.

Eine Regel, die am Updater hängt: **ein Release mit Datenbank-Migration ist
niemals ein Patch-Release.** Damit landet die riskante Klasse automatisch im
Bestätigungspfad.

Vor dem ersten Release mit Installern:

```bash
npx tauri signer generate
```

Der private Teil und sein Passwort werden Repository-Secrets, der öffentliche
wandert in `tauri.conf.json` unter `plugins.updater.pubkey`. Ohne diesen
Schlüssel akzeptiert der Updater nichts — auch nichts Manipuliertes. Erst
danach `plugins.updater.active` auf `true` setzen.
