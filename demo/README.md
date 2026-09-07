# demo/ — synthetische Daten

Diese Daten sind **vollständig erfunden**. Keine ID, kein Name und kein
Standort hier stammt aus einem echten Spielstand.

## Warum das eine harte Regel ist

Das Repository ist öffentlich, und Corp-Daten sind in EVE Aufklärungsmaterial.
Echte Struktur-IDs, Standorte, Bestandshöhen oder Doktrin-Fittings sind genau
die Information, nach der Gegner suchen — und aus der Git-Historie eines
öffentlichen Repos bekommt man sie nicht wieder heraus.

Deshalb gilt ausnahmslos:

- **Testfixtures** verwenden ausschließlich erfundene IDs — die aus diesem
  Verzeichnis.
- **Screenshots** für die Projektseite entstehen automatisiert gegen eine
  Instanz, die mit diesen Daten befüllt ist. Nicht „möglichst", sondern per
  Konstruktion: was hier nicht drinsteht, kann auf keinem Bild auftauchen.
- **Fehlerberichte** mit echten Beständen gehören in den Corp-Discord, nicht in
  den öffentlichen Issue-Tracker.

## Wie die Daten erkennbar synthetisch sind

| Art | Bereich | Echt in EVE? |
|---|---|---|
| `type_id` | `9_900_xxx` | nein — echte Typen liegen weit darunter |
| `group_id` | `9_910_xxx` | nein |
| `category_id` | `9_920_xxx` | nein |
| `region_id` | `9_930_xxx` | nein — echte Regionen sind `10000xxx` |
| `system_id` | `9_940_xxx` | nein |
| `station_id` | `9_950_xxx` | nein — echte NPC-Stationen sind `600xxxxx` |
| Namen | erfunden | keiner existiert im Spiel |

Wer eine Zahl aus diesen Bereichen in einem Bugreport sieht, weiß sofort:
das kommt aus der Demo, nicht aus einem Spielstand.

## Inhalt

`sde/` — ein winziger, aber strukturell vollständiger Static Data Export im
JSONL-Format. Er deckt jede Form ab, die der Importer beherrschen muss:
verschachtelte Blueprint-Aktivitäten, lokalisierte Namen, Materiallisten
sowohl als Liste als auch als ID-indiziertes Objekt, ein PI-Schema mit Ein-
und Ausgang.

```bash
cd backend
python -m app.sde.importer --source ../demo/sde --build demo-001
```
