# Changelog

Wird aus den Conventional Commits erzeugt und mit der Anwendung ausgeliefert —
damit der Updater „was ist neu" anzeigen kann, ohne die GitHub-API zu
befragen.

Versioniert nach [SemVer](https://semver.org/lang/de/), unterhalb von `1.0.0`
bis das Datenmodell stabil ist. Eine feste Regel hängt am Updater: **ein
Release mit Datenbank-Migration ist niemals ein Patch-Release.**

## [0.1.0] — noch nicht veröffentlicht

### Neu

- Fundament der Anwendung: Tauri-Schale mit Backend-Sidecar, FastAPI auf der
  Loopback-Adresse, SQLite mit Migration beim Start.
- Static-Data-Importer für das offizielle JSONL-Format, versioniert und in
  einer Transaktion — ein abgebrochener Import lässt den vorherigen Stand
  unverändert stehen.
- ESI-Client mit Kompatibilitätsdatum, ETag- und `Expires`-Cache,
  gemeinsamem Rate-Limit-Budget je Routengruppe und Circuit Breaker auf dem
  Fehlerbudget.
- Absicherung des Loopback-Servers über ein Sitzungsgeheimnis, das die Schale
  bei jedem Start neu erzeugt.
- Oberfläche mit den acht Tabs und der Betriebszustandsansicht: Version,
  Static-Data-Stand, Alter des Kompatibilitätsdatums, ESI-Fehlerbudget.
- Synthetische Demo-Daten in `demo/` als einzige Quelle für Testfixtures und
  Screenshots.
- **EVE SSO:** nativer Login mit PKCE über den Systembrowser, kurzlebiger
  Callback-Listener auf einem festen Port, Offline-Prüfung des Access Tokens
  gegen den JWKS. Refresh Tokens liegen im Schlüsselbund des Systems, mit
  einer verschlüsselten Datei als Rückfallebene; der neue Token wird bei jedem
  Refresh sofort gespeichert.
- Gestaffelte Scope-Pakete statt eines Consent-Fensters, das alles auf einmal
  anfragt. Erteilte Corp-Scopes, denen die passende In-Game-Rolle fehlt,
  werden benannt statt als leere Liste angezeigt.
- Erkennung übertragener Charaktere über den `owner`-Claim: Tokens und
  Bestände des alten Besitzers werden verworfen.
- **Bestände:** Abruf je Charakter mit Auflösung verschachtelter Container
  über eine rekursive CTE, Namen benannter Container und Schiffe, und das
  Asset-Delta vom ersten Sync an — es lässt sich nicht rückwirkend nachholen.
- Tab **Assets** mit Suche, Ortsfilter, Volumenangabe je Zeile und der
  Ansicht „seit gestern".
