import { Kennzahl } from "@/components/Kennzahl";
import type { AmpelZustand } from "@/components/Ampel";
import { useStatus } from "@/hooks/useStatus";
import { formatAlter, formatMenge } from "@/lib/format";

/**
 * Der Betriebszustand.
 *
 * In Phase 0 ist das die einzige Ansicht mit echten Daten -- und die
 * richtige: sie beweist, dass Fenster, Sidecar, Datenbank und SDE-Import
 * zusammenspielen. Genau darauf zielt der Meilenstein der Phase.
 */
export function StatusPanel() {
  const { data, error, isPending } = useStatus();

  if (isPending) {
    return <p className="text-sm text-muted">Verbinde mit dem Backend …</p>;
  }

  if (error) {
    return (
      <div className="border-l-2 border-crit bg-surface px-4 py-3">
        <p className="text-sm font-semibold text-crit">Kein Kontakt zum Backend</p>
        <p className="mt-1 text-sm text-muted">{error.message}</p>
      </div>
    );
  }

  const kompatibel: AmpelZustand =
    data.compatibility.state === "ok"
      ? "ok"
      : data.compatibility.state === "warn"
        ? "warn"
        : "crit";

  const fehlerbudget = data.rate_limit.error_remain;
  const budgetZustand: AmpelZustand =
    fehlerbudget === null ? "unbekannt" : fehlerbudget < 20 ? "crit" : fehlerbudget < 60 ? "warn" : "ok";

  const sdeZeilen = data.sde
    ? Object.values(data.sde.row_counts).reduce((summe, wert) => summe + wert, 0)
    : 0;

  return (
    <div>
      <div className="grid gap-px bg-line sm:grid-cols-2 lg:grid-cols-4">
        <Kennzahl titel="Version" wert={data.version} zusatz={`Schema ${data.database_revision ?? "—"}`} />
        <Kennzahl
          titel="Static Data"
          wert={data.sde ? data.sde.build : "nicht importiert"}
          zusatz={
            data.sde
              ? `${formatMenge(sdeZeilen)} Zeilen · ${formatAlter(data.sde.completed_at)}`
              : "python -m app.sde.importer --source …"
          }
          zustand={data.sde ? "ok" : "warn"}
        />
        <Kennzahl
          titel="Kompatibilitätsdatum"
          wert={data.compatibility.date}
          zusatz={`${data.compatibility.age_days} von ${data.compatibility.guaranteed_days} Tagen alt`}
          zustand={kompatibel}
        />
        <Kennzahl
          titel="ESI-Fehlerbudget"
          wert={fehlerbudget === null ? "—" : formatMenge(fehlerbudget)}
          zusatz={
            data.rate_limit.breaker_seconds_left > 0
              ? `Pause noch ${Math.ceil(data.rate_limit.breaker_seconds_left)} s`
              : "noch kein Abruf gelaufen"
          }
          zustand={budgetZustand}
        />
      </div>
      <p className="mt-2 break-all font-mono text-[11px] text-faint">
        Daten:{" "}
        <span className="text-muted">{data.data_dir}</span>{" "}
        {data.portable ? "— portabel, neben der Anwendung" : "— Ablage des Systems"}
      </p>
    </div>
  );
}
