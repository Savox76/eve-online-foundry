import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { openExternal } from "@/lib/bridge";
import type {
  CharacterListResponse,
  LoginStartResponse,
  LoginStatusResponse,
  ScopeTierInfo,
} from "@/lib/types";

export function useCharacters() {
  return useQuery({
    queryKey: ["characters"],
    queryFn: ({ signal }) => apiGet<CharacterListResponse>("/api/v1/auth/characters", signal),
    staleTime: 10_000,
  });
}

export function useScopeTiers() {
  return useQuery({
    queryKey: ["scope-tiers"],
    queryFn: ({ signal }) => apiGet<ScopeTierInfo[]>("/api/v1/auth/scopes", signal),
    // Die Pakete stehen im Code und ändern sich nur mit einem Release.
    staleTime: Infinity,
  });
}

/**
 * Startet einen Anmeldeversuch und verfolgt ihn.
 *
 * Zwischen dem Öffnen des Browsers und der Rückkehr können Minuten liegen —
 * Anmeldung, Zwei-Faktor, Scope-Bestätigung. Deshalb wird der Fortschritt
 * abgefragt statt auf eine lange Antwort zu warten.
 */
export function useLogin() {
  const queryClient = useQueryClient();

  const start = useMutation({
    mutationFn: async (tiers: string[]) => {
      const attempt = await apiPost<LoginStartResponse>("/api/v1/auth/login", { tiers });
      await openExternal(attempt.url);
      return attempt;
    },
  });

  const status = useQuery({
    queryKey: ["login", start.data?.id],
    queryFn: ({ signal }) =>
      apiGet<LoginStatusResponse>(`/api/v1/auth/login/${start.data!.id}`, signal),
    enabled: Boolean(start.data?.id),
    refetchInterval: (query) =>
      query.state.data?.state === "waiting" ? 1500 : false,
  });

  const fertig = status.data?.state === "done";
  if (fertig) {
    void queryClient.invalidateQueries({ queryKey: ["characters"] });
  }

  return { start, status };
}

export function useRemoveCharacter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (characterId: number) => apiDelete(`/api/v1/auth/characters/${characterId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["characters"] });
      void queryClient.invalidateQueries({ queryKey: ["assets"] });
    },
  });
}

export function useRefreshCharacter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (characterId: number) =>
      apiPost(`/api/v1/auth/characters/${characterId}/refresh`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["characters"] }),
  });
}
