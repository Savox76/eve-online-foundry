import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Erst der bekannte Stand aus dem Cache, Aktualisierung im Hintergrund.
      // In einem Werkzeug mit einstuendigem ESI-Cache waere ein Ladebalken bei
      // jedem Tabwechsel schlicht falsch (Kapitel 15).
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30_000,
    },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("#root fehlt im HTML-Grundgeruest.");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
