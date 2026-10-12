#!/bin/bash -e
# Installiert Node.js 24 und Node-RED im Image und aktiviert den Dienst.
# Läuft im pi-gen-Kontext: ROOTFS_DIR und FIRST_USER_NAME werden von pi-gen
# gesetzt, on_chroot führt Befehle im Ziel-Rootfs aus.

# --- Pins: vor dem Build prüfen ---------------------------------------------
NODERED_VERSION="5.0.8"     # Platzhalter; echte Version vorher mit
                            # "npm view node-red dist-tags" nachsehen
INSTALLER_REF="master"      # besser: Tag oder Commit-Hash für reproduzierbare Builds
INSTALLER_URL="https://github.com/node-red/linux-installers/releases/latest/download/install-update-nodered-deb"

# --- Installation -------------------------------------------------------------
# Heredoc ohne Quotes: pi-gen löst ${...} auf, bevor der Text ins Chroot geht.
# Deshalb "\\" für Zeilenfortsetzungen: im Chroot kommt ein einfaches "\" an.
# Der Installer läuft als root, weil sudo im Chroot nicht funktioniert
# ("effective uid is not 0"). Der Zielbenutzer wird per --nodered-user gesetzt.
# --no-init: keine Rückfrage zur Initialisierung der Einstellungen (settings.js)
on_chroot << EOF
set -e
curl -fsSL "${INSTALLER_URL}" -o /tmp/nodered-installer.sh
bash /tmp/nodered-installer.sh \\
  --confirm-root \\
  --confirm-install \\
  --node24 \\
  --nodered-version="${NODERED_VERSION}" \\
  --confirm-pi \\
  --nodered-user="${FIRST_USER_NAME}" \\
  --no-init
rm -f /tmp/nodered-installer.sh
EOF

# --- Versionen festhalten -----------------------------------------------------
# Landet im Image unter /etc/nodered-build-versions und hilft später bei der
# Fehlersuche ("welche Version steckt in diesem Image?").
# Ungequotetes Heredoc: ${FIRST_USER_NAME} löst pi-gen auf, während "\$(...)"
# erst im Chroot ausgeführt wird. Ohne Backslash würde der Befehl schon auf dem
# Build-Host laufen und die Versionen des Hosts statt des Images eintragen.
on_chroot << EOF
{
  echo "node: \$(node --version)"
  echo "npm: \$(npm --version)"
  echo "node-red: \$(runuser -u "${FIRST_USER_NAME}" -- node-red --version 2>/dev/null | head -n1)"
} > /etc/nodered-build-versions
EOF

# --- systemd-Override ---------------------------------------------------------
# Drop-in statt Änderung der Original-Unit: übersteht Updates des Installers.
# -D legt das Verzeichnis nodered.service.d bei Bedarf mit an.
install -D -m 644 files/nodered-override.conf \
  "${ROOTFS_DIR}/etc/systemd/system/nodered.service.d/override.conf"

# --- Dienst aktivieren --------------------------------------------------------
# Gequotetes Heredoc: nichts zu ersetzen, alles läuft unverändert im Chroot.
# "enable" setzt nur den Symlink für den Start beim Boot; gestartet wird der
# Dienst erst auf dem laufenden Pi, nicht beim Image-Bau.
on_chroot << 'EOF'
systemctl enable nodered.service
EOF
