import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import type { StatusResponse } from "@/lib/types";

/**
 * Kein blockierendes Laden (Kapitel 15): TanStack Query liefert erst den
 * bekannten Stand und aktualisiert im Hintergrund. `staleTime` orientiert
 * sich am ESI-Cache -- oefter nachzufragen bringt keine neuen Daten.
 */
export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: ({ signal }) => apiGet<StatusResponse>("/api/v1/admin/status", signal),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}
