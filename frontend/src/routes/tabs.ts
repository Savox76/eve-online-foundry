/**
 * Die acht Tabs aus Kapitel 15.
 *
 * Die Reihenfolge folgt dem Arbeitsablauf eines Industrialisten, nicht der
 * Datenstruktur: von der Lage ueber die Entscheidung zur Ausfuehrung, danach
 * die Bestandsansichten zum Nachschlagen. Assets steht deshalb bewusst hinter
 * dem Scanner -- die Bestandsliste ist ein Nachschlagewerk, kein Einstieg.
 *
 * Was hier absichtlich fehlt: Admin (hinter dem Nutzermenue), Fittings (im
 * Tab Projekte) und Nachrichten (Briefsymbol im Kopfbereich).
 */

export interface Tab {
  readonly id: string;
  readonly label: string;
  /** Die Frage, die dieser Tab beantwortet. */
  readonly frage: string;
  /** Ab welcher Phase es hier etwas zu sehen gibt. */
  readonly phase: number;
}

export const TABS: readonly Tab[] = [
  {
    id: "uebersicht",
    label: "Industrie Übersicht",
    frage: "Was braucht heute meine Aufmerksamkeit?",
    phase: 3,
  },
  {
    id: "projekte",
    label: "Projekte",
    frage: "Was haben wir uns vorgenommen und wie weit sind wir?",
    phase: 7,
  },
  {
    id: "invention",
    label: "T2 Invention",
    frage: "Welcher Decryptor lohnt sich wofür?",
    phase: 5,
  },
  {
    id: "produktion",
    label: "Produktion",
    frage: "Wie komme ich vom Ziel zur ausführbaren Liste?",
    phase: 4,
  },
  {
    id: "scanner",
    label: "Markt & Produktionsscanner",
    frage: "Was lohnt sich, und lässt es sich absetzen?",
    phase: 6,
  },
  {
    id: "assets",
    label: "Assets",
    frage: "Wo liegt das Zeug, und was hat sich bewegt?",
    phase: 2,
  },
  {
    id: "blueprints",
    label: "Blueprint Bibliothek",
    frage: "Wer hat den besten BPO — und was erforsche ich als Nächstes?",
    phase: 3,
  },
  {
    id: "pi",
    label: "Planetare Industrie",
    frage: "Welcher Extraktor läuft als Nächstes aus?",
    phase: 8,
  },
] as const;
