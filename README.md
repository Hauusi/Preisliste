# Preisliste

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

## Jahresabgleich (Hauptablauf)

1. Hersteller anlegen (Seite Hersteller → Name/Kürzel → Bearbeiten):
   - Kürzel (RT + 12345 = RT12345), Standardregel für den VK (z. B. EK × 2,6)
   - Artikel mit eigener Kalkulation (z. B. × 2,8 bei zu wenig Marge): am einfachsten im Ergebnis des Abgleichs
     Artikel anhaken und Faktor eingeben. Gilt dauerhaft, auch in den Folgejahren. Auf der Herstellerseite auch
     „Artikelnummer beginnt mit …“. Einzelne Artikel gehen vor; sonst wird bei mehreren passenden Regeln nicht geraten.
   - Herstellerliste enthält EK oder UVP/RRP (dann EK = UVP − Händlerrabatt)
   - Währung der Liste und Kurs, z. B. SEK × 0,095 = EUR (EK in € kaufmännisch auf Cent gerundet)
   - Prüfschwelle (Standard ±10 % EK-Änderung)
2. Unsere aktuelle Liste importieren, in Schritt 3 „Unsere Liste“ wählen (EK- und VK-Spalte, optional Serie).
3. Neue Herstellerliste importieren (in der Währung des Herstellers), „Neue Herstellerliste“ wählen,
   in Schritt 5 „Abgleich starten“: Jahrespreisliste (vollständig) oder Preiserhöhung einzelner Serien (Teilliste).
4. Ergebnis: nur unsere Artikel. EK alt/neu und VK alt/neu mit Änderung in %, Faktor VK/EK, Rechenweg pro Artikel.
   Jeder VK wird unabhängig von der Regelengine nachgerechnet (Gegenrechnung); Abweichung = Fehler, alter Preis bleibt.
   Zu prüfen: EK-Änderung ab Schwelle, VK-Änderung passt nicht zur EK-Änderung, VK unter EK, Preis 0,
   fehlender alter EK/VK, unklare Zuordnung, Artikel fehlt (nur bei Jahrespreisliste), Fehler.
   Neue Artikel des Herstellers werden ignoriert. Bei einer Teilliste bleiben nicht enthaltene Artikel unverändert.
5. Positionen bestätigen (optional VK von Hand), unklare Zuordnungen auswählen. Fehler und unklare Zuordnungen
   nur einzeln. Endgültiger Export erst, wenn alles geprüft ist; vorher nur ENTWURF.
6. „Als aktuelle Liste übernehmen“: das Ergebnis wird unsere neue EK/VK-Liste und ist beim nächsten Abgleich
   vorausgewählt. Alle Entscheidungen stehen mit Benutzer und Zeit im Audit-Log und im Export.

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
