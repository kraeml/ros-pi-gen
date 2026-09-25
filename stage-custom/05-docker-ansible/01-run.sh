#!/bin/bash -e
# Docker-APT-Repository im Zielsystem einrichten (Kommandos laufen im Chroot);
# ${ARCH} und ${RELEASE} expandieren build.sh-seitig im Host-Kontext.

on_chroot << EOF
set -e
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${RELEASE} stable" > /etc/apt/sources.list.d/docker.list
apt-get -o Acquire::Retries=3 update
EOF
