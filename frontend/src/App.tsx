import { useState } from "react";
import { AssetTable } from "@/features/assets/AssetTable";
import { CharacterPanel } from "@/features/auth/CharacterPanel";
import { StatusPanel } from "@/features/status/StatusPanel";
import { useCharacters } from "@/hooks/useCharacters";
import { TABS } from "@/routes/tabs";

/**
 * Die Schale der Oberfläche: acht Tabs, dichte Tabellen, dunkles Thema.
 *
 * Der Tab **Assets** hat Inhalt (Phase 2, Durchstich), die übrigen sagen, ab
 * welcher Phase sie welchen bekommen. Das ist Absicht: eine leere Tabelle
 * sieht aus wie ein Fehler.
 *
 * **Admin** steht bewusst nicht in der Hauptnavigation, sondern hinter dem
 * Nutzermenü — Charaktere, Token-Gesundheit und Betriebszustand sieht man
 * selten und dann meist im Fehlerfall (Kapitel 15).
 */
export function App() {
  const [aktiv, setAktiv] = useState(TABS[0]!.id);
  const [menueOffen, setMenueOffen] = useState(false);
  const characters = useCharacters();
  const tab = TABS.find((eintrag) => eintrag.id === aktiv) ?? TABS[0]!;

  const verbunden = characters.data?.characters.length ?? 0;
  const mitProblem =
    characters.data?.characters.filter((character) => character.status !== "ok").length ?? 0;

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-line bg-surface px-6 py-4">
        <div className="flex items-baseline justify-between gap-4">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-accent">
              Industrie-Werkzeug für EVE Online
            </p>
            <h1 className="mt-1 text-xl font-semibold tracking-tight">New Eden Foundry</h1>
          </div>
          <button
            type="button"
            onClick={() => setMenueOffen((offen) => !offen)}
            aria-expanded={menueOffen}
            className={`border px-3 py-1.5 font-mono text-[11px] transition-colors ${
              mitProblem > 0
                ? "border-crit text-crit"
                : "border-line text-muted hover:border-muted hover:text-ink"
            }`}
          >
            {verbunden === 0
              ? "Kein Charakter verbunden"
              : `${verbunden} Charakter${verbunden === 1 ? "" : "e"}`}
            {mitProblem > 0 && ` · ${mitProblem} mit Problem`}
          </button>
        </div>
      </header>

      {menueOffen && (
        <div className="border-b border-line bg-surface px-6 py-5">
          <CharacterPanel />
          <div className="mt-6">
            <h3 className="mb-3 font-mono text-[10px] uppercase tracking-widest text-faint">
              Betriebszustand
            </h3>
            <StatusPanel />
          </div>
        </div>
      )}

      <nav className="border-b border-line bg-ground" aria-label="Hauptnavigation">
        <div className="flex gap-1 overflow-x-auto px-4">
          {TABS.map((eintrag) => {
            const gewaehlt = eintrag.id === aktiv;
            return (
              <button
                key={eintrag.id}
                type="button"
                onClick={() => setAktiv(eintrag.id)}
                aria-current={gewaehlt ? "page" : undefined}
                className={`whitespace-nowrap border-b-2 px-3 py-2.5 font-mono text-[11px] tracking-wide transition-colors ${
                  gewaehlt
                    ? "border-accent text-accent"
                    : "border-transparent text-muted hover:text-ink"
                }`}
              >
                {eintrag.label}
              </button>
            );
          })}
        </div>
      </nav>

      <main className="flex-1 px-6 py-6">
        <section aria-labelledby="tab-titel">
          <h2 id="tab-titel" className="text-lg font-semibold tracking-tight">
            {tab.label}
          </h2>
          <p className="mb-5 mt-1 text-sm text-muted">{tab.frage}</p>

          {tab.id === "assets" ? (
            <AssetTable />
          ) : (
            <p className="max-w-[70ch] border-l-2 border-cool bg-surface px-4 py-3 text-sm text-muted">
              Dieser Tab bekommt seinen Inhalt in{" "}
              <strong className="text-ink">Phase {tab.phase}</strong> des Phasenplans. Bis dahin
              steht hier bewusst nichts — eine leere Tabelle sieht aus wie ein Fehler.
            </p>
          )}
        </section>
      </main>

      <footer className="border-t border-line px-6 py-3 text-xs text-faint">
        EVE Online und alle zugehörigen Marken sind Eigentum von CCP hf. Drittanbieter-Werkzeug unter
        dem EVE Developer License Agreement.
      </footer>
    </div>
  );
}
