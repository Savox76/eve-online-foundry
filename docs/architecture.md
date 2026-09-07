# Architektur — Stand Phase 0

> Der Masterplan ist der Entwurf, dieses Dokument ist der Stand. Wo beide
> auseinandergehen, gilt das Repository.

## Was läuft

Ein Prozessbaum auf dem Rechner des Nutzers:

```
Tauri-Schale (Rust)
 ├─ WebView  ──HTTP──►  Backend-Sidecar (FastAPI, 127.0.0.1:8000)
 └─ spawnt              ├─ SQLite (eine Datei im Datenverzeichnis)
                        ├─ APScheduler (im selben Prozess)
                        └─ ESI-Client (ein einziger, gemeinsames Budget)
```

Kein Server, kein Postgres, kein Redis, kein Browser. Die Schale startet das
Backend, das Backend hält die Datenbank.

## Verzeichnisse

| Pfad | Inhalt |
|---|---|
| `backend/app/core/` | Konfiguration, Datenbank, Sicherheit, Migration, Instanzsperre, Rate-Limit-Budget |
| `backend/app/esi/` | ESI-Client, Routenkatalog, Scopes, Kompatibilitätsdatum, Cache, Fehlerarten |
| `backend/app/sde/` | Static-Data-Import: Loader, Datensatz-Zuordnung, Importer-CLI |
| `backend/app/models/` | SQLAlchemy-Modelle, getrennt nach `sde_`, `esi_`, `app_` |
| `backend/app/api/v1/` | Ein Router je Fachbereich; die noch nicht dran sind, sind leer |
| `backend/alembic/` | Migrationen |
| `frontend/src/` | React-Oberfläche: acht Tabs, Betriebszustand |
| `src-tauri/` | Anwendungsschale, Sidecar-Handschlag, Bündelung |
| `demo/sde/` | Synthetischer Static Data Export — die einzige Quelle für Fixtures |
| `scripts/` | Sidecar-Bündelung, Symbolerzeugung, Commit-Prüfung |

## Entscheidungen, die getroffen sind

### Datenbank: SQLite mit drei PRAGMAs

`foreign_keys=ON` ist Pflicht — in SQLite sind Fremdschlüssel standardmäßig
**aus**, und ohne das PRAGMA sind alle `ForeignKey`-Angaben in den Modellen
reine Dokumentation. Dazu `journal_mode=WAL`, damit der Sync schreiben kann
während die Oberfläche liest, und `busy_timeout` als zweite Sicherung gegen
zwei Prozesse auf einer Datei.

Die PRAGMAs hängen am `connect`-Event, nicht an einer Startroutine: eine
Verbindung, die sie nicht bekommen hat, gibt es damit gar nicht erst.

> **Fallstrick, der hier zugeschlagen hat:** ein naheliegender
> `isinstance(conn, sqlite3.Connection)`-Wächter im Event-Handler greift unter
> `aiosqlite` **immer** — SQLAlchemy reicht dort einen
> `AsyncAdapt_aiosqlite_connection` durch. Die Folge wäre eine Datenbank ohne
> Fremdschlüssel und ohne WAL, lautlos. `tests/test_db.py` prüft die PRAGMAs
> deshalb nach, statt sich auf das Registrieren des Hooks zu verlassen.

### Tabellenpräfixe statt Schemata

SQLite kennt keine Schemata. `sde_`, `esi_`, `app_` im Namen leisten dasselbe
und laufen als Nebeneffekt unverändert auf PostgreSQL, falls doch ein
Corp-Server dazukommt. Die Entwurfsregel: **ein SDE-Reimport oder ein
kompletter ESI-Resync darf niemals `app_`-Daten berühren** — dafür gibt es
einen eigenen Test.

### SDE-Import in einer Transaktion

Kapitel 5 fordert „der alte Datensatz bleibt stehen, bis der neue vollständig
ist". Für SQLite ist die Antwort darauf nicht eine zweite Tabellengeneration,
sondern **eine Transaktion**: Bricht der Import ab — kaputte Datei, voller
Datenträger, Strom weg — macht SQLite alles rückgängig und die Anwendung
arbeitet unverändert mit dem vorherigen Stand weiter. Es gibt keinen
Zwischenzustand mit halb importierten Typen.

`PRAGMA defer_foreign_keys` schiebt die Fremdschlüsselprüfung ans Ende der
Transaktion, damit die Löschreihenfolge keine Rolle spielt. Geprüft wird
trotzdem, nur einmal am Schluss.

### Migration beim Start, mit Sicherung davor

Eine Desktop-Anwendung hat kein Wartungsfenster. Deshalb: vor jeder Migration
eine Kopie, benannt nach dem abgelösten Stand, die letzten zehn bleiben
liegen. Schlägt die Migration fehl, **startet die Anwendung gar nicht** — das
ist beabsichtigt und besser als halb migriert.

Kopiert wird über die `backup`-Schnittstelle von SQLite, nicht mit
`shutil.copy`: bei aktivem WAL erwischt ein Dateikopieren den Journalstand
nicht zuverlässig mit und kann eine Sicherung erzeugen, die sich nicht öffnen
lässt — was man erst merkt, wenn man sie braucht.

### Migrationen sind von Anwendungscode entkoppelt

`alembic/env.py` rendert eigene Typen (`UtcDateTime`) als das, was sie auf
DDL-Ebene sind (`sa.DateTime()`). Sonst stünde `app.models.base.UtcDateTime()`
in der Migration — und eine Migration von heute muss in zwei Jahren noch
laufen, auch wenn die Klasse längst anders heißt.

> Zweiter Fallstrick an derselben Stelle: `fileConfig()` schaltet
> standardmäßig **alle bestehenden Logger ab**. Da die Migration beim
> Anwendungsstart läuft, wäre danach das gesamte Logging stumm. Deshalb
> `disable_existing_loggers=False`.

### Absicherung des Loopback-Servers

Ein Server auf `127.0.0.1` ist für jeden Prozess auf dem Rechner erreichbar —
auch für eine Webseite im Browser. Zwei Maßnahmen:

1. **Sitzungsgeheimnis.** Die Schale erzeugt es beim Start und reicht es dem
   Sidecar über die Umgebung und dem Fenster über einen Tauri-Befehl durch.
   Jeder Request trägt es im Header `X-Foundry-Session`; verglichen wird in
   konstanter Zeit. Einzige Ausnahme: `/health`, worauf die Schale wartet,
   bevor sie überhaupt ein Geheimnis mitschicken kann.
2. **Kein CORS.** Es wird bewusst *keine* CORS-Middleware registriert. Damit
   verweigert der Browser jeder fremden Origin schon den Lesezugriff.

Im Entwicklungsbetrieb gibt es keine Schale; dort legt das Backend das
Geheimnis im Datenverzeichnis ab und der Vite-Proxy hängt es an.

### Ein ESI-Client, ein Budget

Rate Limit und Fehlerbudget gelten **pro Anwendung**, nicht pro Charakter.
Einhalten lassen sie sich nur, wenn ein einziger Zähler alle Abrufe sieht.
Deshalb gibt es genau ein `EsiBudget` im Prozess, durch das aller externe
Verkehr läuft. Details in [`esi-notes.md`](esi-notes.md).

## Was noch nicht steht

| Bereich | Phase | Anmerkung |
|---|---|---|
| SSO-Login, Token im Schlüsselbund | 1 | `app/esi/scopes.py` und die Callback-Konfiguration stehen bereits |
| Asset-Sync, `esi_asset_changes` | 2 | Die Delta-Entscheidung ist getroffen, die Tabelle kommt mit dem Sync |
| Blueprint-Bibliothek, Jobs | 3 | Die SDE-Seite liegt vollständig vor |
| Produktionssolver, Job-Kosten | 4 | Gegen `api.everef.net/v1/industry/cost` zu validieren |
| T2 Invention | 5 | SDE-Grundwahrscheinlichkeiten werden bereits importiert |
| Scanner | 6 | Hängt an den EVE-Ref-Bulk-Dumps, nicht an ESI |
| Projekte, Doktrinen, Fittings | 7 | |
| Planetare Industrie | 8 | PI-Schemata liegen im SDE-Import bereits vor |
| Nachrichten, Discord, Feinschliff | 9 | |
| Projektseite (`site/`, `pages.yml`) | 2 | Der Phasenplan setzt sie ans Ende von Phase 2, nicht in Phase 0 |

## Offene Punkte aus dem Masterplan

Diese drei beeinflussen das Datenmodell ab Phase 4 und sind noch nicht
entschieden:

- **Standard-Preisquelle** — Jita-Sell-Perzentil oder eigener Buyback-Kurs?
  Vorschlag des Plans: konfigurierbare Preisprofile, Standard Jita 5 %.
- **Reaktionen** — mit Phase 4 oder später?
- **Regionen des Scanners** — bleibt es bei den fünf Hubs, und was ist die
  Standardsortierung?

Dazu ein vierter Punkt, der in Phase 0 aufgefallen ist und im Masterplan
widersprüchlich steht: die **Callback-URL**. Kapitel 4 nennt
`http://localhost:8765/callback`, Kapitel 16 im Abschnitt „Lokaler Start"
dagegen `http://localhost:8000/auth/callback`. Der Code folgt Kapitel 4
(fester Port 8765, eigener kurzlebiger Listener), weil das zum nativen Flow
passt und den Callback vom API-Port trennt. Vor der Registrierung im
Developers-Portal ist das zu bestätigen — die SSO weist jede abweichende URL
zurück.
