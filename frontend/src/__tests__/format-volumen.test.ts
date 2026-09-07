import { describe, expect, it } from "vitest";
import { formatVolumen } from "@/lib/format";

describe("formatVolumen", () => {
  it("setzt Kubikmeter deutsch", () => {
    expect(formatVolumen(2500)).toBe("2.500 m³");
    expect(formatVolumen(0.01)).toBe("0 m³");
    expect(formatVolumen(27_500.55)).toBe("27.500,6 m³");
  });
});
