#!/usr/bin/env bash
# Hardware-Q-Runner: prueft die Gruppe Q des Abnahmeprotokolls
# (Testprotokoll-AccessPopup.md) direkt am echten Pi – read-only.
#
# Aufruf (vom Build-Host):
#   ssh pi@<ip> 'bash -s' < tests/tools/pi-smoke.sh
#
# Output: Markdown mit Protokoll-IDs (Q1–Q9, Extras) + Beobachtungs-Hilfen
# fuer die Gruppen A/B/D. Exit-Code 1 = FAIL; root-only checks are SKIPped.

set -u

PASS=0; FAIL=0; SKIP=0; FAILED_IDS=(); SKIPPED_IDS=()

note() { printf '%s\n' "$*"; }
hr()   { printf '\n## %s\n' "$1"; }

skip_check() {
  local id="$1" desc="$2" command="$3"
  SKIP=$((SKIP + 1)); SKIPPED_IDS+=("$id")
  note "| $id | SKIP | $desc (Root-Rechte erforderlich) |"
  note "> Manuell als root ausführen: \`$command\`"
}

check() {
  # check <ID> <Beschreibung> <Befehl...>  (harter Check, zaehlt PASS/FAIL)
  local id="$1" desc="$2"; shift 2
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -eq 0 ]; then
    PASS=$((PASS + 1))
    note "| $id | PASS | $desc |"
  else
    FAIL=$((FAIL + 1)); FAILED_IDS+=("$id")
    note "| $id | FAIL | $desc |"
    note "> Ausgabe: \`$(printf '%s' "$out" | head -2 | tr '\n' ';')\`"
  fi
}

check_state() {
  # check_state <ID> <Beschreibung> <ist> <erlaubt:regex>
  local id="$1" desc="$2" state="$3" allow="$4"
  if printf '%s' "$state" | grep -qE "$allow"; then
    PASS=$((PASS + 1)); note "| $id | PASS | $desc ($state) |"
  else
    FAIL=$((FAIL + 1)); FAILED_IDS+=("$id")
    note "| $id | FAIL | $desc (ist: $state, erlaubt: $allow) |"
  fi
}

hr "Gruppe Q – harte Checks"
note "| ID | Ergebnis | Beschreibung |"
note "|---|---|---|"

# Q1: Boot + SSH
check_state "Q1-ssh" "sshd aktiv" "$(systemctl is-active ssh 2>&1 || true)" "^active$"
FAILED_UNITS="$(systemctl list-units --state=failed --no-legend 2>/dev/null | grep -vE '^\s*$' | wc -l)"
check_state "Q1-failed" "keine gescheiterten systemd-Units" "$FAILED_UNITS" "^0$"

# Q2/Q3: enabled
check_state "Q2" "AccessPopup.timer enabled" "$(systemctl is-enabled AccessPopup.timer 2>&1 || true)" "^enabled$"
check_state "Q3" "hostname-ssid.service enabled" "$(systemctl is-enabled hostname-ssid.service 2>&1 || true)" "^enabled$"

# Q4: Web-Units disabled (Dispatcher-Gating)
for u in acpu_web.service acpu_web_app.socket; do
  check_state "Q4-$u" "$u nicht enabled" \
    "$(systemctl is-enabled "$u" 2>&1 || true)" "^(not enabled|disabled)$"
done
ACPU_WANTS="$(find /etc/systemd/system -path '*target.wants*' -name 'acpu_web*' 2>/dev/null | wc -l)"
check_state "Q4-wants" "keine acpu_web-Eintraege in *.target.wants" "$ACPU_WANTS" "^0$"

# Q5: conf
if [ -f /etc/accesspopup.conf ]; then
  PW="$(sed -n "s/^ap_pw='\(.*\)'/\1/p" /etc/accesspopup.conf)"
  check_state "Q5-pw" "ap_pw = Pi-WLAN-Setup-2026" "$PW" "^Pi-WLAN-Setup-2026$"
  check_state "Q5-ssid" "ap_ssid-Platzhalter vorhanden" \
    "$(grep -c '^ap_ssid=' /etc/accesspopup.conf 2>/dev/null || echo 0)" "^[1-9]"
else
  check_state "Q5-conf" "/etc/accesspopup.conf vorhanden" "false" "^true$"
fi

# Q6: nft cache initialization requires CAP_NET_ADMIN; skip cleanly when unprivileged
if [ -x /usr/sbin/nft ]; then
  if [ "$(id -u)" -eq 0 ]; then
    check "Q6" "nft -c accesspopup.rules (Syntax am bcm-Kernel)" \
      /usr/sbin/nft -c -f /etc/nftables.d/accesspopup.rules
  else
    skip_check "Q6" "nft -c accesspopup.rules (Syntax am bcm-Kernel)" \
      "sudo /usr/sbin/nft -c -f /etc/nftables.d/accesspopup.rules"
  fi
else
  check_state "Q6" "nft vorhanden" "fehlend" "^present$"
fi

# Q7: Dispatcher-Rechte
ST="$(stat -c '%a %u %g' /etc/NetworkManager/dispatcher.d/90-accesspopup-portal 2>/dev/null || echo 'missing')"
check_state "Q7" "Dispatcher 755 root:root" "$ST" "^755 0 0$"

# Q8: sudoers file is root-readable only
if [ -x /usr/sbin/visudo ]; then
  if [ "$(id -u)" -eq 0 ]; then
    VIS_OUT="$(/usr/sbin/visudo -cf /etc/sudoers.d/acpu 2>&1)"; VIS_RC=$?
    check_state "Q8" "visudo sudoers.d/acpu parsed OK" \
      "$([ $VIS_RC -eq 0 ] && echo ok || echo "$VIS_OUT")" "^ok$"
  else
    skip_check "Q8" "visudo sudoers.d/acpu parsed OK" \
      "sudo /usr/sbin/visudo -cf /etc/sudoers.d/acpu"
  fi
else
  check_state "Q8" "visudo vorhanden" "fehlend" "^ok$"
fi

# Q9: NM-Dispatcher
check_state "Q9" "NetworkManager-dispatcher aktivierbar" \
  "$(systemctl is-enabled NetworkManager-dispatcher 2>&1 || true)" \
  "^(enabled|enabled-runtime|static|indirect)$"

hr "Extras (pi-gen-Basis, TODO Block 3)"
for p in docker-ce docker-ce-cli containerd.io ansible ansible-core; do
  ST="$(dpkg-query -W -f='${db:Status-Abbrev}' "$p" 2>/dev/null || echo '??')"
  check_state "X-$p" "$p installiert" "$ST" "^ii "
done
check_state "X-docker-enabled" "docker.service enabled" \
  "$(systemctl is-enabled docker.service 2>&1 || true)" "^enabled$"
CI="$(systemctl is-active cloud-init.service 2>&1 || true)"
if [ "$CI" = "failed" ]; then
  check_state "X-cloud-init" "cloud-init.service nicht failed" "failed" "^(active|inactive)$"
else
  check_state "X-cloud-init" "cloud-init.service nicht failed" "$CI" "^(active|inactive)$"
fi

hr "Beobachtungen (fuer Spalten 'Beobachtet' in A/B/D)"
note "* Hostname: \`$(hostname)\` · Modell: \`$(tr -d '\0' </proc/device-tree/model 2>/dev/null)\` · Uptime: \`$(uptime -p)\`"
note "* Up since: \`$(uptime -s 2>/dev/null)\` (Q1: Boot-Beleg, Journal: \`journalctl -b\`)"
note "* Gerätezustand:"
nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status 2>/dev/null | sed 's/^/  * `/;s/$/`/'
note "* Verbindungen (A7/B3/B5/C5: Profile gleichzeitig gespeichert?):"
nmcli -t -f NAME,TYPE,DEVICE,ACTIVE connection show 2>/dev/null | sed 's/^/  * `/;s/$/`/'
AP_SSID="$(nmcli -g 802-11-wireless.ssid connection show AccessPopup 2>/dev/null || true)"
note "* AP-Profil-SSID (A2/B2: <hostname>-AP?): \`${AP_SSID:-(kein Profil)}\`"
note "* Port 8052 (A5/D6: Portal nur im AP-Fenster?):"
ss -tlnp 2>/dev/null | grep ':8052' | sed 's/^/  * /' || note "  * 8052 nicht offen"
note "* nft-Regeln (D5: Tabellen nur waehrend AP?):"
if [ -x /usr/sbin/nft ] && /usr/sbin/nft list ruleset 2>/dev/null | grep -q 'table ip accesspopup'; then
  note "  * \`ip accesspopup\` geladen (AP aktiv)"
else
  note "  * keine accesspopup-Tabelle (AP inaktiv)"
fi
note "* accesspopup.conf (Werte):"
sed -n -e "s/^ap_pw=.*/ap_pw='********' (gesetzt)/p" -e "/^ap_ssid=/p" -e "/^ap_ip=/p" -e "/^wdev0=/p" \
  /etc/accesspopup.conf 2>/dev/null | sed 's/^/  * `/;s/$/`/'
note "* Letzte AccessPopup-Journalzeilen:"
journalctl -u AccessPopup.service -n 8 --no-pager -o short 2>/dev/null | sed 's/^/  * /'

hr "Ergebnis"
note "PASS: $PASS · FAIL: $FAIL · SKIP: $SKIP"
if [ "$FAIL" -gt 0 ]; then
  note "Fehlgeschlagen: ${FAILED_IDS[*]}"
  note "Detaillog ggf. mit: journalctl -b · systemctl --failed · nft list ruleset"
  exit 1
fi
if [ "$SKIP" -gt 0 ]; then
  note "Nicht geprüft: ${SKIPPED_IDS[*]} (Privilegienhinweise oben beachten)"
fi
exit 0
