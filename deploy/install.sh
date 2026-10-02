#!/usr/bin/env bash
# Installation/Update der Preisliste auf dem Server. Mehrfach ausführbar.
# Aufruf: sudo bash deploy/install.sh
set -euo pipefail

cd "$(dirname "$0")"
DEPLOY_DIR="$(pwd)"

echo "== 1/7 Swap prüfen"
if ! swapon --show | grep -q .; then
  echo "Kein Swap vorhanden, lege 4 GB /swapfile an"
  fallocate -l 4G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
else
  echo "Swap vorhanden"
fi

echo "== 2/7 Verzeichnisse"
mkdir -p "$DEPLOY_DIR/data" "$DEPLOY_DIR/ollama"
chown 10001:10001 "$DEPLOY_DIR/data"
chmod 700 "$DEPLOY_DIR/data"

echo "== 3/7 Portprüfung 8010"
if ss -tln | grep -q '127.0.0.1:8010 ' && ! docker compose ps --status running app 2>/dev/null | grep -q app; then
  echo "FEHLER: Port 8010 ist von einem anderen Dienst belegt." >&2
  exit 1
fi

echo "== 4/7 KI-Modell (einmalig, ca. 2 GB)"
if [ -z "$(ls -A "$DEPLOY_DIR/ollama" 2>/dev/null)" ]; then
  docker compose --profile setup run --rm ollama-setup
else
  echo "Modellverzeichnis vorhanden, überspringe Download"
fi

echo "== 5/7 Bauen und starten"
docker compose up -d --build app ollama

echo "== 6/7 Warten auf Health-Check"
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8010/health >/dev/null 2>&1; then
    echo "App läuft auf 127.0.0.1:8010"
    break
  fi
  sleep 2
  if [ "$i" = 30 ]; then
    echo "FEHLER: App antwortet nicht. Logs: docker compose logs app" >&2
    exit 1
  fi
done

if ! docker compose exec -T app python -c "
from sqlalchemy import select, func
from backend.config import get_settings
from backend.database import engine as e
from backend.models.entities import User
e.configure(f'sqlite:///{get_settings().db_path}')
with e.session_scope() as db:
    raise SystemExit(0 if db.scalar(select(func.count(User.id))) else 1)
"; then
  echo
  echo "Noch kein Benutzer vorhanden. Administrator anlegen:"
  read -rp "Benutzername: " ADMIN
  docker compose exec app python -m backend.cli create-admin "$ADMIN"
fi

echo "== 7/7 Tägliches Backup (02:17 Uhr, 14 Sicherungen in $DEPLOY_DIR/data/backups)"
cat > /etc/cron.d/preisliste-backup <<CRON
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
17 2 * * * root cd $DEPLOY_DIR && docker compose exec -T app python -m backend.cli backup 14 >> /var/log/preisliste-backup.log 2>&1
CRON
chmod 644 /etc/cron.d/preisliste-backup
docker compose exec -T app python -m backend.cli backup 14

echo
echo "Fertig. Test per SSH-Tunnel: ssh -L 8010:127.0.0.1:8010 root@<server>, dann http://localhost:8010"
echo "Umstellung der Domain: sudo bash deploy/switch-nginx.sh"
