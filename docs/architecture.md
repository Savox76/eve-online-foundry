# Architektur — Stand Phase 1 + Durchstich

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
| `backend/app/esi/` | ESI-Client, Routenkatalog, Scopes, Kompatibilitätsdatum, Cache, Fehlerarten, SSO-Flow (PKCE, JWKS, Callback, Token-Speicher) |
| `backend/app/services/` | Charaktere, Bestände, Standortauflösung |
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

### Der Login: nativ, mit PKCE, ohne Client Secret

Als Desktop-Anwendung gilt der native Flow. Eine installierte Anwendung kann
ohnehin nichts geheim halten — statt eines Client Secrets weist sie sich über
PKCE aus: sie schickt beim Tausch von Code gegen Token den `code_verifier`
nach, aus dem die zuvor übermittelte `code_challenge` gebildet wurde.

Der Ablauf verteilt sich auf vier Module, und die Trennung hat einen Grund:

| Modul | Aufgabe |
|---|---|
| `esi/pkce.py` | Verifier, Challenge, `state` |
| `esi/callback.py` | Der kurzlebige Listener auf Port 8765 |
| `esi/sso.py` | Token-Endpunkt, formularkodiert |
| `esi/jwks.py` | Offline-Prüfung des Access Tokens |

**Der Listener lebt genau einen Login lang.** Ein dauerhaft offener Port wäre
eine unnötige Angriffsfläche für eine Anwendung, die sich vielleicht einmal
pro Woche anmeldet. Er bindet nur an `127.0.0.1` und verwirft jeden Rückruf,
dessen `state` nicht zum laufenden Versuch gehört.

**Geprüft wird offline gegen den JWKS**, nicht durch Nachfragen bei CCP: eine
Anwendung, die bei jedem Request nachfragt, wartet unnötig und fällt aus,
sobald der Login-Dienst kurz hängt. Vier Dinge werden geprüft — Signatur,
Issuer, Audience (Client-ID **und** `"EVE Online"`, beides), Ablauf. Bei
einem unbekannten `kid` wird der Schlüsselsatz einmal neu geholt; ist der
Dienst nicht erreichbar, gilt der letzte Stand weiter statt den Nutzer
auszusperren.

### Wo der Refresh Token liegt — und wo nicht

Im **Schlüsselbund des Systems**: Windows Credential Manager, macOS Keychain,
Secret Service unter Linux. Ob der wirklich nutzbar ist, wird durch einen
echten Schreib-Lese-Löschzyklus festgestellt, nicht durch eine Abfrage —
`keyring` meldet auch dann ein Backend, wenn dahinter kein laufender Dienst
steht, und unter Linux ohne Desktop-Sitzung ist das der Normalfall.

Fällt er aus, greift eine verschlüsselte Datei mit `0600`. Diese Ebene ist
**schwächer**, und zwar in einem Punkt, den man kennen muss: der Schlüssel
liegt neben den Daten. Was sie trotzdem leistet — der Token steht nirgends im
Klartext und landet nicht versehentlich in einem Backup, einem Screenshot
oder einem Bugreport. Genau das sind die Wege, auf denen so etwas in der
Praxis abhandenkommt. Welche Ebene aktiv ist, steht in der Oberfläche.

**In der Datenbank steht kein Token**, nur was über ihn bekannt ist: Scopes,
Speicherort, Ablauf, Zahl der Fehlversuche. Eine Datenbankdatei wandert in
Backups und auf USB-Sticks.

Zwei Regeln aus Kapitel 4 sind fest verdrahtet:

- **Der neue Refresh Token wird bei jedem Refresh sofort gespeichert.** CCP
  tauscht ihn aus; wer den alten behält, fliegt beim übernächsten Start raus.
- **Der `owner`-Claim wird mitgeführt und verglichen.** Ändert er sich, wurde
  der Charakter verkauft: alle Tokens werden verworfen und die Bestände des
  alten Besitzers gelöscht. Sonst zeigt Foundry fremde Assets an.

Ein einzelner Ausfall des Login-Dienstes meldet niemanden ab — erst drei
Fehlversuche in Folge setzen den Charakter auf `needs_reauth`, mit Begründung
in der Oberfläche.

### Standorte auflösen

Ein `location_id` kann eine NPC-Station sein, eine Spielerstruktur, ein
Sonnensystem — oder die `item_id` eines anderen Assets, also ein Container
oder ein Schiff. Die Elternkette läuft eine rekursive CTE hoch, mit
`depth < 32` als Zyklusschutz.

**Der zweite Schritt ist der wichtigere.** Wer die Tiefengrenze erreicht, hat
keine Wurzel gefunden, sondern nur aufgehört zu suchen. Solche Zeilen bekommen
`root_location_id = NULL` und erscheinen als „unbekannt", statt einen
erfundenen Ort zu tragen, der jedes Aggregat darüber verfälschen würde. Eine
fehlende Angabe sieht man; eine falsche glaubt man. Die Zahl der
unaufgelösten Zeilen steht über der Tabelle.

Für Strukturen ohne Docking-Zugriff gilt derselbe Grundsatz: `Unbekannte
Struktur #1035…` statt einer leeren Zelle, die wie ein Fehler aussieht.

### Das Asset-Delta

`esi_asset_changes` wird **vom ersten Sync an** mitgeschrieben — das ist die
Entscheidung aus Kapitel 7, die sich nicht rückwirkend nachholen lässt. Vier
Fälle werden unterschieden, und die Unterscheidung ist der Punkt:

| Fall | Bedeutung |
|---|---|
| `added` | neu aufgetaucht |
| `removed` | verschwunden — die Frage „wo sind die 2000 Morphite geblieben" |
| `quantity` | Menge geändert, mit Vorher und Nachher |
| `moved` | umgezogen, **nicht** als „weg" plus „neu" |

Ohne den letzten Fall sähe jeder Transport wie ein Verlust aus. Und wo sich
nichts geändert hat, wird nichts geschrieben — sonst wüchse die Tabelle bei
jedem Lauf, ohne etwas auszusagen.

Ein Delta allein sagt nur, dass etwas weg ist. Erst der Abgleich mit den
Industrie-Jobs desselben Zeitraums macht daraus eine Aussage; dafür trägt die
Tabelle bereits ein `job_id`-Feld, das Phase 3 füllt.

### Ein ESI-Client, ein Budget

Rate Limit und Fehlerbudget gelten **pro Anwendung**, nicht pro Charakter.
Einhalten lassen sie sich nur, wenn ein einziger Zähler alle Abrufe sieht.
Deshalb gibt es genau ein `EsiBudget` im Prozess, durch das aller externe
Verkehr läuft. Details in [`esi-notes.md`](esi-notes.md).

## Was noch nicht steht

| Bereich | Phase | Anmerkung |
|---|---|---|
| Corp-Bestände (`CorpSAG1`…`CorpSAG7`) | 2 | Der Charakter-Sync steht; Corp braucht Rollenprüfung und Divisionsnamen |
| Strukturnamen über `/universe/structures/` | 2 | Die Tabelle `esi_structures` steht samt `access_denied`; der Abruf fehlt |
| Suche über alle Charaktere zugleich | 2 | Die Tabelle filtert derzeit auf einen |
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
