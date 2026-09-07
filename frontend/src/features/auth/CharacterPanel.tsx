import { useState } from "react";
import { Ampel, type AmpelZustand } from "@/components/Ampel";
import {
  useCharacters,
  useLogin,
  useRefreshCharacter,
  useRemoveCharacter,
  useScopeTiers,
} from "@/hooks/useCharacters";
import { formatAlter } from "@/lib/format";
import type { CharacterInfo } from "@/lib/types";

/**
 * Charaktere verbinden und verwalten.
 *
 * Die Scope-Pakete werden gestaffelt angeboten, nicht auf einen Schlag: ein
 * erster Login, der alles anfragt, erzeugt ein unlesbares Consent-Fenster.
 * Wer weiß, wofür ein Scope gebraucht wird, erteilt ihn eher.
 */
export function CharacterPanel() {
  const { data, error, isPending } = useCharacters();
  const tiers = useScopeTiers();
  const { start, status } = useLogin();
  const [gewaehlt, setGewaehlt] = useState<string[]>(["base"]);

  const wartet = status.data?.state === "waiting" || start.isPending;

  function umschalten(tier: string) {
    if (tier === "base") return; // Ohne Basis geht nichts.
    setGewaehlt((bisher) =>
      bisher.includes(tier) ? bisher.filter((eintrag) => eintrag !== tier) : [...bisher, tier],
    );
  }

  return (
    <div className="space-y-6">
      <section>
        <h3 className="mb-2 font-mono text-[10px] uppercase tracking-widest text-faint">
          Charakter verbinden
        </h3>
        <p className="mb-3 max-w-[70ch] text-sm text-muted">
          Der Login öffnet den Systembrowser. Das ist Absicht — so siehst du die echte Adresszeile
          von CCP. Eine Anwendung, die das Login-Formular selbst anzeigt, wäre von Phishing nicht zu
          unterscheiden.
        </p>

        <div className="mb-4 flex flex-wrap gap-2">
          {(tiers.data ?? []).map((tier) => {
            const aktiv = gewaehlt.includes(tier.tier) || tier.tier === "base";
            return (
              <button
                key={tier.tier}
                type="button"
                onClick={() => umschalten(tier.tier)}
                disabled={tier.tier === "base"}
                title={tier.description}
                className={`border px-2.5 py-1 font-mono text-[11px] transition-colors ${
                  aktiv
                    ? "border-accent text-accent"
                    : "border-line text-muted hover:border-muted hover:text-ink"
                } ${tier.tier === "base" ? "cursor-default opacity-80" : ""}`}
              >
                {tier.label}
                {tier.tier === "base" && " · immer"}
              </button>
            );
          })}
        </div>

        <button
          type="button"
          onClick={() => start.mutate(gewaehlt)}
          disabled={wartet}
          className="border border-accent px-4 py-2 text-sm font-semibold text-accent transition-colors hover:bg-accent hover:text-ground disabled:cursor-wait disabled:opacity-50"
        >
          {wartet ? "Warte auf den Browser …" : "Mit EVE SSO anmelden"}
        </button>

        {status.data?.state === "failed" && (
          <p className="mt-3 border-l-2 border-crit bg-surface px-3 py-2 text-sm text-muted">
            {status.data.error}
          </p>
        )}
        {status.data?.state === "done" && (
          <p className="mt-3 border-l-2 border-ok bg-surface px-3 py-2 text-sm text-muted">
            <strong className="text-ink">{status.data.character_name}</strong> ist verbunden.
          </p>
        )}
        {start.error && (
          <p className="mt-3 border-l-2 border-crit bg-surface px-3 py-2 text-sm text-muted">
            {start.error.message}
          </p>
        )}
      </section>

      <section>
        <h3 className="mb-2 flex items-baseline gap-3 font-mono text-[10px] uppercase tracking-widest text-faint">
          Verbundene Charaktere
          {data && (
            <span className="normal-case tracking-normal">
              Tokens: {data.token_storage === "keyring" ? "Schlüsselbund" : "verschlüsselte Datei"}
            </span>
          )}
        </h3>

        {isPending && <p className="text-sm text-muted">Lade …</p>}
        {error && <p className="text-sm text-crit">{error.message}</p>}
        {data?.characters.length === 0 && (
          <p className="text-sm text-muted">Noch kein Charakter verbunden.</p>
        )}

        <div className="grid gap-px bg-line">
          {data?.characters.map((character) => (
            <CharacterRow key={character.character_id} character={character} />
          ))}
        </div>
      </section>
    </div>
  );
}

function CharacterRow({ character }: { character: CharacterInfo }) {
  const entfernen = useRemoveCharacter();
  const erneuern = useRefreshCharacter();

  const zustand: AmpelZustand = character.status === "ok" ? "ok" : "crit";
  const ohneRolle = Object.entries(character.scopes_without_role);

  return (
    <div className="bg-surface px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <Ampel zustand={zustand} titel={character.status} />
          <span className="font-semibold">{character.name}</span>
          <span className="font-mono text-[11px] text-faint">
            {character.scopes.length} Scopes · zuletzt {formatAlter(character.last_seen_at)}
          </span>
        </div>
        <div className="flex gap-3 font-mono text-[11px]">
          <button
            type="button"
            onClick={() => erneuern.mutate(character.character_id)}
            disabled={erneuern.isPending}
            className="text-cool hover:underline disabled:opacity-50"
          >
            Token erneuern
          </button>
          <button
            type="button"
            onClick={() => entfernen.mutate(character.character_id)}
            disabled={entfernen.isPending}
            className="text-crit hover:underline disabled:opacity-50"
          >
            Entfernen
          </button>
        </div>
      </div>

      {character.status_reason && (
        <p className="mt-2 text-sm text-crit">{character.status_reason}</p>
      )}

      {ohneRolle.length > 0 && (
        <div className="mt-2 border-l-2 border-warn bg-raised px-3 py-2 text-sm text-muted">
          <strong className="text-ink">Scope erteilt, Rolle fehlt.</strong> Diese Corp-Routen
          antworten mit 403, bis die In-Game-Rolle vergeben ist:
          <ul className="mt-1 space-y-0.5 font-mono text-[11px]">
            {ohneRolle.map(([scope, rolle]) => (
              <li key={scope}>
                {scope} → {rolle}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
