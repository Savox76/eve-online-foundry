"""Zeitplaene, im selben Prozess.

Redis und getrennte Worker brauchte es nur, solange mehrere Prozesse auf einem
Server standen. Eine Desktop-Anwendung hat genau einen Prozessbaum; APScheduler
laeuft darin mit (Kapitel 3).

Der wichtigere Unterschied ist konzeptionell: ein Server laeuft durch und darf
"nachts um vier" sagen. Eine Desktop-Anwendung laeuft nur, wenn jemand sie
startet. Deshalb ist der Einstiegspunkt hier nicht die Uhrzeit, sondern die
Frage **"wie alt sind die Daten?"** -- beim Start und danach in Intervallen.
"""
