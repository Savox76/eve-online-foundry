/**
 * Die Bruecke zur Schale.
 *
 * Zwei Dinge kann nur die Schale, und beide sind wichtig:
 *
 * 1. **Das Sitzungsgeheimnis liefern.** Es entsteht im Rust-Elternprozess bei
 *    jedem Start neu und wird über einen Tauri-Befehl abgeholt.
 * 2. **Den Systembrowser öffnen.** Nicht ein eingebettetes Fenster: der Nutzer
 *    soll die echte Adresszeile von CCP sehen. Eine Anwendung, die das
 *    Login-Formular selbst anzeigt, ist von Phishing nicht zu unterscheiden.
 *
 * Im Entwicklungsbetrieb läuft keine Schale. Dann hängt der Vite-Proxy das
 * Geheimnis an und `window.open` tut es für den Login.
 */

let cachedSecret: string | null = null;

/** Läuft die Oberfläche in der Tauri-Schale oder im Browser? */
export function inShell(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function sessionSecret(): Promise<string> {
  if (cachedSecret !== null) return cachedSecret;
  if (!inShell()) {
    cachedSecret = "";
    return cachedSecret;
  }
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    cachedSecret = await invoke<string>("session_secret");
  } catch (error) {
    console.error("[foundry] Sitzungsgeheimnis nicht abrufbar", error);
    cachedSecret = "";
  }
  return cachedSecret;
}

/**
 * Öffnet eine URL außerhalb des Anwendungsfensters.
 *
 * Die Berechtigung in `src-tauri/capabilities/default.json` ist bewusst auf
 * `login.eveonline.com` und das Projekt-Repository beschränkt — die Schale
 * soll nicht zu einem Werkzeug werden, mit dem sich beliebige URLs öffnen
 * lassen.
 */
export async function openExternal(url: string): Promise<void> {
  if (!inShell()) {
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }
  const { openUrl } = await import("@tauri-apps/plugin-opener");
  await openUrl(url);
}

/** Nur für Tests. */
export function resetBridgeCache(): void {
  cachedSecret = null;
}
