# ESI: Regeln, Fallstricke und Bauregeln

> Alle Angaben nach dem Stand der offiziellen Entwicklerdokumentation im
> September 2026. **Kompatibilitätsdatum, Rate-Limit-Werte und Scope-Strings
> vor jeder Änderung gegen `esi.evetech.net/meta/openapi.json` gegenprüfen** —
> das ist die einzige verbindliche Quelle.

Dieser Abschnitt ist kein Feinschliff. CCP kündigt ausdrücklich temporäre und
permanente Sperren für Anwendungen an, die Caching umgehen oder sich nicht
identifizieren.

## Kompatibilitätsdatum

ESI hat versionierte Pfade (`/v1/`, `/v5/`) durch ein datumsbasiertes Modell
abgelöst. Jeder Request schickt `X-Compatibility-Date`. **Ohne den Header
nutzt ESI das älteste verfügbare Datum** — den Stand, den niemand will.

- Steht als **eine Konstante** in `backend/app/core/config.py`:
  `ESI_COMPATIBILITY_DATE`. Anheben ist damit ein bewusster, testbarer Commit
  statt eines schleichenden Drifts.
- Der Client setzt sie auf jedem Request; ein Test in
  `tests/test_esi_client.py` prüft das nach.
- Beim Start wird das Datum geprüft: ein **Zukunftsdatum bricht den Start ab**
  (ESI würde solche Requests ablehnen), ein alterndes wird geloggt.
- CCP sichert mindestens ein Jahr Rückwärtskompatibilität zu. Ab 300 Tagen
  warnt die Anwendung, ab 365 meldet sie einen Fehler.

**Beim Anheben:** Commit-Typ `esi:` verwenden und das Issue-Label
`esi-change` setzen. Dann ist in fünf Sekunden sichtbar, was betroffen war.

## User-Agent

Pflicht, nicht Höflichkeit. Wird aus `app/core/config.py` gebildet:

```
NewEdenFoundry/0.1.0 (mario.elssner@googlemail.com; +https://github.com/Savox76/eve-online-foundry) httpx
```

Fehlt die Kontaktadresse, steht `no-contact-configured` drin — sichtbar,
statt die Zeile stillschweigend zu kürzen. Die Adresse kommt aus
`FOUNDRY_CONTACT_EMAIL`.

## Caching ist Pflicht

| Mechanismus | Verhalten |
|---|---|
| `Expires` | Vor Ablauf wird **gar kein Request gestellt**. Der Cache-Eintrag kennt den Zeitpunkt, der Client bricht vorher ab. |
| `ETag` | Wird gespeichert und als `If-None-Match` zurückgeschickt. `304` = unverändert, kein Traffic, ein Token statt zwei. |
| `Last-Modified` | Muss über **alle Seiten** eines paginierten Abrufs identisch sein. Weicht es ab, hat sich der Datensatz mitten im Abruf geändert; der ganze Abruf wird verworfen (`EsiPaginationError`). |

## Zwei Limits gleichzeitig

### Rate Limit — Token-Budget je Routengruppe

Gleitendes Fenster, typisch `150/15m`, Gruppe im Header `X-Ratelimit-Group`.

| Antwort | Kosten |
|---|---:|
| 2xx | 2 |
| 3xx | 1 |
| 4xx | 5 |
| 5xx | 0 |

Ein `304` kostet halb so viel wie ein `200`; ein Client-Fehler kostet mehr als
zwei Erfolge. Sauberes Caching zahlt sich doppelt aus, schlampiges
Fehlerverhalten bestraft sich doppelt.

Bei einem `429` wird `Retry-After` beachtet und **nur die betroffene Gruppe**
pausiert.

### Error Limit — global

100 Nicht-2xx/3xx-Antworten pro Minute, dann `420` auf **allen** Routen.
Header: `X-ESI-Error-Limit-Remain`, `X-ESI-Error-Limit-Reset`.

Der Circuit Breaker schließt bei **unter 20 verbleibenden Fehlern**, nicht
erst bei 0 — zwischen Messung und nächstem Request sind schon Antworten
unterwegs. Ein `420` sperrt alle Gruppen bis zum Reset.

### Architektonisch

- **Ein** `EsiBudget` im Prozess. Der Asset-Sync von Charakter A und der
  Preisabruf von Charakter B teilen sich dasselbe Budget.
- Bei Abweichung zwischen eigener Rechnung und Server-Header gilt der
  **kleinere** Wert. Ein zu optimistischer Zähler ist genau der Fehler, der
  zur Sperre führt.
- Zeitpläne mit **Jitter**. Zehn Pläne auf `:00` sind ein Ansturm, zehn
  gestreute sind Verkehr.
- Ein Intervall **darf nie unter der ESI-Cache-Dauer liegen** — der
  Scheduler weist solche Zeitpläne ab, statt sie zu registrieren.
- Jeder Lauf wird in `esi_sync_runs` protokolliert: Route, Entität,
  Statuscode, ETag, verbrauchte Tokens, Dauer. Ohne dieses Log ist ein
  Quotenproblem nicht diagnostizierbar.

## Sync-Intervalle

| Daten | ESI-Cache | Foundry |
|---|---|---|
| Assets (Char und Corp) | 1 h | 70 min + Jitter |
| Blueprints | 1 h | 70 min + Jitter |
| Industrie-Jobs | 5 min | 10 min |
| Kostenindizes | 1 h | 1 × täglich |
| Referenzpreise | ~1 h | 1 × täglich |
| Order-Snapshots (fünf Hubs) | extern, 30 min | stündlich |
| Markthistorie | extern, täglich | 1 × nachts |
| PI-Kolonien | 10 min | 30 min |
| Skills, Rollen | 2 h / 1 h | 6 h |

Der Einstiegspunkt ist bei einer Desktop-Anwendung nicht die Uhrzeit, sondern
die Frage **„wie alt sind die Daten?"** — beim Start und danach im Intervall.
Ein Server darf „nachts um vier" sagen; eine Anwendung, die nur läuft wenn
jemand sie startet, nicht.

## Fallstricke, die fast jeden erwischen

**Der `scp`-Claim ist nicht immer eine Liste.** Bei genau einem gewährten
Scope liefert das JWT einen String statt eines Arrays. `normalize_scp_claim()`
in `app/esi/scopes.py` fängt das ab. Ohne Normalisierung bekommt man beim
ersten Minimal-Login eine Liste einzelner Buchstaben.

**Der `owner`-Claim ändert sich beim Charakter-Transfer.** Mitspeichern; ändert
er sich, wurde der Charakter verkauft — alle Tokens sofort verwerfen und neu
autorisieren lassen. Sonst zeigt Foundry fremde Assets an. *(Phase 1.)*

**Refresh Tokens sind flüchtig.** CCP weist native Anwendungen gesondert
darauf hin: bei **jedem** Refresh mit einem neuen Token rechnen und ihn
speichern. Wer den alten behält, fliegt beim übernächsten Start raus.
*(Phase 1.)*

**403 ist kein Fehler.** Eine Struktur ohne Docking-Zugriff oder eine
Corp-Route ohne die passende In-Game-Rolle antwortet mit 403. Das gehört
sichtbar gemeldet und mit einem Rückfall angezeigt („Unbekannte Struktur
#1035…"), nicht als leere Liste verschwiegen — sonst hängt der ganze Sync an
einer fremden Struktur.

**Kein Client Secret.** Native Anwendungen arbeiten mit PKCE. Taucht irgendwo
ein `client_secret` auf, stimmt der Flow nicht — `.gitleaks.toml` hat dafür
eine eigene Regel.

## Bauregeln

Diese beiden Regeln sind keine Stilfrage, sondern die Grenze zwischen
Bedienhilfe und Automatisierung. Automatisierung ist im EVE Developer License
Agreement eindeutig untersagt.

### UI-Endpunkte

`POST /ui/openwindow/…` und `POST /ui/autopilot/waypoint/` wirken auf den
laufenden Client. Sie sind offizielle Endpunkte mit eigenem Zustimmungs-Scope,
und der dokumentierte Anwendungsfall ist genau dieser: jemand drückt einen
Knopf, im Spiel öffnet sich das passende Fenster.

> **Jeder UI-Aufruf ist die unmittelbare Folge eines Klicks durch den Besitzer
> des Charakters.** Nie zeitgesteuert, nie aus dem Scheduler, nie gebündelt,
> nie für einen fremden Charakter. Ein UI-Aufruf ohne menschlichen Klick wird
> nicht gebaut — auch nicht „nur zum Testen".

### Mail

Lesen und Antworten ist ausdrücklich vorgesehen; die Grenze ist Spam, und
CCP misst sie an der Wirkung, nicht an einem Schwellwert.

> **Gesendet wird ausschließlich, was ein Mensch getippt und abgeschickt hat.**
> Keine Serienmail, keine Vorlage an eine Empfängerliste, keine automatische
> Antwort, keine Benachrichtigung per EVE-Mail — dafür ist Discord da.
> Foundry verschickt niemals von sich aus eine Mail.

Technisch: etwa fünf Mails pro Minute, darüber antwortet ESI mit `520`.

### Vertraulichkeit von Mail

Auch im Einzelplatzbetrieb einzuhalten — sonst müsste es beim ersten
Corp-Server nachträglich eingebaut werden:

- Der Mail-Scope ist **optional und je Charakter**.
- Mail-Tabellen sind die **einzigen** im System, die auf `user_id` filtern
  statt auf `corporation_id`.
- Mailinhalte landen **nie** in `esi_sync_runs`, Logs oder Fehlermeldungen.
- Scope entziehen **löscht** die lokal gespeicherten Mails dieses Charakters.

## Was vor dem Bau zu prüfen ist

Diese Angaben sind aus der Dokumentation übernommen und **nicht** gegen einen
echten Abruf verifiziert:

- [ ] Die Dateinamen und Feldnamen des JSONL-Exports in
      `app/sde/datasets.py`. `python -m app.sde.importer --report` sagt, was
      der tatsächliche Export enthält — das ist der erste Aufruf bei einem
      neuen Export.
- [ ] Die exakten Pfade und Scope-Strings der **Corporation Projects** —
      direkt aus `openapi.json` ziehen, nicht aus einem Blogpost.
- [ ] Ob die Rate-Limit-Gruppen im Routenkatalog denen entsprechen, die ESI
      im `X-Ratelimit-Group`-Header tatsächlich meldet. Der Client übernimmt
      die Server-Angabe, die lokale Zuordnung ist nur die Vorab-Annahme.
- [ ] Die Callback-URL (siehe offener Punkt in `architecture.md`).
