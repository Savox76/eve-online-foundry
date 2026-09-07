import { describe, expect, it } from "vitest";
import { formatAlter, formatIsk, formatMenge } from "@/lib/format";

describe("formatAlter", () => {
  const jetzt = new Date("2026-09-07T12:00:00Z");

  it("nennt fehlende Daten beim Namen statt sie zu verstecken", () => {
    // "nie" ist eine Aussage. Ein leeres Feld sieht aus wie ein Ladefehler.
    expect(formatAlter(null, jetzt)).toBe("nie");
    expect(formatAlter(undefined, jetzt)).toBe("nie");
  });

  it("erkennt unbrauchbare Zeitstempel", () => {
    expect(formatAlter("kein datum", jetzt)).toBe("unbekannt");
  });

  it("rechnet in Einheiten, die man im Alltag benutzt", () => {
    expect(formatAlter("2026-09-07T11:59:30Z", jetzt)).toBe("gerade eben");
    expect(formatAlter("2026-09-07T11:20:00Z", jetzt)).toBe("vor 40 min");
    expect(formatAlter("2026-09-07T09:00:00Z", jetzt)).toBe("vor 3 h");
    expect(formatAlter("2026-09-06T12:00:00Z", jetzt)).toBe("vor 1 Tag");
    expect(formatAlter("2026-09-02T12:00:00Z", jetzt)).toBe("vor 5 Tagen");
  });

  it("meldet keine negativen Zeiten bei leichtem Uhrversatz", () => {
    expect(formatAlter("2026-09-07T12:00:30Z", jetzt)).toBe("gerade eben");
  });
});

describe("Zahlenformate", () => {
  it("setzt Tausendertrennung deutsch", () => {
    expect(formatMenge(4820000)).toBe("4.820.000");
  });

  it("haengt die Waehrung an", () => {
    expect(formatIsk(1234.5)).toBe("1.234,5 ISK");
  });
});
