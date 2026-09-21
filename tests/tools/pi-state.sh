#!/usr/bin/env bash
# Status-Report fuer die Hardware-Testgruppen A–D (Abnahmetests
# Testprotokoll-AccessPopup.md). Nur lesend; auf dem Pi ausfuehren, z. B.:
#   ssh pi@192.168.50.5 'bash -s' < tests/tools/pi-state.sh
# Liefert Markdown-Beobachtungen fuer die Spalten "Beobachtet"/"OK".

set -u

hr() { printf '\n## %s\n' "$1"; }

hr "System"
printf '%s\n' \
  "* Hostname: \`$(hostname)\`" \
  "* Modell: \`$(tr -d '\0' </proc/device-tree/model 2>/dev/null || echo '?')\`" \
  "* Uptime: \`$(uptime -p 2>/dev/null || echo '?')\`"

hr "Units (is-enabled / is-active)"
for u in AccessPopup.timer AccessPopup.service hostname-ssid.service \
         acpu_web.service acpu_web_app.service acpu_web_app.socket \
         NetworkManager-dispatcher; do
  e="$(systemctl is-enabled "$u" 2>&1 || true)"
  a="$(systemctl is-active "$u" 2>&1 || true)"
  printf '* `%s`: enabled=%s active=%s\n' "$u" "$e" "$a"
done

hr "Port 8052 (Web-UI)"
if ss -tln 2>/dev/null | grep -q ':8052'; then
  ss -tlnp 2>/dev/null | grep ':8052' | sed 's/^/* /'
else
  echo '* 8052 nicht offen'
fi

hr "nftables (AP-Isolation aktiv?)"
if command -v nft >/dev/null 2>&1; then
  if nft list ruleset 2>/dev/null | grep -q 'table ip accesspopup'; then
    echo '* Tabelle `ip accesspopup` geladen (AP-Fenster aktiv)'
    nft list ruleset 2>/dev/null | grep -c 'accesspopup' | sed 's/^/* Zeilen mit accesspopup: /'
  else
    echo '* Keine accesspopup-Tabelle geladen (AP inaktiv oder Dispatcher-Ladefehler)'
  fi
else
  echo '* nft nicht vorhanden'
fi

hr "Netzwerk (NetworkManager)"
nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status 2>/dev/null | sed 's/^/* /'
echo
nmcli -t -f NAME,TYPE,DEVICE,ACTIVE connection show 2>/dev/null | sed 's/^/* /'

hr "AP-Profil (SSID)"
if nmcli -g 802-11-wireless.ssid connection show AccessPopup 2>/dev/null; then
  :
else
  echo '* Kein AccessPopup-Profil vorhanden'
fi

hr "accesspopup.conf (ap_pw maskiert)"
if [ -f /etc/accesspopup.conf ]; then
  sed -n -e "s/^ap_pw=.*/ap_pw='********' (gesetzt)/p" \
         -e "s/^\(ap_ssid=\)/\1/p" -e "s/^\(ap_ip=\)/\1/p" \
         -e "s/^\(wdev0=\)/\1/p" /etc/accesspopup.conf | sed 's/^/* /'
else
  echo '* /etc/accesspopup.conf fehlt'
fi

hr "Letzte AccessPopup-Ereignisse (Journal)"
journalctl -u AccessPopup.service -n 15 --no-pager -o short 2>/dev/null | tail -15 || true
