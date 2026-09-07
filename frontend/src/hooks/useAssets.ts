import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";
import type {
  AssetChangeListResponse,
  AssetListResponse,
  LocationSummary,
  SyncResultResponse,
} from "@/lib/types";

export interface AssetFilter {
  characterId?: number;
  search?: string;
  locationId?: number | null;
  limit?: number;
}

function query(filter: AssetFilter): string {
  const params = new URLSearchParams();
  if (filter.characterId) params.set("character_id", String(filter.characterId));
  if (filter.search) params.set("search", filter.search);
  if (filter.locationId != null) params.set("location_id", String(filter.locationId));
  params.set("limit", String(filter.limit ?? 500));
  return params.toString();
}

export function useAssets(filter: AssetFilter) {
  return useQuery({
    queryKey: ["assets", filter],
    queryFn: ({ signal }) => apiGet<AssetListResponse>(`/api/v1/assets?${query(filter)}`, signal),
    // Beim Tippen in der Suche die vorherigen Zeilen stehen lassen, statt die
    // Tabelle bei jedem Zeichen leer zu räumen.
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useLocations(characterId?: number) {
  return useQuery({
    queryKey: ["asset-locations", characterId],
    queryFn: ({ signal }) =>
      apiGet<LocationSummary[]>(
        `/api/v1/assets/locations${characterId ? `?character_id=${characterId}` : ""}`,
        signal,
      ),
    staleTime: 30_000,
  });
}

export function useAssetChanges(characterId?: number, sinceHours = 24) {
  const params = new URLSearchParams({ since_hours: String(sinceHours) });
  if (characterId) params.set("character_id", String(characterId));
  return useQuery({
    queryKey: ["asset-changes", characterId, sinceHours],
    queryFn: ({ signal }) =>
      apiGet<AssetChangeListResponse>(`/api/v1/assets/changes?${params}`, signal),
    staleTime: 30_000,
  });
}

export function useSyncAssets() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (characterId: number) =>
      apiPost<SyncResultResponse>(`/api/v1/assets/sync?character_id=${characterId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["assets"] });
      void queryClient.invalidateQueries({ queryKey: ["asset-locations"] });
      void queryClient.invalidateQueries({ queryKey: ["asset-changes"] });
    },
  });
}
