#!/bin/bash -e
# Docker-Dienst aktivieren und ersten Benutzer in die docker-Gruppe aufnehmen;
# ${FIRST_USER_NAME} expandiert build.sh-seitig (Default 'pi'). Der erste
# Benutzer wird erst beim ersten Boot angelegt (Setup-Assistent) – der
# usermod greift dann nicht; siehe README.md (Erster Benutzer).

on_chroot << EOF
systemctl enable docker.service
if id -u "${FIRST_USER_NAME}" >/dev/null 2>&1; then
    usermod -aG docker "${FIRST_USER_NAME}"
fi
EOF
