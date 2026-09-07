/**
 * Der einzige Weg nach draussen.
 *
 * Das Fenster spricht ausschliesslich mit dem eigenen Backend auf der
 * Loopback-Adresse, und zwar nur mit dem Sitzungsgeheimnis, das die Schale
 * beim Start erzeugt hat. Im Entwicklungsbetrieb gibt es keine Schale --
 * dort haengt der Vite-Proxy den Header an.
 */

import { sessionSecret } from "./bridge";

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

async function headers(): Promise<HeadersInit> {
  const secret = await sessionSecret();
  return secret ? { [SESSION_HEADER]: secret } : {};
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return request<T>("GET", path, { signal });
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>("POST", path, { body });
}

export async function apiDelete(path: string): Promise<void> {
  await request<void>("DELETE", path, {});
}

async function request<T>(
  method: string,
  path: string,
  { body, signal }: { body?: unknown; signal?: AbortSignal },
): Promise<T> {
  const base = await headers();
  const response = await fetch(path, {
    method,
    signal,
    headers: body === undefined ? base : { ...base, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text();
    }
    throw new ApiError(errorMessage(response.status, detail), response.status, detail);
  }
  if (response.status === 204) return undefined as T;
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
