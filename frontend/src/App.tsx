import { useState } from "react";
import { StatusPanel } from "@/features/status/StatusPanel";
import { TABS } from "@/routes/tabs";

/**
 * Die Schale der Oberflaeche: acht Tabs, dichte Tabellen, dunkles Thema.
 *
 * In Phase 0 ist noch kein Fachinhalt drin — und die Tabs sagen das auch,
 * statt eine leere Tabelle zu zeigen, die wie ein Fehler aussieht. Was hier
 * schon steht, ist die Navigation aus Kapitel 15 und der Betriebszustand, an
 * dem sich ablesen laesst, ob Fenster, Sidecar, Datenbank und SDE zueinander
 * finden.
 */
export function App() {
  const [aktiv, setAktiv] = useState(TABS[0]!.id);
  const tab = TABS.find((eintrag) => eintrag.id === aktiv) ?? TABS[0]!;

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
          <p className="text-xs text-faint">Phase 0 — Fundament</p>
        </div>
      </header>

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
        <section aria-labelledby="tab-titel" className="mb-8">
          <h2 id="tab-titel" className="text-lg font-semibold tracking-tight">
            {tab.label}
          </h2>
          <p className="mt-1 text-sm text-muted">{tab.frage}</p>
          <p className="mt-3 max-w-[70ch] border-l-2 border-cool bg-surface px-4 py-3 text-sm text-muted">
            Dieser Tab bekommt seinen Inhalt in <strong className="text-ink">Phase {tab.phase}</strong>{" "}
            des Phasenplans. Bis dahin steht hier bewusst nichts — eine leere Tabelle sieht aus wie ein
            Fehler.
          </p>
        </section>

        <section aria-labelledby="status-titel">
          <h2
            id="status-titel"
            className="mb-3 font-mono text-[10px] uppercase tracking-widest text-faint"
          >
            Betriebszustand
          </h2>
          <StatusPanel />
        </section>
      </main>

      <footer className="border-t border-line px-6 py-3 text-xs text-faint">
        EVE Online und alle zugehörigen Marken sind Eigentum von CCP hf. Drittanbieter-Werkzeug unter
        dem EVE Developer License Agreement.
      </footer>
    </div>
  );
}
