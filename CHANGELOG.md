# Changelog

Wird aus den Conventional Commits erzeugt und mit der Anwendung ausgeliefert —
damit der Updater „was ist neu" anzeigen kann, ohne die GitHub-API zu
befragen.

Versioniert nach [SemVer](https://semver.org/lang/de/), unterhalb von `1.0.0`
bis das Datenmodell stabil ist. Eine feste Regel hängt am Updater: **ein
Release mit Datenbank-Migration ist niemals ein Patch-Release.**

## [0.2.0](https://github.com/Savox76/eve-online-foundry/compare/v0.1.0...v0.2.0) (2026-09-07)


### Neu

* **assets:** Bestände abrufen, Standorte auflösen, Delta mitschreiben ([840ba12](https://github.com/Savox76/eve-online-foundry/commit/840ba127ae1c1cc4e85bb45c420907ed0ce659fb))
* **auth:** EVE SSO mit PKCE, Token im Schlüsselbund und Rotation ([4d51cad](https://github.com/Savox76/eve-online-foundry/commit/4d51cad2f8b1b12d5e21c979548d165c854758f9))
* **backend:** Sidecar mit SQLite, Migration beim Start und ESI-Client ([5175383](https://github.com/Savox76/eve-online-foundry/commit/5175383720a85378daf74936bcffcb2676533f5f))
* **frontend:** Login-Oberfläche und Bestandstabelle ([514a2f2](https://github.com/Savox76/eve-online-foundry/commit/514a2f2af98884ffef827dc69e8e8316b0d332e9))
* **frontend:** Oberfläche mit acht Tabs und Betriebszustand ([613ba6e](https://github.com/Savox76/eve-online-foundry/commit/613ba6e5dd0a4062ffe7de685aaae19ea7e35faf))
* **shell:** Tauri-Schale mit Sidecar-Handschlag ([69fee20](https://github.com/Savox76/eve-online-foundry/commit/69fee2002ddea3921cba5b9bafbd1609933aa1a3))


### Behoben

* **ci:** Sidecar-Attrappe anlegen, sonst scheitert der Schalen-Job ([7e644f6](https://github.com/Savox76/eve-online-foundry/commit/7e644f6d9aad565e85a4debfff0d50068a4b921c))
* **frontend:** Favicon aus derselben Quelle wie das Anwendungssymbol ([7ec0ba2](https://github.com/Savox76/eve-online-foundry/commit/7ec0ba2e46ca3bcaa05037ad091a41291ecf34b3))
* **release:** Versionsnummer wirklich ueberall anheben ([580496e](https://github.com/Savox76/eve-online-foundry/commit/580496ebf9bed4bf75672fc8f3b4b90f1caa8ba3))

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
