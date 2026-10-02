# Abhängigkeiten: Lizenzen, Notwendigkeit, Netzwerk

Stand: 2026-10-02, ermittelt aus den installierten Paketen (`requirements.txt`, inklusive indirekter Abhängigkeiten).
Alle Lizenzen sind freizügig (MIT, BSD, Apache-2.0, PSF). Es gibt keine Copyleft-Lizenzen (GPL/AGPL).

| Paket | Version | Lizenz | Wofür |
|---|---|---|---|
| fastapi | 0.142.2 | MIT | Web-Framework |
| starlette | 1.7.0 | BSD-3-Clause | Grundlage von FastAPI |
| uvicorn | 0.54.0 | BSD-3-Clause | Webserver |
| h11 | 0.16.0 | MIT | HTTP für uvicorn |
| anyio | 4.15.1 | MIT | asynchrone Grundlage (Starlette) |
| idna | 3.20 | BSD-3-Clause | indirekt (anyio) |
| click | 8.5.0 | BSD-3-Clause | indirekt (uvicorn) |
| python-multipart | 0.0.32 | Apache-2.0 | Datei-Upload |
| jinja2 | 3.1.6 | BSD | HTML-Vorlagen |
| markupsafe | 3.0.3 | BSD-3-Clause | Escaping für Jinja2 |
| sqlalchemy | 2.1.1 | MIT | Datenbankzugriff |
| alembic | 1.20.0 | MIT | Datenbank-Migrationen |
| mako | 1.4.3 | MIT | indirekt (alembic) |
| openpyxl | 3.1.5 | MIT | Excel lesen/schreiben |
| et_xmlfile | 2.0.0 | MIT | indirekt (openpyxl) |
| defusedxml | 0.7.1 | PSF | Schutz beim XML-Parsen der Excel-Dateien |
| argon2-cffi | 25.1.0 | MIT | Passwort-Hashing |
| argon2-cffi-bindings | 26.1.0 | MIT | indirekt |
| cffi | 2.1.1 | MIT-0 | indirekt |
| pycparser | 3.0 | BSD-3-Clause | indirekt |
| pydantic | 2.13.5 | MIT | Validierung (Regeln, KI-Antworten) |
| pydantic_core | 2.46.5 | MIT | indirekt |
| pydantic-settings | 2.15.0 | MIT | Konfiguration |
| python-dotenv | 1.2.4 | BSD-3-Clause | indirekt (pydantic-settings) |
| annotated-types, typing-inspection, typing_extensions, annotated-doc | – | MIT / PSF | indirekt |
| pyyaml | 6.0.3 | MIT | Synonymliste lesen |
| rapidfuzz | 3.14.6 | MIT | unscharfer Vergleich |
| opentelemetry-api | 1.45.0 | Apache-2.0 | **Pflichtabhängigkeit von FastAPI**, siehe unten |

## Telemetrie und Netzwerkzugriff zur Laufzeit

- Keines der Pakete baut von sich aus Verbindungen nach außen auf.
- **opentelemetry-api** wird von FastAPI zwingend mitinstalliert. Ohne das OpenTelemetry-SDK und ohne gesetzte `OTEL_EXPORTER_*`-Umgebungsvariable sendet es nichts. Zusätzlich ist FastAPIs Telemetrie im Code abgeschaltet (`telemetry=NO_TELEMETRY` in `backend/api/app.py`, mit Test), und im Docker-Image sind `OTEL_SDK_DISABLED=true` und alle `OTEL_*_EXPORTER=none` gesetzt.
- **Ollama** (`ollama/ollama`, MIT-Lizenz) läuft in einem Docker-Netz mit `internal: true`, hat also keinen Internetzugang. Nur der einmalige Modell-Download (`ollama-setup`) braucht Internet.
- **Modell `llama3.2:3b`:** Es gilt die Llama 3.2 Community License von Meta, keine Open-Source-Lizenz im engeren Sinn. Die Nutzung ist erlaubt, es gibt aber Bedingungen (u. a. Acceptable Use Policy). Vor dem produktiven Einsatz bitte selbst lesen. Austauschbar über `PREIS_AI_MODEL`. Die Lizenzen anderer Modelle unterscheiden sich, teils je nach Größe; vor einem Wechsel prüfen. Größere Modelle brauchen mehr RAM als die 4 GB Limit für Ollama.

Nur für die Entwicklung (nicht im Image): pytest (MIT), httpx (BSD-3-Clause).
