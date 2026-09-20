#!/bin/bash -e
# 07-accesspopup: AccessPopup (NM-AP-Fallback) + Web-UI + Captive-Portal-Redirect
#
# Repliziert die nicht-interaktiven Schritte des upstream-Installers
# (RaspberryConnect/AccessPopup, gepinnter Commit, siehe files/VENDORED.md).
# AccessPopup bleibt unverändert (kein Fork); projektspezifisch ergänzt:
# - hostname-SSID (<hostname>-AP; Hostname via Pi-Imager = Geräteidentität)
# - Dispatcher-Gating: Web-UI + nft-Regeln nur im AP-Fenster
# - DNS-Wildcard + Port-80-Redirect auf 8052 (Captive-Portal-Erkennung)
# - nftables-Isolation der AP-Clients (kein Internet/SSH/Docker/ROS)
#
# Build-Regeln (pi-gen-Chroot): kein NM-Start, kein AP, kein Scan, kein
# accesspopup-Lauf im Build; Units werden nur installiert und enable'd.

# --- AccessPopup Hauptskript + Konfig (ap_pw vorbelegt) ---
install -m 0755 files/accesspopup "${ROOTFS_DIR}/usr/local/bin/accesspopup"
install -m 0644 files/accesspopup.conf "${ROOTFS_DIR}/etc/accesspopup.conf"

# --- AccessPopup systemd-Units (Inhalt wie upstream installconfig.sh) ---
install -m 0644 files/AccessPopup.service "${ROOTFS_DIR}/etc/systemd/system/AccessPopup.service"
install -m 0644 files/AccessPopup.timer "${ROOTFS_DIR}/etc/systemd/system/AccessPopup.timer"

# Drop-in: SSID-Bildung vor dem ersten AccessPopup-Lauf (Timer OnBootSec=0min)
install -d -m 0755 "${ROOTFS_DIR}/etc/systemd/system/AccessPopup.service.d"
install -m 0644 files/AccessPopup.service.d/order.conf \
    "${ROOTFS_DIR}/etc/systemd/system/AccessPopup.service.d/order.conf"

# --- hostname-SSID ---
install -d -m 0755 "${ROOTFS_DIR}/usr/local/sbin"
install -m 0755 files/hostname-ssid.sh "${ROOTFS_DIR}/usr/local/sbin/hostname-ssid.sh"
install -m 0644 files/hostname-ssid.service "${ROOTFS_DIR}/etc/systemd/system/hostname-ssid.service"

# --- NM-Dispatcher (orchestriert Web-UI + nft um den AP) ---
install -d -m 0755 "${ROOTFS_DIR}/etc/NetworkManager/dispatcher.d"
install -m 0755 files/dispatcher-90-accesspopup-portal \
    "${ROOTFS_DIR}/etc/NetworkManager/dispatcher.d/90-accesspopup-portal"

# --- DNS-Wildcard für das NM-shared-dnsmasq (Captive-Detection) ---
install -d -m 0755 "${ROOTFS_DIR}/etc/NetworkManager/dnsmasq-shared.d"
install -m 0644 files/dnsmasq-shared.d/01-wildcard.conf \
    "${ROOTFS_DIR}/etc/NetworkManager/dnsmasq-shared.d/01-wildcard.conf"

# --- nftables-AP-Regeln (nur im AP-Fenster via Dispatcher aktiv) ---
install -d -m 0755 "${ROOTFS_DIR}/etc/nftables.d"
install -m 0644 files/nft-accesspopup.rules "${ROOTFS_DIR}/etc/nftables.d/accesspopup.rules"

# --- AccessPopup-Web-UI (Port 8052) ---
install -d -m 0755 "${ROOTFS_DIR}/usr/local/bin/acpu_web"
cp -r files/acpu_web/. "${ROOTFS_DIR}/usr/local/bin/acpu_web/"
install -m 0644 files/acpu_web.service "${ROOTFS_DIR}/etc/systemd/system/acpu_web.service"
install -m 0644 files/acpu_web_app.service "${ROOTFS_DIR}/etc/systemd/system/acpu_web_app.service"
install -m 0644 files/acpu_web_app.socket "${ROOTFS_DIR}/etc/systemd/system/acpu_web_app.socket"

on_chroot << EOF
set -e
# Systemuser für die Web-UI (kein Login, kein Home)
useradd -r -s /usr/sbin/nologin -d /nonexistent acpu 2>/dev/null || true

# sudoers: Portal-Benutzer darf nur nmcli/iw/tee/Conf/AccessPopup
# (upstream add_permissions; visudo-Prüfung im Chroot)
cat > /etc/sudoers.d/acpu <<'EOT'
acpu ALL=(ALL) NOPASSWD: /usr/bin/nmcli, /usr/sbin/iw, /usr/bin/tee, /etc/accesspopup.conf, /usr/local/bin/accesspopup
EOT
chmod 440 /etc/sudoers.d/acpu
visudo -cf /etc/sudoers.d/acpu

# venv + gepinnte Abhängigkeiten (QEMU-arm64; dauert einige Minuten)
cd /usr/local/bin/acpu_web
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/pip check
chmod 755 /usr/local/bin/acpu_web/acpu_get_std.py /usr/local/bin/acpu_web/pages/app.py

# Web-Units bewusst NICHT enabled: der Dispatcher startet sie nur im
# AP-Fenster (keine unauthentifizierte Oberfläche auf dem Schul-/Heim-LAN).
# AccessPopup selbst: Timer + hostname-SSID aktivieren (kein Start im Build).
systemctl daemon-reload
systemctl enable AccessPopup.timer hostname-ssid.service
EOF
