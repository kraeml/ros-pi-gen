#!/bin/bash -e
# Docker-Dienst aktivieren und ggf. bereits vorhandenen Build-Benutzer
# aufnehmen. Cloud-init setzt die Docker-Gruppe für den First-Boot-Benutzer.

on_chroot << EOF
systemctl enable docker.service
if id -u "${FIRST_USER_NAME}" >/dev/null 2>&1; then
    usermod -aG docker "${FIRST_USER_NAME}"
fi
EOF
