#!/bin/bash -e
# Setzt die AccessPopup-SSID aus dem System-Hostname ab: <hostname>-AP
# (Hostname = Geräteidentität, gesetzt via Pi-Imager; keine Etiketten, MAC
# nicht ablesbar). Läuft beim Boot (hostname-ssid.service) und bei
# Hostnamenwechsel (NM-Dispatcher-Action 'hostname').
# Idempotent; im pi-gen-Build NICHT ausführen (nur installieren).

CONF="/etc/accesspopup.conf"
SUFFIX="-AP"
FALLBACK="Roboter"

[ -f "$CONF" ] || exit 0

h="$(hostname 2>/dev/null || true)"
# Umlaute transliterieren, dann auf SSID-kompatible Zeichen reduzieren
h="$(printf '%s' "$h" \
    | sed -e 's/ä/ae/g; s/ö/oe/g; s/ü/ue/g; s/ß/ss/g; s/Ä/Ae/g; s/Ö/Oe/g; s/Ü/Ue/g' \
    | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9-')"
# SSID max. 32 Bytes (WLAN-Spec) inkl. Suffix
max=$(( 32 - ${#SUFFIX} ))
h="${h:0:$max}"
[ -n "$h" ] || h="$FALLBACK"
ssid="${h}${SUFFIX}"

# accesspopup.conf aktualisieren (idempotent; AccessPopup nutzt ap_ssid bei
# der Profil-Erzeugung)
sed -i "s/^ap_ssid=.*/ap_ssid='${ssid}'/" "$CONF"

# Falls das AP-Profil bereits existiert, SSID nachziehen (Hostnamenwechsel)
if nmcli -t -f NAME connection show 2>/dev/null | grep -qx 'AccessPopup'; then
    nmcli connection modify AccessPopup 802-11-wireless.ssid "$ssid" >/dev/null 2>&1 || true
fi

exit 0
