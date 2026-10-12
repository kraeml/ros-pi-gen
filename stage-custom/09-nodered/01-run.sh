#!/bin/bash -e

NODERED_VERSION="5.0.8"     # Platzhalter, vor dem Build prüfen
INSTALLER_REF="master"      # besser: Tag oder Commit-Hash
INSTALLER_URL="https://raw.githubusercontent.com/node-red/linux-installers/${INSTALLER_REF}/deb/update-nodejs-and-nodered"

# Installer als Benutzer ausführen; Variablen explizit durchreichen
on_chroot << EOF
set -e
runuser -u "${FIRST_USER_NAME}" -- bash -c '
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
'
EOF

# Versionen festhalten (Variable wird hier von pi-gen aufgelöst)
on_chroot << EOF
{
  echo "node: \$(node --version)"
  echo "npm: \$(npm --version)"
  echo "node-red: \$(runuser -u "${FIRST_USER_NAME}" -- node-red --version 2>/dev/null | head -n1)"
} > /etc/nodered-build-versions
EOF

install -D -m 644 files/nodered-override.conf \
  "${ROOTFS_DIR}/etc/systemd/system/nodered.service.d/override.conf"

on_chroot << 'EOF'
systemctl enable nodered.service
EOF