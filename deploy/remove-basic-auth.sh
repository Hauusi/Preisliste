#!/usr/bin/env bash
# Entfernt die zusätzliche nginx-Passwortabfrage (Browser-Popup). Danach gilt nur noch die Anmeldung der App
# (mit Sperre nach Fehlversuchen und IP-Begrenzung).
# - sichert die nginx-Konfiguration vorher
# - setzt bei ungültiger Konfiguration automatisch zurück
# Aufruf: sudo bash deploy/remove-basic-auth.sh
set -euo pipefail

SITE="/etc/nginx/sites-available/salesassistent"
BACKUP="$SITE.bak-$(date +%Y%m%d-%H%M%S)"

[ -f "$SITE" ] || { echo "FEHLER: $SITE nicht gefunden" >&2; exit 1; }
if ! grep -q 'auth_basic' "$SITE"; then
  echo "Keine Passwortabfrage in $SITE gefunden – nichts zu tun."
  exit 0
fi
cp -a "$SITE" "$BACKUP"
sed -i '/^\s*auth_basic\(_user_file\)\?\s/d' "$SITE"
if ! nginx -t; then
  echo "FEHLER: nginx-Konfiguration ungültig, stelle Sicherung wieder her" >&2
  cp -a "$BACKUP" "$SITE"
  nginx -t && systemctl reload nginx
  exit 1
fi
systemctl reload nginx
echo "Fertig: Browser-Popup entfernt. Sicherung: $BACKUP"
echo "Rückgängig: cp $BACKUP $SITE && nginx -t && systemctl reload nginx"
