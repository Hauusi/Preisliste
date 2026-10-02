# Betrieb auf dem Server

Server: Hetzner, Ubuntu 24.04, `62.238.39.31`, Domain `https://salesassistent.duckdns.org`.
Installationsort: `/root/apps/preisliste`, Docker-Dateien in `deploy/`.

## Aufbau

- nginx (Host) → `127.0.0.1:8010` → Container `app` (FastAPI, SQLite in `deploy/data/`)
- Container `ollama` im internen Netz ohne Internet, Modelle in `deploy/ollama/`
- Zusätzlich zur App-Anmeldung: nginx-Passwortabfrage (`/etc/nginx/.htpasswd`)

## Häufige Aufgaben

| Aufgabe | Befehl (im Ordner `/root/apps/preisliste/deploy`) |
|---|---|
| Status | `docker compose ps` |
| Logs | `docker compose logs --tail 100 app` |
| Neustart | `docker compose restart app` |
| Update | `cd .. && git pull && sudo bash deploy/install.sh` |
| Admin anlegen | `docker compose exec app python -m backend.cli create-admin <name>` |
| Passwort zurücksetzen | `docker compose exec app python -m backend.cli reset-password <name>` |
| Backup sofort | `docker compose exec app python -m backend.cli backup 14` |
| KI-Status | `docker compose logs app \| grep "KI:"` oder Dashboard |
| nginx-Passwort ändern | `htpasswd /etc/nginx/.htpasswd <benutzer>` (Paket `apache2-utils`) |

## Nur Daten löschen (Benutzer und Regeln bleiben)

Löscht Hersteller, Preislisten, Artikel, Kalkulationen, Vergleiche und Uploads. Vorher wird automatisch gesichert.
Regeln bleiben erhalten, verlieren aber die Zuordnung zum Hersteller.

```
cd /root/apps/preisliste/deploy
docker compose exec app python -m backend.cli clear-data --ja
```

## Alle Daten löschen (Neustart)

Löscht Listen, Hersteller, Regeln, Vergleiche, Benutzer und Uploads. Vorher wird automatisch eine Sicherung angelegt.
Die App muss dabei gestoppt sein, sonst arbeitet sie mit der gelöschten Datei weiter.

```
cd /root/apps/preisliste/deploy
docker compose stop app
docker compose run --rm app python -m backend.cli reset-data --ja
docker compose start app
docker compose exec app python -m backend.cli create-admin <name>
```

## Backup

- Täglich 02:17 Uhr per `/etc/cron.d/preisliste-backup`, Log `/var/log/preisliste-backup.log`.
- Ablage: `deploy/data/backups/preisliste-JJJJMMTT-HHMMSS.tar.gz`, die letzten 14 bleiben.
- Inhalt: konsistente Kopie der Datenbank (SQLite-Backup-API, mit Integritätsprüfung) und alle hochgeladenen Excel-Dateien.
- **Einschränkung:** Die Sicherungen liegen auf demselben Server. Sie schützen vor Bedienfehlern und kaputten Updates, nicht vor Plattendefekt, Serververlust oder Einbruch. Für mehr Sicherheit den Ordner `deploy/data/backups` regelmäßig woandershin kopieren (z. B. `scp` auf den eigenen Rechner oder eine Hetzner Storage Box).

### Wiederherstellen

```
cd /root/apps/preisliste/deploy
docker compose stop app
mkdir -p /root/restore && tar xzf data/backups/preisliste-<DATUM>.tar.gz -C /root/restore
cp data/preisliste.sqlite3 /root/preisliste-vor-restore.sqlite3      # aktuellen Stand sichern
rm -f data/preisliste.sqlite3-wal data/preisliste.sqlite3-shm
cp /root/restore/preisliste.sqlite3 data/preisliste.sqlite3
cp -a /root/restore/uploads/. data/uploads/
chown -R 10001:10001 data
docker compose start app
```

## Rückfall auf die alte App

Die alte App ist gestoppt, aber noch vorhanden, bis sie gelöscht wird. Sicherung: `/root/backup-salesassistent-20261001-151602`.

```
cp /root/backup-salesassistent-20261001-151602/nginx-salesassistent.conf /etc/nginx/sites-available/salesassistent
nginx -t && systemctl reload nginx
cd /root/apps/salesassistent && docker compose up -d
```

## Laufzeiten

Gemessen in der Entwicklungsumgebung, **nicht** auf dem Server. Auf dem Server können die Werte abweichen.

| Vorgang | Dauer | Speicher |
|---|---|---|
| Import 50.000 Zeilen (Lesen + Prüfen + Schreiben) | ca. 19 s | ca. 380 MB Spitze |
| Vergleich 10.000 gegen 10.000 Artikel (200 unscharfe Fälle) | ca. 2,4 s | – |
| KI-Anfrage `llama3.2:3b` auf 4 CPU-Kernen | **nicht gemessen** | Modell ca. 2–3 GB |

KI-Laufzeit auf dem Server messen: einen KI-Job starten, auf der Job-Seite stehen Start- und Endzeit. Dauer ÷ Anzahl Anfragen = Zeit pro Anfrage. Bitte das Ergebnis hier eintragen.

## Sicherheit

- Aus dem Internet erreichbar sind nur nginx (80/443) und SSH (22). Prüfen: `ss -tlnp`.
- Empfehlung: In der Hetzner Cloud Console eine Firewall setzen, eingehend nur 22, 80, 443. Docker umgeht `ufw`.
- Updates des Systems: `apt update && apt upgrade`, danach ggf. Neustart. Die Container starten automatisch.
- Docker-Image `ollama/ollama:latest` ist nicht auf eine Version festgelegt. Nach erfolgreicher Installation festschreiben:
  `docker image inspect ollama/ollama:latest --format '{{index .RepoDigests 0}}'` und den Wert in `docker-compose.yml` statt `:latest` eintragen.
