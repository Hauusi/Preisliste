# Phase 1: Anforderungsprüfung, Architektur, Plan

Stand: 2026-10-01. Grundlage: `docs/anforderungen-v2.md` plus die Änderungen aus Abschnitt 1.
Status: **wartet auf Freigabe**. Noch kein Anwendungscode.

---

## 1. Geänderte Rahmenbedingungen (Entscheidung des Auftraggebers)

| Thema | Original (v2) | Neu |
|---|---|---|
| Betrieb | Lokal auf Windows-PCs, offline | **Nur Server**: Hetzner-Server, Zugriff per Browser über `https://salesassistent.duckdns.org` |
| Installation | Windows-Installer, Offline-Paket | Linux-Server, Docker Compose, Installationsskript |
| Zugriff | Nur lokal | **Mit Anmeldung** (Benutzername + Passwort) |
| KI | Ollama lokal | **Ollama auf dem Server** |

### Folgen, die bewusst akzeptiert werden

- **Geschäftsdaten verlassen den Arbeitsplatz-PC** und liegen auf dem Hetzner-Server. §1 ("Daten verlassen das lokale System nicht") gilt ab jetzt sinngemäß für den **Server**: Die Daten verlassen den Server nicht. Es gibt keine Cloud-KI, keine externen APIs und keine Telemetrie.
- **§13 (Windows-Installer, Offline-Paket)** entfällt und wird durch Gruppe D "Server-Deployment" ersetzt.
- **§8 Statusanzeige "OFFLINE"** passt nicht mehr. Ersatz: Statusanzeige "KI aktiv / inaktiv" und "keine externen Verbindungen" (Ollama läuft ohne Internetzugang, siehe 3.3).
- **§2.8 (nur 127.0.0.1)** wird so umgesetzt: Aus dem Internet erreichbar ist nur der Reverse-Proxy (Caddy) auf Port 80/443. App und Ollama veröffentlichen keine Ports nach außen. Erklärung in 3.2.

---

## 2. Gefundene Lücken und Widersprüche in den Anforderungen

| # | Stelle | Problem | Vorschlag / Status |
|---|---|---|---|
| W1 | §1, §2.8, §13 vs. Serverbetrieb | Siehe Abschnitt 1 | Entschieden |
| W2 | §4 | `calculated_price`, `previous_price`, `price_difference` an der Artikelzeile vertragen sich nicht mit mehreren Preisen pro Artikel und mehreren Vergleichen | Ergebnisse in eigene Tabellen (`calculation_results`, `comparison_items`), Artikelzeile bleibt Rohdatum |
| W3 | §3.2 | "Führende Nullen nach definierter Regel": die Regel ist nicht definiert | **Offene Frage F2** |
| W4 | §2.5, §3.2 | Schwellwert nicht festgelegt; unklar, ob er auch für Fuzzy-Treffer gilt | **Offene Frage F3** |
| W5 | §6 | `ARTIKEL_GEÄNDERT` ist nicht definiert | **Offene Frage F4** |
| W6 | §4, §6 | Bei Staffelpreisen ist unklar, welche Staffel verglichen wird | **Offene Frage F5** |
| W7 | §6 | Unklar, welcher Preis verglichen wird: Listenpreis, EK oder kalkulierter Preis | **Offene Frage F6** |
| W8 | §5 | Schritttyp "Rundung" vs. automatische Rundung pro Schritt: Bedeutung unklar (z. B. auf ,90-Endung oder auf 0,05) | **Offene Frage F7** |
| W9 | §6 | Prozentänderung bei altem Preis 0 ist nicht definiert | Status FEHLER, keine Division |
| W10 | §6, §10 | Alte und neue Liste in unterschiedlichen Währungen | Status FEHLER "Währung abweichend" (Umrechnung ist nicht im MVP) |
| W11 | §3.1 | `.xlsm`: "klare Fehlermeldung bzw. definierte Behandlung" lässt offen, welche Variante gilt | `.xls` und `.xlsm` werden abgelehnt, mit klarer Meldung. Begründung: keine Makro-Container auf dem Server |
| W12 | §4 Audit-Log "wer" | Ohne Benutzerverwaltung nicht möglich | Wird durch die Anmeldung gelöst |
| W13 | §14 | Ressourcen beziehen sich auf den PC | Bezug ist jetzt die Servergröße, die noch unbekannt ist (**F1**) |

Die Referenzrechnung aus §5 ist in sich stimmig: 100,00 − 15 % = 85,00; 4 % von 85,00 = 3,40; 85,00 + 3,40 = 88,40.

---

## 3. Architektur

### 3.1 Überblick

```
Internet ──443/80──> Caddy (TLS, Let's Encrypt)
                       │  internes Docker-Netz "web"
                       v
                     App (FastAPI + Uvicorn, 1 Prozess)
                       │  ├─ SQLite (Volume /data)
                       │  ├─ Upload-/Export-Ordner (Volume)
                       │  └─ Hintergrund-Worker (Thread, Job-Tabelle)
                       │  internes Docker-Netz "ai" (ohne Internet)
                       v
                     Ollama (Modell z. B. llama3.2:3b)
```

### 3.2 Netzwerk und §2.8

- **Docker Compose** mit drei Diensten: `caddy`, `app`, `ollama`.
- Nur `caddy` veröffentlicht Ports (80, 443).
- `app` lauscht im Container auf `0.0.0.0:8000`. Das ist in Docker nötig, damit Caddy die App erreicht. Nach außen ist der Port trotzdem nicht erreichbar, weil er nicht veröffentlicht wird. Das ist die einzige wörtliche Abweichung von §2.8. Der Zweck der Regel (nicht aus dem Netz erreichbar) bleibt erfüllt.
  Alternative ohne Docker: App per systemd direkt auf `127.0.0.1:8000`, Caddy auf dem Host. Das erfüllt §2.8 wörtlich, Updates und Wiederherstellung sind dann aber aufwendiger. **Empfehlung: Docker.**
- `ollama` hängt nur am Netz `ai`, das mit `internal: true` angelegt wird, also ohne Internetzugang. Das Modell wird einmalig bei der Installation geladen, mit einem separaten Befehl, der zeitweise Internet hat.
- Firewall (Hetzner Cloud Firewall oder `ufw`): eingehend nur 22, 80, 443.

### 3.3 Domain und TLS

- `salesassistent.duckdns.org` muss per A-Record auf die öffentliche IPv4 des Servers zeigen. Das stellt man im DuckDNS-Konto ein. Hetzner-IPs sind fest, ein Update-Dienst ist daher nicht nötig.
- Caddy holt das Zertifikat automatisch über Let's Encrypt (HTTP-01). Dafür muss Port 80 offen sein.
- Header: HSTS, `X-Frame-Options: DENY`, eine strikte Content-Security-Policy, keine externen Skripte oder CDNs (alles wird mitgeliefert).

### 3.4 Anmeldung und Sicherheit

- Benutzer liegen in der Datenbank. Passwörter werden mit **Argon2id** gehasht (`argon2-cffi`).
- Keine Selbstregistrierung. Der erste Admin wird per CLI-Befehl auf dem Server angelegt, weitere Benutzer legt der Admin in der UI an.
- Rollen: **admin** (Regeln, Hersteller, Benutzer, Einstellungen) und **benutzer** (Import, Vergleich, Export, Zuordnungen bestätigen). Ob das so passt: **F8**.
- Serverseitige Sessions mit Cookie `HttpOnly`, `Secure`, `SameSite=Strict`, Leerlauf-Timeout (Vorschlag 8 h). Zusätzlich ein CSRF-Token für alle schreibenden Anfragen.
- Brute-Force-Schutz: Begrenzung pro IP und pro Konto. Nach 5 Fehlversuchen wird das Konto 15 Minuten gesperrt. Alle Anmeldungen werden ins Audit-Log geschrieben.
- Uploads: maximal 25 MB (konfigurierbar). Vor dem Öffnen wird die unkomprimierte Größe des ZIP-Containers geprüft (Schutz gegen Zip-Bomben). XML wird mit `defusedxml` gelesen. Dateien bekommen zufällige Namen und liegen außerhalb jedes Web-Pfads.
- Optional später: 2FA (TOTP). Nicht im MVP.

### 3.5 Technologien

| Bereich | Wahl | Grund |
|---|---|---|
| Sprache | Python 3.12 | Vorgabe pandas/openpyxl |
| Web | FastAPI, Uvicorn | Vorgabe |
| UI | Serverseitige Jinja2-Templates + HTMX (lokal ausgeliefert) | Kein Build-Schritt, Paginierung und Filter laufen ohnehin serverseitig (§8) |
| DB | SQLite im WAL-Modus, SQLAlchemy 2.x, Alembic | Einfach, eine Datei, reicht für wenige gleichzeitige Benutzer |
| Excel | openpyxl (lesen mit `read_only`, `data_only`), pandas | Vorgabe |
| Fuzzy | rapidfuzz | Vorgabe |
| Formeln | simpleeval mit Whitelist | Vorgabe |
| Validierung | pydantic v2 | Vorgabe |
| KI | Ollama HTTP-API mit `format` = JSON-Schema | Vorgabe |
| Tests | pytest | Vorgabe |
| Betrieb | Docker Compose, Caddy | Siehe 3.2 |

Eine Lizenz- und Telemetrieprüfung aller Abhängigkeiten folgt in Gruppe D als `docs/abhaengigkeiten.md`.

### 3.6 Hintergrundjobs

- Tabelle `jobs` (Typ, Status, Fortschritt, Abbruch-Flag, Fehler).
- Ein Worker-Thread im App-Prozess arbeitet die Jobs nacheinander ab. Er prüft das Abbruch-Flag zwischen den Einzelanfragen. Jede KI-Anfrage hat ein Zeitlimit (Vorschlag 60 s).
- Uvicorn läuft mit nur einem Worker-Prozess. Mehrere Prozesse würden den Job-Thread vervielfachen und SQLite-Schreibkonflikte erzeugen. Für wenige Benutzer reicht das.

---

## 4. Datenmodell (SQLite)

Geldbeträge werden als **TEXT** gespeichert (Decimal als String, z. B. `"1234.56"`). SQLite kennt keinen echten Dezimaltyp, und REAL wäre float. Umgesetzt wird das mit einem eigenen SQLAlchemy-Typ `DecimalText`.

| Tabelle | Wichtige Spalten |
|---|---|
| `users` | id, username, password_hash, role, active, failed_logins, locked_until, created_at |
| `sessions` | id (zufällig), user_id, created_at, last_seen, csrf_token |
| `manufacturers` | id, name, aliases (JSON), default_rule_id |
| `price_lists` (Importhistorie) | id, source_file, file_sha256, sheet, header_row, column_mapping (JSON, bestätigt), manufacturer_id, currency, valid_from, imported_by, imported_at, status |
| `articles` | id, price_list_id, source_row, article_number, article_number_normalized, manufacturer_id, description, category, quantity_unit, status, messages (JSON) |
| `article_prices` | id, article_id, price_type (EK/LISTE/UVP), amount, currency, min_quantity, valid_from, discount, transport_cost |
| `import_messages` | id, price_list_id, source_row, level (FEHLER/WARNUNG/UNKLAR), code, text |
| `rules` | id, name, manufacturer_id, current_version, deleted |
| `rule_versions` | id, rule_id, version, steps (JSON), rounding_mode, rounding_places, rounding_timing (STEP/END), created_by, created_at. **Unveränderlich**: keine UPDATE-Operation, wird auch per DB-Trigger blockiert |
| `calculation_results` | id, article_price_id, rule_version_id, base_amount, result_amount, trace (JSON: Schritt, Basis, Operand, Zwischenergebnis), status |
| `comparisons` | id, old_price_list_id, new_price_list_id, manufacturer_id, price_type, created_by, created_at, summary (JSON) |
| `comparison_items` | id, comparison_id, old_article_id, new_article_id, status, old_amount, new_amount, difference, difference_percent, match_method, confidence |
| `confirmed_matches` | id, manufacturer_id, old_number_normalized, new_number_normalized, confirmed_by, confirmed_at |
| `jobs` | id, type, status, progress, total, cancel_requested, error, created_by |
| `settings` | key, value (JSON) |
| `audit_log` | id, user_id, action, entity, entity_id, before (JSON), after (JSON), ip, timestamp |

Doppelte Artikelnummern innerhalb einer Liste werden alle gespeichert und als WARNUNG markiert, nichts wird überschrieben. Im Vergleich führen sie zu NICHT_EINDEUTIG.

Indizes: `articles(price_list_id, manufacturer_id, article_number_normalized)`, `comparison_items(comparison_id, status)`.

---

## 5. API (Auszug)

Alle Endpunkte außer `/login` und `/health` verlangen eine gültige Session. Schreibende Endpunkte verlangen zusätzlich das CSRF-Token.

| Methode | Pfad | Zweck |
|---|---|---|
| POST | `/login`, `/logout` | Anmeldung |
| GET | `/health` | Lebenszeichen (ohne Details) |
| GET | `/api/status` | KI erreichbar, Modell vorhanden, Speicherverbrauch |
| POST | `/api/imports` | Datei hochladen, gibt Blätter und erkannte Spalten zurück (noch nicht übernommen) |
| GET | `/api/imports/{id}/preview?sheet=&page=` | Vorschau |
| POST | `/api/imports/{id}/confirm` | Spaltenzuordnung und Hersteller bestätigen, Import ausführen |
| GET | `/api/price-lists`, `/api/price-lists/{id}/articles?page=&filter…` | Listen und Artikel (serverseitig paginiert) |
| GET/POST/PUT/DELETE | `/api/manufacturers` | Hersteller (admin) |
| GET/POST | `/api/rules`, `/api/rules/{id}/versions` | Regeln; PUT erzeugt eine neue Version (admin) |
| POST | `/api/rules/{id}/test` | Regel an Beispielbetrag testen, mit Rechenweg |
| POST | `/api/comparisons` | Vergleich starten (als Job) |
| GET | `/api/comparisons/{id}/items?status=&manufacturer=&category=&min=&max=&page=` | Ergebnisse gefiltert und paginiert |
| POST | `/api/comparisons/{id}/items/{item}/confirm` | Zuordnung bestätigen oder ablehnen |
| POST | `/api/comparisons/{id}/ai-match` | KI-Job für den Rest starten |
| GET/POST | `/api/jobs/{id}`, `/api/jobs/{id}/cancel` | Fortschritt, Abbruch |
| GET | `/api/comparisons/{id}/export` | Excel-Export |
| GET/POST | `/api/users` | Benutzerverwaltung (admin) |
| GET | `/api/audit` | Audit-Log (admin) |

---

## 6. Risiken

| Risiko | Auswirkung | Gegenmaßnahme |
|---|---|---|
| Servergröße unbekannt | Ollama läuft nicht oder sehr langsam | Zuerst Specs prüfen (F1). Die App läuft ohne KI vollständig (§2.1) |
| Öffentlich erreichbar | Angriffe, Passwort-Raten | Login, Rate-Limit, Sperre, TLS, Firewall, Updates |
| Daten auf dem Server | Verlust oder Diebstahl | Tägliches Backup der SQLite-DB (Ziel: **F9**), Volumes nur für root lesbar, SSH nur mit Schlüssel |
| DuckDNS fällt aus | Domain nicht erreichbar | Kostenloser Dienst ohne Garantie; später eigene Domain möglich, ohne Änderung an der App |
| Let's Encrypt scheitert | Kein HTTPS | Port 80 muss offen sein, DNS muss vorher stimmen; Prüfschritt im Installationsskript |
| KI-Confidence unkalibriert | Falsche Zuordnungen | Nie automatisch übernehmen (§2.5), nur zur Sortierung |
| Excel-Vielfalt | Falsch erkannte Spalten | Bestätigung in der Vorschau ist Pflicht; Tests mit echten anonymisierten Listen in `tests/data/` |
| SQLite bei mehreren Benutzern | Schreibsperren | WAL-Modus, ein Worker; bei Bedarf später PostgreSQL |
| CPU-Laufzeit der KI | Lange Wartezeiten | Kaskade vorgeschaltet, Jobs im Hintergrund und abbrechbar; Laufzeiten messen statt schätzen (§14) |

---

## 7. Projektstruktur

```
Preisliste/
  backend/
    api/            # FastAPI-Router
    auth/           # Login, Sessions, CSRF, Rate-Limit  (neu wegen Serverbetrieb)
    models/         # SQLAlchemy + pydantic
    database/       # Engine, Migrationen (Alembic)
    excel/          # Parser, Spaltenerkennung, Export
    calculations/   # Decimal, Regelengine, Formelparser
    matching/       # Kaskade
    comparison/     # Vorjahresvergleich
    ai/             # AIProvider, OllamaProvider, MockProvider
    jobs/           # Worker
    manufacturers/
  frontend/         # Jinja2-Templates, CSS, htmx.min.js (lokal)
  config/           # header_synonyms.yaml, manufacturers/, rules/
  deploy/           # docker-compose.yml, Caddyfile, Dockerfile, install.sh, backup.sh  (neu)
  tests/  (inkl. data/)
  docs/
  requirements.txt
  README.md
```

Abweichung vom Prompt: Das Verzeichnis heißt nicht `price-ai/`, sondern liegt direkt im Repo-Root. Neu sind `auth/`, `comparison/`, `jobs/` und `deploy/`, wegen des Serverbetriebs und zur Trennung der Zuständigkeiten.

---

## 8. Implementierungsplan

| Gruppe | Inhalt | Nachweis |
|---|---|---|
| **A** | Grundprojekt, DB-Schema + Migrationen, **Login/Benutzer**, Excel-Import, deutsche Zahlenformate, Spaltenerkennung (Synonyme + Heuristik), Import-Vorschau | pytest: Zahlenformate, Layouts, kaputte Dateien, .xls/.xlsm-Ablehnung, Zip-Bombe, Login/Sperre/CSRF |
| **B** | Regelengine (Decimal, Versionierung, Rechenweg, simpleeval), Matching-Kaskade, Vorjahresvergleich | pytest: Referenzbeispiele, Rundungsrandfälle, Pro-Schritt vs. Ende, Staffeln, Statuslogik |
| **C** | AIProvider (Ollama, Mock), Jobs mit Fortschritt/Abbruch, vollständige UI | pytest mit MockProvider inkl. ungültiger JSON-Antworten; manuelle UI-Prüfung |
| **D** | Excel-Export (formelsicher), Belastungstest 50.000 Zeilen, **Docker-Deployment, Caddy, Installationsskript, Backup**, Lizenzprüfung, Betriebsanleitung | pytest Export/Injektion, gemessene Laufzeiten, Probeinstallation auf frischem Ubuntu |

Nach jeder Gruppe gibt es einen kurzen Bericht und es wird auf Freigabe gewartet.

---

## 9. Offene Fragen (vor Gruppe A bzw. B zu klären)

**F1 – Server (nötig vor Gruppe D, hilfreich schon jetzt).** Bitte auf dem Server ausführen und die Ausgabe schicken:
```
cat /etc/os-release | head -3
nproc
free -h
df -h /
ss -tlnp
docker --version
```
Für Ollama mit einem 3B-Modell sollten es mindestens 8 GB RAM sein, besser 16 GB. Mit 4 GB läuft die App, die KI aber nicht sinnvoll.

**F2 – Führende Nullen.** Sind `00123` und `123` derselbe Artikel? Vorschlag: Beim normalisierten Match nur dann gleichsetzen, wenn der Rest rein numerisch ist, und das pro Hersteller abschaltbar machen.

**F3 – Schwellwert.** Vorschlag: Exakte und normalisierte Treffer werden automatisch übernommen. Fuzzy-Treffer und KI-Treffer werden **nie** automatisch übernommen, sondern immer bestätigt; der Score dient nur der Sortierung. Alternativ: Fuzzy ab Score X automatisch übernehmen. Wie hoch wäre X?

**F4 – ARTIKEL_GEÄNDERT.** Vorschlag: Gleiche Artikelnummer, gleicher Preis, aber Bezeichnung, Kategorie oder Einheit haben sich geändert. Ändert sich zusätzlich der Preis, gilt der Preis-Status; die geänderten Felder werden als Hinweis angezeigt.

**F5 – Staffelpreise im Vergleich.** Vorschlag: Jede Staffel (gleiche Mindestmenge) wird einzeln verglichen. Fehlt eine Staffel auf einer Seite, gilt NICHT_EINDEUTIG.

**F6 – Welcher Preis wird verglichen?** EK, Listenpreis oder der nach Regel kalkulierte Preis? Vorschlag: beim Vergleich auswählbar, Standard ist der Listenpreis.

**F7 – Schritttyp "Rundung".** Was soll er können? Zum Beispiel "auf 0,05 runden", "auf ,90 enden", "auf ganze Euro aufrunden"?

**F8 – Rollen.** Reichen admin und benutzer? Wie viele Benutzer ungefähr?

**F9 – Backup.** Wohin? Nur auf den Server selbst (schützt nicht vor Serververlust), auf eine Hetzner Storage Box oder auf einen anderen Ort?
