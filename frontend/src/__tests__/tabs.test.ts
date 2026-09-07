import { describe, expect, it } from "vitest";
import { TABS } from "@/routes/tabs";

describe("Navigation", () => {
  it("hat genau die acht Tabs aus Kapitel 15", () => {
    expect(TABS).toHaveLength(8);
  });

  it("vergibt jede Kennung nur einmal", () => {
    expect(new Set(TABS.map((tab) => tab.id)).size).toBe(TABS.length);
  });

  it("fuehrt Assets hinter dem Scanner", () => {
    // Die Bestandsliste ist ein Nachschlagewerk, kein Einstiegspunkt.
    const scanner = TABS.findIndex((tab) => tab.id === "scanner");
    const assets = TABS.findIndex((tab) => tab.id === "assets");
    expect(assets).toBeGreaterThan(scanner);
  });

  it("hat weder Fittings noch Admin noch Nachrichten als eigenen Tab", () => {
    const kennungen = TABS.map((tab) => tab.id);
    expect(kennungen).not.toContain("fittings");
    expect(kennungen).not.toContain("admin");
    expect(kennungen).not.toContain("mail");
  });

  it("beantwortet mit jedem Tab eine Frage", () => {
    for (const tab of TABS) {
      expect(tab.frage.endsWith("?")).toBe(true);
    }
  });
});
