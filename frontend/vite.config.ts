import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * Im Entwicklungsbetrieb laeuft kein Tauri-Fenster, das ein Sitzungsgeheimnis
 * durchreichen koennte. Das Backend legt in dem Fall eins im Datenverzeichnis
 * ab; der Proxy liest es dort und haengt es an jeden Request.
 *
 * Der Proxy loest ausserdem genau das Problem, das der Plan nennt: `/api`
 * bleibt same-origin, und man schlaegt sich im Entwicklungsbetrieb nicht mit
 * CORS herum -- was der Anwendung im echten Betrieb ohnehin verwehrt ist.
 */
function sessionSecret(): string {
  const candidates = [
    process.env.FOUNDRY_DATA_DIR,
    join(homedir(), ".local", "share", "NewEdenFoundry"),
    join(homedir(), "Library", "Application Support", "NewEdenFoundry"),
    join(process.env.LOCALAPPDATA ?? "", "NewEdenFoundry"),
  ].filter(Boolean) as string[];

  for (const dir of candidates) {
    try {
      const value = readFileSync(join(dir, "session-secret"), "utf8").trim();
      if (value) return value;
    } catch {
      // naechster Kandidat
    }
  }
  console.warn(
    "[foundry] Kein Sitzungsgeheimnis gefunden. Erst das Backend starten " +
      "(uvicorn app.main:create_app --factory), dann `npm run dev` erneut.",
  );
  return "";
}

export default defineConfig(({ command }) => {
  const secret = command === "serve" ? sessionSecret() : "";
  const proxyTarget = "http://127.0.0.1:8000";
  const proxyHeaders: Record<string, string> = secret ? { "X-Foundry-Session": secret } : {};

  return {
    plugins: [react()],
    resolve: { alias: { "@": new URL("./src", import.meta.url).pathname } },
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target: proxyTarget,
          changeOrigin: false,
          headers: proxyHeaders,
        },
        "/health": { target: proxyTarget, changeOrigin: false },
      },
    },
    build: { outDir: "dist", sourcemap: true },
    test: {
      globals: true,
      environment: "jsdom",
      setupFiles: ["./src/test-setup.ts"],
    },
  };
});
