"""Bestaende ueber alle Charaktere und Corp-Hangars, inklusive Delta-Ansicht.

Kommt in **Phase 2** des Phasenplans. Die Datei existiert schon, weil die
Struktur aus Kapitel 16 damit vollstaendig ist und der Router nur noch Routen
bekommen muss -- nicht, um Funktionen vorzutaeuschen, die es noch nicht gibt.
Solange hier nichts steht, taucht der Bereich auch nicht in der OpenAPI-Ausgabe
auf.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/assets", tags=["assets"])
