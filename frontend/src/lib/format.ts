/** Anzeigeformate. Deutsch, weil die Oberflaeche deutsch ist. */

const isk = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 2 });
const ganz = new Intl.NumberFormat("de-DE");

export function formatIsk(value: number): string {
  return `${isk.format(value)} ISK`;
}

export function formatMenge(value: number): string {
  return ganz.format(value);
}

/**
 * "Wie alt sind die Daten" ist in einem Werkzeug mit einstuendigem Cache
 * keine Nebensache, sondern eine Kernangabe (Kapitel 15). Deshalb steht sie
 * in jeder Ansicht -- und deshalb gibt es diese Funktion.
 */
export function formatAlter(iso: string | null | undefined, jetzt = new Date()): string {
  if (!iso) return "nie";
  const zeitpunkt = new Date(iso);
  if (Number.isNaN(zeitpunkt.getTime())) return "unbekannt";

  const sekunden = Math.max(0, Math.round((jetzt.getTime() - zeitpunkt.getTime()) / 1000));
  if (sekunden < 60) return "gerade eben";
  const minuten = Math.round(sekunden / 60);
  if (minuten < 60) return `vor ${minuten} min`;
  const stunden = Math.round(minuten / 60);
  if (stunden < 24) return `vor ${stunden} h`;
  const tage = Math.round(stunden / 24);
  return `vor ${tage} ${tage === 1 ? "Tag" : "Tagen"}`;
}

const volumen = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });

/**
 * Kubikmeter. Die Einheit, in der sich die Frage „passt das in einen Epithal?"
 * beantworten lässt — deshalb steht sie neben jeder Menge.
 */
export function formatVolumen(kubikmeter: number): string {
  return `${volumen.format(kubikmeter)} m³`;
}
