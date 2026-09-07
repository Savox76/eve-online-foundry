import { afterEach, describe, expect, it, vi } from "vitest";
import { inShell, openExternal, resetBridgeCache, sessionSecret } from "@/lib/bridge";

afterEach(() => {
  resetBridgeCache();
  vi.unstubAllGlobals();
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
});

describe("Brücke zur Schale", () => {
  it("erkennt den Entwicklungsbetrieb ohne Schale", () => {
    expect(inShell()).toBe(false);
  });

  it("liefert ohne Schale kein Geheimnis — der Vite-Proxy hängt es an", async () => {
    await expect(sessionSecret()).resolves.toBe("");
  });

  it("öffnet den Login im Systembrowser statt im Anwendungsfenster", async () => {
    // Der Nutzer soll die echte Adresszeile von CCP sehen.
    const open = vi.fn();
    vi.stubGlobal("open", open);

    await openExternal("https://login.eveonline.com/v2/oauth/authorize?x=1");

    expect(open).toHaveBeenCalledWith(
      "https://login.eveonline.com/v2/oauth/authorize?x=1",
      "_blank",
      "noopener,noreferrer",
    );
  });
});
