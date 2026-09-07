#!/usr/bin/env python3
"""Prueft Commit-Nachrichten auf Conventional Commits.

Aus den Typen entstehen die Release Notes automatisch (Kapitel 16). Der eigene
Typ ``esi:`` ist dabei kein Schmuck: er macht auf einen Blick sichtbar, welche
Releases von einer ESI-Aenderung ausgeloest wurden und nicht von eigener
Arbeit.

Laeuft als ``commit-msg``-Hook ueber ``.pre-commit-config.yaml``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

#: Die Typen aus Kapitel 16, mit ihrer Ueberschrift im Changelog.
TYPES = {
    "feat": "Neu",
    "fix": "Behoben",
    "perf": "Schneller",
    "esi": "ESI-Anpassung",
    "refactor": "Intern",
    "chore": "Intern",
    "docs": "Intern",
    "test": "Intern",
    "build": "Intern",
    "ci": "Intern",
    "revert": "Intern",
}

PATTERN = re.compile(
    r"^(?P<type>" + "|".join(TYPES) + r")(?P<scope>\([\w./-]+\))?(?P<breaking>!)?: (?P<subject>.+)$"
)

MAX_SUBJECT = 72


def check(message: str) -> list[str]:
    lines = message.splitlines()
    header = next((line for line in lines if line.strip() and not line.startswith("#")), "")

    if header.startswith("Merge ") or header.startswith("Revert "):
        return []

    problems: list[str] = []
    match = PATTERN.match(header)
    if not match:
        problems.append(
            f"Die erste Zeile passt nicht auf 'typ: beschreibung'.\n"
            f"  Gelesen: {header!r}\n"
            f"  Erlaubte Typen: {', '.join(sorted(TYPES))}\n"
            f"  Beispiel: feat(sync): Asset-Delta beim Sync mitschreiben"
        )
        return problems

    if len(header) > MAX_SUBJECT:
        problems.append(f"Die erste Zeile ist {len(header)} Zeichen lang, erlaubt sind {MAX_SUBJECT}.")

    subject = match.group("subject")
    if subject.endswith("."):
        problems.append("Die erste Zeile endet mit einem Punkt.")
    if subject[:1].isupper() and subject.split(" ", 1)[0].isalpha() and subject.isupper():
        problems.append("Die Beschreibung ist durchgehend gross geschrieben.")

    return problems


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Aufruf: check_commit_msg.py <datei>", file=sys.stderr)
        return 2

    problems = check(Path(argv[1]).read_text(encoding="utf-8"))
    if not problems:
        return 0

    print("Commit-Nachricht abgelehnt:", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
