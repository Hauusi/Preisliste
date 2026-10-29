# Arbeitsregeln für Claude in diesem Repo

## Ablauf nach jeder fertigen Änderung (vom Besitzer dauerhaft freigegeben)
1. Tests laufen lassen (`.venv/bin/pytest -q`), nur bei grünem Stand weiter.
2. Auf dem zugewiesenen Arbeitsbranch committen und pushen.
3. PR gegen den Hauptbranch `ccr-71bf8639-od7ces` anlegen und **ohne Rückfrage mergen**.
4. Am Ende den Server-Deploy-Befehl ausgeben:
   `cd ~/apps/preisliste && git pull && sudo bash deploy/install.sh`

## Dokumentation mitpflegen
Bei jeder Änderung an Bedienung, Abläufen oder Begriffen im selben PR anpassen:
- `docs/HANDBUCH.md` (Bedienung, Betrieb, Technik – maßgeblich)
- `README.md` (Kurzüberblick)
- diese Datei, wenn sich Arbeitsregeln ändern

## Kommunikation
Antworten auf Deutsch, kurz und ungeschönt, keine Emojis. Keine Fakten erfinden – bei Unklarheit nachfragen.

## Projekt
Überblick und Entwicklung: `README.md`. Bedienung und Technik: `docs/HANDBUCH.md`.
Tests: `.venv/bin/pytest -q`; Beispieldaten für den kompletten Ablauf: `beispiel-daten/`.
