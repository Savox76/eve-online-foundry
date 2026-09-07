"""Pydantic-Modelle der API-Aussenkante.

Getrennt von den SQLAlchemy-Modellen, damit ein Schemawechsel in der Datenbank
nicht ungewollt die API-Antwort aendert -- und damit die aus OpenAPI erzeugten
TypeScript-Typen im Frontend stabil bleiben.
"""
