/**
 * Eine Ampel. Ueberall dort, wo eine Zahl allein nicht sagt, ob sie gut ist --
 * Lagerreichweite, Fehlerbudget, Alter des Kompatibilitaetsdatums.
 */
export type AmpelZustand = "ok" | "warn" | "crit" | "unbekannt";

const FARBEN: Record<AmpelZustand, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  crit: "bg-crit",
  unbekannt: "bg-faint",
};

export function Ampel({ zustand, titel }: { zustand: AmpelZustand; titel: string }) {
  return (
    <span
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${FARBEN[zustand]}`}
      role="img"
      aria-label={titel}
      title={titel}
    />
  );
}
