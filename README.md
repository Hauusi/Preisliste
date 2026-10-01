# Preisliste

Server-Anwendung zur Verarbeitung von Excel-Preislisten (.xlsx): Import, Prüfung, Kalkulation, Vorjahresvergleich, Export. Läuft auf dem eigenen Server unter `https://salesassistent.duckdns.org`, mit Anmeldung. Die KI (Ollama) ist optional und läuft auf demselben Server.

- Anforderungen: `docs/anforderungen-v2.md`
- Architektur und Plan (Phase 1, freigegeben): `docs/phase1-architektur.md`

## Stand

| Gruppe | Inhalt | Status |
|---|---|---|
| A | Grundprojekt, Login, Excel-Import, Spaltenerkennung | umgesetzt |
| B | Regelengine, Vergleich, Matching | umgesetzt |
| C | Ollama, Hintergrundjobs, UI | offen |
| D | Export, Deployment, Backup | offen |

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
git clone https://github.com/Hauusi/Preisliste.git preisliste
cd preisliste
git checkout ccr-71bf8639-od7ces
cd deploy
mkdir -p data && chown 10001:10001 data
docker compose up -d --build
docker compose exec app python -m backend.cli create-admin <name>
```

Zum Testen vom eigenen Rechner aus einen SSH-Tunnel öffnen und `http://localhost:8010` im Browser aufrufen:

```
ssh -i ~/.ssh/id_ed25519_handy -L 8010:127.0.0.1:8010 root@62.238.39.31
```

## Konfiguration

Umgebungsvariablen mit Präfix `PREIS_`, siehe `backend/config.py`. Wichtig: `PREIS_COOKIE_SECURE=true` im Betrieb (Standard).
Spaltenüberschriften für die Erkennung: `config/header_synonyms.yaml`.
