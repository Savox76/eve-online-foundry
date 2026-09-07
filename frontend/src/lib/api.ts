/**
 * Der einzige Weg nach draussen.
 *
 * Das Fenster spricht ausschliesslich mit dem eigenen Backend auf der
 * Loopback-Adresse, und zwar nur mit dem Sitzungsgeheimnis, das die Schale
 * beim Start erzeugt hat. Im Entwicklungsbetrieb gibt es keine Schale --
 * dort haengt der Vite-Proxy den Header an.
 */

declare global {
  interface Window {
    __FOUNDRY__?: { sessionSecret?: string; backendPort?: number };
  }
}

export const SESSION_HEADER = "X-Foundry-Session";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function headers(): HeadersInit {
  const secret = window.__FOUNDRY__?.sessionSecret;
  return secret ? { [SESSION_HEADER]: secret } : {};
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { headers: headers(), signal });

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text();
    }
    throw new ApiError(errorMessage(response.status, detail), response.status, detail);
  }
  return (await response.json()) as T;
}

/**
 * Fehlerdialoge statt Fehlerseiten (Kapitel 17, Phase 9). Der Anfang davon:
 * die Statuscodes, die in diesem Werkzeug tatsaechlich etwas bedeuten,
 * bekommen einen Satz, der weiterhilft.
 */
function errorMessage(status: number, detail: unknown): string {
  const fromServer =
    detail && typeof detail === "object" && "detail" in detail
      ? String((detail as { detail: unknown }).detail)
      : undefined;

  switch (status) {
    case 401:
      return "Das Fenster ist nicht am eigenen Backend angemeldet. Anwendung neu starten.";
    case 403:
      return fromServer ?? "Kein Zugriff — fehlt eine In-Game-Rolle oder Docking-Zugriff?";
    case 429:
      return "ESI-Rate-Limit erreicht. Der nächste Abruf wartet automatisch.";
    case 503:
      return fromServer ?? "ESI-Fehlerbudget aufgebraucht. Abrufe pausieren kurz.";
    default:
      return fromServer ?? `Unerwartete Antwort (${status}).`;
  }
}
