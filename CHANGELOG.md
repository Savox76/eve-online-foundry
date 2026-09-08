# Changelog

Wird aus den Conventional Commits erzeugt und mit der Anwendung ausgeliefert —
damit der Updater „was ist neu“ anzeigen kann, ohne die GitHub-API zu
befragen.

Versioniert nach [SemVer](https://semver.org/lang/de/), unterhalb von `1.0.0`
bis das Datenmodell stabil ist. Eine feste Regel hängt am Updater: **ein
Release mit Datenbank-Migration ist niemals ein Patch-Release.**

## [0.3.0](https://github.com/Savox76/eve-online-foundry/compare/v0.2.0...v0.3.0) (2026-09-08)

Ab diesem Release entstehen mit jedem Tag fertige Installer. Für Windows ein
`.msi` und ein NSIS-Setup, für Linux ein `.deb` und ein AppImage — alle
x86-64, alle an das Release gehängt, ohne dass jemand etwas anstoßen muss.

Sie sind **unsigniert**: Windows zeigt beim Setup den SmartScreen-Hinweis, und
der Updater bleibt aus, weil er grundsätzlich nichts Unsigniertes annimmt. Was
dafür fehlt, steht in `docs/runbook.md`.


### Neu

* **release:** Installer fuer Windows und Linux automatisch bauen ([0ab278e](https://github.com/Savox76/eve-online-foundry/commit/0ab278e8cacd243e4d8447f1dd4e91f608c6fe1c))

## [0.2.0](https://github.com/Savox76/eve-online-foundry/compare/f8ad2a2...v0.2.0) — „Erste Schmelze“ (2026-09-07)

Die erste Ausbaustufe, die man benutzen kann: die Anwendung startet, ein
Charakter meldet sich über EVE SSO an, und seine Bestände stehen in einer
durchsuchbaren Tabelle. Darunter liegt das ganze Fundament — Sidecar,
SQLite mit Migration beim Start, Static-Data-Import und ein ESI-Client mit
Cache, Rate-Limit-Budget und Circuit Breaker — bewusst noch schmal
bespielt, aber vollständig.


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

### Bekannte Grenzen

- Der Login ist gegen einen nachgebauten SSO-Dienst getestet, nicht gegen
  `login.eveonline.com`. Der erste echte Login ist der eigentliche Test.
- Von den acht Tabs hat nur **Assets** Inhalt; die übrigen sagen, ab welcher
  Phase sie welchen bekommen.
- Das Asset-Delta beginnt beim ersten Sync und lässt sich nicht rückwirkend
  nachholen.
- Es gibt noch keine signierten Installer und damit keinen Updater — gebaut
  wird aus dem Quelltext.

## 0.1.0

Nie veröffentlicht und ohne Tag: die Nummer steht nur im Manifest von
release-please und markiert den Ur-Commit als Nullpunkt. Alles Inhaltliche
steht in 0.2.0.
