import type { Config } from "tailwindcss";

/**
 * Dunkles Grundthema. Das ist keine Geschmacksfrage: EVE wird nachts
 * gespielt, und ein helles Interface daneben blendet (Kapitel 15).
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ground: "#0b1015",
        surface: "#131b22",
        raised: "#1a242d",
        line: "#25333d",
        ink: "#dce5ec",
        muted: "#8ea0ae",
        faint: "#697b89",
        accent: "#ef8f42",
        cool: "#63a9c9",
        ok: "#5cb98d",
        warn: "#d8a33c",
        crit: "#e0736c",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
