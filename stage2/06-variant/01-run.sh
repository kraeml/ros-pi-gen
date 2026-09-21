#!/bin/bash -e
# LightDM nur in der Desktop-Variante aktivieren; PIGEN_VARIANT kommt aus
# der pi-gen-config (exportiert) und wird auf dem Host expandiert. Bewusst
# NICHT "VARIANT": console-setup (setupcon) nutzt dieselbe Variable im
# Chroot und scheitert sonst an fehlenden keyboard.headless-Konfigen.

if [ "${PIGEN_VARIANT}" = "desktop" ]; then
    on_chroot << EOF
systemctl enable lightdm.service
EOF
fi
