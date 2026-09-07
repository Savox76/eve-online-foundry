import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, SESSION_HEADER, apiGet, apiPost } from "@/lib/api";

// Das Sitzungsgeheimnis kommt in der echten Anwendung aus der Tauri-Schale.
// Hier wird die Brücke ersetzt, damit der Test ohne Schale läuft.
const sessionSecret = vi.fn<() => Promise<string>>();
vi.mock("@/lib/bridge", () => ({
  sessionSecret: () => sessionSecret(),
  inShell: () => false,
  openExternal: vi.fn(),
}));

function antwort(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  sessionSecret.mockReset();
});

describe("apiGet", () => {
  it("schickt das Sitzungsgeheimnis mit, wenn die Schale eins liefert", async () => {
    sessionSecret.mockResolvedValue("geheim");
    const fetchMock = vi.fn(() => Promise.resolve(antwort(200, { status: "ok" })));
    vi.stubGlobal("fetch", fetchMock);

    await apiGet("/health");

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>)[SESSION_HEADER]).toBe("geheim");
  });

  it("kommt ohne Geheimnis aus — im Entwicklungsbetrieb setzt es der Vite-Proxy", async () => {
    sessionSecret.mockResolvedValue("");
    const fetchMock = vi.fn(() => Promise.resolve(antwort(200, {})));
    vi.stubGlobal("fetch", fetchMock);

    await apiGet("/health");

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.headers).toEqual({});
  });

  it("übersetzt 401 in einen Satz, der weiterhilft", async () => {
    sessionSecret.mockResolvedValue("geheim");
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(antwort(401, { detail: "nope" }))));
    await expect(apiGet("/api/v1/admin/status")).rejects.toThrow(/neu starten/);
  });

  it("reicht die Begründung des Servers bei 403 durch", async () => {
    // Bei einem 403 steckt die eigentliche Information in der Antwort:
    // fehlende In-Game-Rolle oder kein Docking-Zugriff.
    sessionSecret.mockResolvedValue("geheim");
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(antwort(403, { detail: "Fehlt die Director-Rolle?" }))),
    );
    await expect(apiGet("/api/v1/assets")).rejects.toThrow("Fehlt die Director-Rolle?");
  });

  it("trägt den Statuscode am Fehler", async () => {
    sessionSecret.mockResolvedValue("geheim");
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(antwort(429, {}))));
    await expect(apiGet("/api/v1/market")).rejects.toMatchObject({ name: "ApiError", status: 429 });
    await expect(apiGet("/api/v1/market")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("apiPost", () => {
  it("setzt den Content-Type nur, wenn es einen Body gibt", async () => {
    sessionSecret.mockResolvedValue("geheim");
    const fetchMock = vi.fn(() => Promise.resolve(antwort(200, {})));
    vi.stubGlobal("fetch", fetchMock);

    await apiPost("/api/v1/auth/login", { tiers: ["base"] });
    await apiPost("/api/v1/assets/sync?character_id=1");

    const [, mitBody] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const [, ohneBody] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect((mitBody.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(mitBody.body).toBe('{"tiers":["base"]}');
    expect(ohneBody.body).toBeUndefined();
    expect((ohneBody.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("kommt mit einer leeren 204-Antwort zurecht", async () => {
    // Charakter entfernen antwortet ohne Inhalt — ein blindes response.json()
    // würde hier werfen.
    sessionSecret.mockResolvedValue("geheim");
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(antwort(204, null))));
    await expect(apiPost("/api/v1/auth/characters/1/refresh")).resolves.toBeUndefined();
  });
});
