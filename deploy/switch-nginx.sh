#!/usr/bin/env bash
# Stellt https://salesassistent.duckdns.org auf die neue App um und stoppt die alte App.
# - sichert nginx-Konfiguration, alten App-Ordner und alte Datenbank
# - behält Zertifikat (certbot); nginx-Passwortabfrage nur mit KEEP_BASIC_AUTH=1 (App hat eigene Anmeldung)
# - setzt nginx bei Fehler automatisch zurück
# Die alte App wird nur gestoppt, nicht gelöscht. Löschen: siehe Ausgabe am Ende.
# Aufruf: sudo bash deploy/switch-nginx.sh
set -euo pipefail

DOMAIN="salesassistent.duckdns.org"
SITE="/etc/nginx/sites-available/salesassistent"
OLD_APP="/root/apps/salesassistent"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/root/backup-salesassistent-$STAMP"

curl -fsS http://127.0.0.1:8010/health >/dev/null || { echo "FEHLER: Neue App läuft nicht auf 127.0.0.1:8010 (erst install.sh)" >&2; exit 1; }
[ -f "$SITE" ] || { echo "FEHLER: $SITE nicht gefunden" >&2; exit 1; }
[ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ] || { echo "FEHLER: Zertifikat fehlt" >&2; exit 1; }

echo "== Sicherung nach $BACKUP"
mkdir -p "$BACKUP"
chmod 700 "$BACKUP"
cp -a "$SITE" "$BACKUP/nginx-salesassistent.conf"
if [ -d "$OLD_APP" ]; then
  tar czf "$BACKUP/alte-app.tar.gz" -C "$(dirname "$OLD_APP")" "$(basename "$OLD_APP")"
  if docker ps --format '{{.Names}}' | grep -q '^salesassistent-postgres-1$'; then
    docker exec salesassistent-postgres-1 pg_dump -U postgres salesassistent | gzip > "$BACKUP/alte-datenbank.sql.gz"
  fi
fi

AUTH=""
if [ "${KEEP_BASIC_AUTH:-0}" = "1" ] && [ -f /etc/nginx/.htpasswd ]; then
  AUTH='        auth_basic "Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd;'
fi

echo "== Neue nginx-Konfiguration"
cat > "$SITE" <<NGINX
server {
    server_name $DOMAIN;

    client_max_body_size 25m;
    add_header Strict-Transport-Security "max-age=31536000" always;

    location / {
$AUTH
        proxy_pass http://127.0.0.1:8010;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }

    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
}
server {
    if (\$host = $DOMAIN) {
        return 301 https://\$host\$request_uri;
    } # managed by Certbot

    listen 80;
    server_name $DOMAIN;
    return 404; # managed by Certbot
}
NGINX

if ! nginx -t; then
  echo "FEHLER: nginx-Konfiguration ungültig, stelle alte wieder her" >&2
  cp -a "$BACKUP/nginx-salesassistent.conf" "$SITE"
  nginx -t && systemctl reload nginx
  exit 1
fi
systemctl reload nginx
echo "nginx neu geladen"

echo "== Alte App stoppen (Daten bleiben erhalten)"
if [ -f "$OLD_APP/docker-compose.yml" ]; then
  (cd "$OLD_APP" && docker compose down)
fi

echo
echo "Fertig. https://$DOMAIN zeigt jetzt die neue App."
echo "Sicherung: $BACKUP"
echo "Zurück zur alten App:  cp $BACKUP/nginx-salesassistent.conf $SITE && nginx -t && systemctl reload nginx && (cd $OLD_APP && docker compose up -d)"
echo "Alte App endgültig löschen (erst nach Prüfung!):"
echo "  cd $OLD_APP && docker compose down -v --rmi local && cd / && rm -rf $OLD_APP"
