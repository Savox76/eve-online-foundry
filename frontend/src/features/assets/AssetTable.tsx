import { useMemo, useState } from "react";
import { useAssetChanges, useAssets, useLocations, useSyncAssets } from "@/hooks/useAssets";
import { useCharacters } from "@/hooks/useCharacters";
import { formatAlter, formatMenge, formatVolumen } from "@/lib/format";

type Ansicht = "bestand" | "delta";

/**
 * Der Tab Assets.
 *
 * Zwei Nutzungsmuster prägen ihn (Kapitel 15): gezielte Suche („wo liegen
 * meine Morphite?") und wiederkehrende Kontrolle („was hat sich seit gestern
 * bewegt?"). Deshalb zwei Ansichten auf denselben Daten — und in beiden eine
 * dichte, sortierbare Tabelle statt großflächiger Kacheln.
 */
export function AssetTable() {
  const characters = useCharacters();
  const [charakter, setCharakter] = useState<number | undefined>();
  const [suche, setSuche] = useState("");
  const [ort, setOrt] = useState<number | null>(null);
  const [ansicht, setAnsicht] = useState<Ansicht>("bestand");

  const gewaehlt = charakter ?? characters.data?.characters[0]?.character_id;
  const assets = useAssets({ characterId: gewaehlt, search: suche, locationId: ort });
  const orte = useLocations(gewaehlt);
  const changes = useAssetChanges(gewaehlt);
  const sync = useSyncAssets();

  const gesamtVolumen = useMemo(
    () => (assets.data?.rows ?? []).reduce((summe, zeile) => summe + (zeile.total_volume ?? 0), 0),
    [assets.data],
  );

  if (characters.data?.characters.length === 0) {
    return (
      <p className="max-w-[70ch] border-l-2 border-cool bg-surface px-4 py-3 text-sm text-muted">
        Noch kein Charakter verbunden. Über das Nutzermenü oben rechts lässt sich einer hinzufügen —
        danach holt <strong className="text-ink">Bestände abrufen</strong> die erste Liste.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={gewaehlt ?? ""}
          onChange={(event) => setCharakter(Number(event.target.value))}
          className="border border-line bg-surface px-2 py-1.5 text-sm"
          aria-label="Charakter"
        >
          {characters.data?.characters.map((character) => (
            <option key={character.character_id} value={character.character_id}>
              {character.name}
            </option>
          ))}
        </select>

        <input
          type="search"
          value={suche}
          onChange={(event) => setSuche(event.target.value)}
          placeholder="Typ suchen …"
          className="min-w-56 flex-1 border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-faint"
          aria-label="Typ suchen"
        />

        <select
          value={ort ?? ""}
          onChange={(event) => setOrt(event.target.value ? Number(event.target.value) : null)}
          className="border border-line bg-surface px-2 py-1.5 text-sm"
          aria-label="Ort"
        >
          <option value="">Alle Orte</option>
          {(orte.data ?? []).map((eintrag) => (
            <option key={eintrag.location_id ?? "unbekannt"} value={eintrag.location_id ?? ""}>
              {eintrag.name} ({eintrag.stacks})
            </option>
          ))}
        </select>

        <button
          type="button"
          onClick={() => gewaehlt && sync.mutate(gewaehlt)}
          disabled={!gewaehlt || sync.isPending}
          className="border border-accent px-3 py-1.5 text-sm text-accent transition-colors hover:bg-accent hover:text-ground disabled:cursor-wait disabled:opacity-50"
        >
          {sync.isPending ? "Hole …" : "Bestände abrufen"}
        </button>
      </div>

      {sync.data && (
        <p className="text-sm text-muted">
          {sync.data.unchanged
            ? "Unverändert — ESI hatte nichts Neues. Das kostet fast kein Budget."
            : `${formatMenge(sync.data.fetched)} Einträge · ${sync.data.added} neu, ` +
              `${sync.data.removed} weg, ${sync.data.quantity_changes} Menge, ${sync.data.moved} bewegt`}
        </p>
      )}
      {sync.error && <p className="text-sm text-crit">{sync.error.message}</p>}

      <div className="flex gap-1 border-b border-line">
        {(
          [
            ["bestand", "Bestand"],
            ["delta", "Seit gestern"],
          ] as const
        ).map(([wert, beschriftung]) => (
          <button
            key={wert}
            type="button"
            onClick={() => setAnsicht(wert)}
            className={`border-b-2 px-3 py-1.5 font-mono text-[11px] ${
              ansicht === wert
                ? "border-accent text-accent"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {beschriftung}
          </button>
        ))}
      </div>

      {ansicht === "bestand" ? (
        <>
          <div className="flex flex-wrap gap-x-6 gap-y-1 font-mono text-[11px] text-faint">
            <span>{formatMenge(assets.data?.total ?? 0)} Stapel</span>
            <span className="tabular">{formatVolumen(gesamtVolumen)} auf dieser Seite</span>
            <span>Datenstand {formatAlter(assets.data?.fetched_at)}</span>
            {(assets.data?.unresolved ?? 0) > 0 && (
              <span className="text-warn">
                {assets.data?.unresolved} ohne auflösbaren Ort
              </span>
            )}
          </div>

          <div className="overflow-x-auto border border-line">
            <table className="w-full min-w-[52rem] text-sm">
              <thead>
                <tr className="border-b border-line bg-raised text-left font-mono text-[10px] uppercase tracking-widest text-faint">
                  <th className="px-3 py-2">Typ</th>
                  <th className="px-3 py-2">Gruppe</th>
                  <th className="num px-3 py-2 text-right">Menge</th>
                  <th className="num px-3 py-2 text-right">Volumen</th>
                  <th className="px-3 py-2">Ort</th>
                </tr>
              </thead>
              <tbody>
                {(assets.data?.rows ?? []).map((zeile) => (
                  <tr key={zeile.item_id} className="border-b border-line/60 last:border-0">
                    <td className="px-3 py-1.5">
                      {zeile.type_name}
                      {zeile.is_blueprint_copy && (
                        <span className="ml-2 font-mono text-[10px] text-cool">BPC</span>
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-muted">{zeile.group_name}</td>
                    <td className="num px-3 py-1.5 text-right">{formatMenge(zeile.quantity)}</td>
                    <td className="num px-3 py-1.5 text-right text-muted">
                      {zeile.total_volume === null ? "—" : formatVolumen(zeile.total_volume)}
                    </td>
                    <td className="px-3 py-1.5 text-muted">
                      {zeile.location_name}
                      {zeile.container_name && (
                        <span className="text-faint"> › {zeile.container_name}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {assets.data?.rows.length === 0 && (
            <p className="text-sm text-muted">
              {suche
                ? `Kein Typ passt auf \u201e${suche}\u201c.`
                : "Noch keine Bestände geholt \u2014 \u201eBestände abrufen\u201c startet den ersten Sync."}
            </p>
          )}
        </>
      ) : (
        <div className="overflow-x-auto border border-line">
          <table className="w-full min-w-[44rem] text-sm">
            <thead>
              <tr className="border-b border-line bg-raised text-left font-mono text-[10px] uppercase tracking-widest text-faint">
                <th className="px-3 py-2">Was</th>
                <th className="px-3 py-2">Typ</th>
                <th className="num px-3 py-2 text-right">Differenz</th>
                <th className="px-3 py-2">Ort</th>
                <th className="px-3 py-2">Wann</th>
              </tr>
            </thead>
            <tbody>
              {(changes.data?.rows ?? []).map((zeile) => (
                <tr key={zeile.id} className="border-b border-line/60 last:border-0">
                  <td className="px-3 py-1.5">{ART[zeile.kind]}</td>
                  <td className="px-3 py-1.5">{zeile.type_name}</td>
                  <td
                    className={`num px-3 py-1.5 text-right ${
                      (zeile.delta ?? 0) < 0 ? "text-crit" : "text-ok"
                    }`}
                  >
                    {zeile.delta === null
                      ? "—"
                      : `${zeile.delta > 0 ? "+" : ""}${formatMenge(zeile.delta)}`}
                  </td>
                  <td className="px-3 py-1.5 text-muted">{zeile.location_name}</td>
                  <td className="px-3 py-1.5 text-muted">{formatAlter(zeile.observed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {changes.data?.rows.length === 0 && (
            <p className="px-3 py-3 text-sm text-muted">
              Seit dem letzten Tag hat sich nichts bewegt. Das Delta entsteht erst ab dem zweiten
              Abruf — der erste hat nichts, womit er vergleichen könnte.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

const ART: Record<string, string> = {
  added: "neu",
  removed: "weg",
  quantity: "Menge",
  moved: "bewegt",
};
