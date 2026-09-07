import type { ReactNode } from "react";
import { Ampel, type AmpelZustand } from "./Ampel";

export function Kennzahl({
  titel,
  wert,
  zusatz,
  zustand,
}: {
  titel: string;
  wert: ReactNode;
  zusatz?: ReactNode;
  zustand?: AmpelZustand;
}) {
  return (
    <div className="border border-line bg-surface px-4 py-3">
      <div className="mb-1 flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-faint">
        {zustand && <Ampel zustand={zustand} titel={titel} />}
        {titel}
      </div>
      <div className="tabular text-[15px] font-semibold leading-tight">{wert}</div>
      {zusatz && <div className="mt-1 text-xs text-muted">{zusatz}</div>}
    </div>
  );
}
