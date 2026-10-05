#!/bin/bash -e

# Pfad aus der Sicht des Zielsystems (Chroot-Umgebung)
CHROOT_TARGET_DIR="/home/${FIRST_USER_NAME}/pi-base-ansible"

# Pfad aus der Sicht des Host-Buildsystems
HOST_TARGET_DIR="${ROOTFS_DIR}${CHROOT_TARGET_DIR}"

# 1. Zielverzeichnis im Home-Ordner des Benutzers anlegen
# --directory: Legt alle angegebenen Verzeichniskomponenten an
# --mode=0755: Setzt Zugriffsrechte (Lesen/Schreiben/Ausführen für Eigentümer, Lesen/Ausführen für alle)
# --verbose:   Gibt ausgeführte Aktionen auf der Konsole aus
install --directory --mode=0755 --verbose "${HOST_TARGET_DIR}"

# 2. Ansible-Dateien, Unterordner (Rollen) und versteckte Dateien kopieren
# --archive: Behält Rechte, Zeitstempel, Eigentümer und Symlinks bei und arbeitet rekursiv
# /. sorgt dafür, dass auch versteckte Konfigurationsdateien mitkopiert werden
cp --archive files/pi-base-ansible/. "${HOST_TARGET_DIR}/"

# 3. Berechtigungen im Chroot anpassen und Playbook ausführen
on_chroot << EOF
# Eigentümer und Gruppe rekursiv auf den Standardbenutzer setzen
# --recursive: Wendet die Berechtigungsänderung auf alle Dateien und Unterordner an
chown --recursive "${FIRST_USER_NAME}:${FIRST_USER_NAME}" "${CHROOT_TARGET_DIR}"

# In das Arbeitsverzeichnis wechseln
cd "${CHROOT_TARGET_DIR}"

# Ansible-Playbook lokal ausführen
# --inventory:      Gibt die Zielhosts an (das Komma signalisiert eine direkte Host-Liste, keine Datei)
# --connection:     Verwendet lokale Ausführung statt einer SSH-Verbindung
ansible-playbook \
  --inventory "localhost," \
  --connection local \
  --extra-vars "robot_codeserver_user=${FIRST_USER_NAME}" \
  playbook.yml
EOF