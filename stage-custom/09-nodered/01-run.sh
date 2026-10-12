#!/bin/bash -e

# Pins: vor dem Build anpassen
NODERED_VERSION="5.0.8"     # Platzhalter, aktuelle Version selbst eintragen
INSTALLER_REF="master"      # besser: Tag oder Commit-Hash
INSTALLER_URL="https://raw.githubusercontent.com/node-red/linux-installers/${INSTALLER_REF}/deb/update-nodejs-and-nodered"

on_chroot << EOF
set -e
su - "${FIRST_USER_NAME}" -c '
  curl -fsSL "${INSTALLER_URL}" -o /tmp/nodered-installer.sh
  bash /tmp/nodered-installer.sh \
    --confirm-root \
    --confirm-install \
    --node24 \
    --nodered-version="${NODERED_VERSION}" \
    --confirm-pi \
    --nodered-user="${FIRST_USER_NAME}" \
    --no-init
  rm -f /tmp/nodered-installer.sh
'
EOF

# Versionen festhalten
on_chroot << 'EOF'
{
  echo "node: $(node --version)"
  echo "npm: $(npm --version)"
  echo "node-red: $(su - "${FIRST_USER_NAME}" -c 'node-red --version 2>/dev/null | head -n1')"
} > /etc/nodered-build-versions
EOF

install -d "${ROOTFS_DIR}/etc/systemd/system/nodered.service.d"
cat > "${ROOTFS_DIR}/etc/systemd/system/nodered.service.d/override.conf" <<'EOF'
[Service]
User=pi
Group=pi
WorkingDirectory=/home/pi
EOF

on_chroot << 'EOF'
systemctl enable nodered.service
EOF