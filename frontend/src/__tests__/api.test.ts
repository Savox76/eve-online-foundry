import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, SESSION_HEADER, apiGet } from "@/lib/api";

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  delete window.__FOUNDRY__;
});

describe("apiGet", () => {
  it("schickt das Sitzungsgeheimnis mit, wenn die Schale eins gesetzt hat", async () => {
    window.__FOUNDRY__ = { sessionSecret: "geheim" };
    const fetchMock = vi.fn().mockResolvedValue(antwort(200, { status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    await apiGet("/health");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)[SESSION_HEADER]).toBe("geheim");
  });

  it("kommt ohne Geheimnis aus — im Entwicklungsbetrieb setzt es der Vite-Proxy", async () => {
    const fetchMock = vi.fn().mockResolvedValue(antwort(200, {}));
    vi.stubGlobal("fetch", fetchMock);

    await apiGet("/health");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.headers).toEqual({});
  });

  it("uebersetzt 401 in einen Satz, der weiterhilft", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(antwort(401, { detail: "nope" })));
    await expect(apiGet("/api/v1/admin/status")).rejects.toThrow(/neu starten/);
  });

  it("reicht die Begruendung des Servers bei 403 durch", async () => {
    // Bei einem 403 steckt die eigentliche Information in der Antwort:
    // fehlende In-Game-Rolle oder kein Docking-Zugriff.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(antwort(403, { detail: "Fehlt die Director-Rolle?" })),
    );
    await expect(apiGet("/api/v1/assets")).rejects.toThrow("Fehlt die Director-Rolle?");
  });

  it("traegt den Statuscode am Fehler", async () => {
    // Frische Antwort je Aufruf: der Body einer Response laesst sich nur
    // einmal lesen.
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(antwort(429, {}))));
    await expect(apiGet("/api/v1/market")).rejects.toMatchObject({
      name: "ApiError",
      status: 429,
    });
    await expect(apiGet("/api/v1/market")).rejects.toBeInstanceOf(ApiError);
  });
});
