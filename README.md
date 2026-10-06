# Sales Assistant (Modul Preisliste)

Server-Anwendung zur Verarbeitung von Excel-Preislisten (.xlsx): Import, Prüfung, Kalkulation, Vorjahresvergleich, Export. Läuft auf dem eigenen Server unter `https://salesassistent.duckdns.org`, mit Anmeldung. Die KI (Ollama) ist optional und läuft auf demselben Server.

- Anforderungen: `docs/anforderungen-v2.md`
- Architektur und Plan (Phase 1, freigegeben): `docs/phase1-architektur.md`
- Betrieb, Backup, Wiederherstellung: `docs/betrieb.md`
- Lizenzen und Telemetrie der Abhängigkeiten: `docs/abhaengigkeiten.md`

## Stand

| Gruppe | Inhalt | Status |
|---|---|---|
| A | Grundprojekt, Login, Excel-Import, Spaltenerkennung | umgesetzt |
| B | Regelengine, Vergleich, Matching | umgesetzt |
| C | Ollama, Hintergrundjobs, UI | umgesetzt |
| D | Export, Deployment, Backup | umgesetzt |

## So arbeitet man damit (Sales Assistant → Preisliste)

Nach dem Login: Kachel-Startseite des **Sales Assistant**, Modul **Preisliste** öffnen.

1. **Hersteller einmal anlegen**: Name, Kürzel (z. B. RA), Faktor (VK = EK × 2,6). Die Kalkulationsregel entsteht
   automatisch. Optional: Hersteller schickt UVP (Händlerrabatt), Fremdwährung (Kurs), Prüfschwelle.
2. **Liste einspielen** (eine Datei für alles): Das Tool erkennt Hersteller, Spalten, Art der Liste (unsere
   EK/VK-Liste oder neue Herstellerliste), Währung, Kürzel in den Nummern und bei Herstellerlisten, wie viele
   unserer Artikel enthalten sind (Teilliste wird vorgeschlagen). Eine Prüfseite, ein Klick auf „Starten“.
   - Unsere Liste → wird die aktuelle EK/VK-Liste des Herstellers.
   - Herstellerliste → der Jahresabgleich startet automatisch, danach direkt das Ergebnis.
3. **Prüfen**: Es werden zuerst nur die Auffälligkeiten gezeigt (EK-Änderung ab Schwelle, VK unter EK, fehlende
   oder unklare Artikel, Fehler). Jeder VK ist unabhängig nachgerechnet. Einzelne Artikel lassen sich mit eigenem
   Faktor kalkulieren (gilt dauerhaft), geänderte Nummern per Auswahl oder KI-Vorschlag zuordnen.
4. **Abschließen** (optional mit „gültig ab“): ein Klick übernimmt die neuen EK/VK als aktuelle Liste und lädt die
   fertige Excel-Liste herunter. Zusätzlich: **Preisänderungsliste für Kunden** (nur geänderte VK, alt → neu, gültig ab).

Vertriebsdetails: VK-Rundung pro Hersteller (10 Cent, volle Euro, ,90/,95/,99 – Endungen runden immer auf),
Marge (Rohertrag in % vom VK) in Prüfung und Export, doppelte Zeilen mit gleichem Preis zählen einmal,
„entfällt“-Vermerke des Herstellers werden erkannt (alter Preis bleibt, Hinweis in der Prüfung),
Deckblätter werden übersprungen, eine allgemeine „Preis“-Spalte wird laut Hersteller-Einstellung als EK bzw. UVP gelesen.

Testdaten für den kompletten Ablauf: `beispiel-daten/` (erzeugt mit `python beispiel-daten/erzeuge_testdaten.py`),
automatisch durchgespielt in `tests/test_e2e_szenarien.py`.

## Benutzer und Sichtbarkeit

Jeder Benutzer sieht nur seine eigenen Hersteller, Regeln, Preislisten, Abgleiche und Vergleiche und pflegt sie
selbst. Name und Kürzel eines Herstellers sind pro Benutzer eindeutig (zwei Benutzer dürfen je einen „Strand“
haben). Administratoren sehen und bearbeiten alles, mit Benutzerspalte in den Übersichten. Fremde Inhalte
werden wie nicht vorhanden behandelt (404). Benutzer anlegen: Seite „Benutzer“ (nur Administratoren).

## Neue Artikel unterm Jahr

Menü „Neue Artikel“: Artikelnummern mit Kürzel einfügen (z. B. aus Excel: ST12345, optional Bezeichnung und EK).
Der Hersteller wird am Kürzel erkannt, der EK kommt aus der neuesten Herstellerliste (sonst aus der Zeile), der VK
aus der Standardregel bzw. der eigenen Kalkulation, mit Gegenrechnung. Alles erscheint zuerst in einer
Bestätigungsliste; erst nach Bestätigung kommen die Artikel in die aktuelle EK/VK-Liste des Herstellers.
Mehrdeutige Kürzel, doppelte oder schon vorhandene Artikel werden nicht aufgenommen.

## Entwicklung

```
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest                 # alle Tests ausser Belastungstest
.venv/bin/pytest -m slow -s      # Belastungstest 50.000 Zeilen
PREIS_COOKIE_SECURE=false .venv/bin/python -m backend.cli create-admin admin
PREIS_COOKIE_SECURE=false .venv/bin/uvicorn backend.main:app --port 8010
```

## Server (Testbetrieb parallel zur alten App)

Die App läuft auf `127.0.0.1:8010` und ist nur lokal auf dem Server erreichbar. nginx wird erst bei der Umstellung angepasst (Gruppe D).

```
cd ~/apps
git clone -b ccr-71bf8639-od7ces https://github.com/Hauusi/Preisliste.git preisliste
sudo bash preisliste/deploy/install.sh          # Swap, Modell, Bauen, Start, Admin anlegen
sudo bash preisliste/deploy/switch-nginx.sh     # Domain auf neue App umstellen, alte App stoppen
```

Update: `cd ~/apps/preisliste && git pull && sudo bash deploy/install.sh`

Ohne Modell oder ohne Ollama läuft die App trotzdem vollständig, die KI-Knöpfe werden dann ausgeblendet.

Zum Testen vom eigenen Rechner aus einen SSH-Tunnel öffnen und `http://localhost:8010` im Browser aufrufen (Chrome oder Firefox):

```
ssh -i ~/.ssh/id_ed25519_handy -L 8010:127.0.0.1:8010 root@62.238.39.31
```

Empfohlen vor dem Start von Ollama (der Server hat keinen Swap):

```
fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

## Konfiguration

Umgebungsvariablen mit Präfix `PREIS_`, siehe `backend/config.py`. Wichtig: `PREIS_COOKIE_SECURE=true` im Betrieb (Standard).
Spaltenüberschriften für die Erkennung: `config/header_synonyms.yaml`.
KI: `PREIS_AI_PROVIDER` (`ollama`, `local`, `none`), `PREIS_OLLAMA_URL`, `PREIS_AI_MODEL` (Standard `llama3.2:3b`), `PREIS_AI_TIMEOUT_SECONDS`, `PREIS_AI_RETRIES`. Nur lokale Endpunkte werden akzeptiert.
