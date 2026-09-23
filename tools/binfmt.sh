#!/usr/bin/env bash
# qemu-Interpreter-Entry für arm64-Emulation im Build registrieren/entfernen.
#
# Hintergrund: der Host-binfmt-Entry zeigt i. d. R. auf ein altes Host-
# qemu-user-static. Ältere qemu-Versionen (beobachtet: 4.2.1, Ubuntu 20.04)
# emulieren OFD-Dateisperren falsch — fcntl(F_OFD_SETLKW) liefert EINVAL —
# wodurch systemd-sysusers im stage0-Bootstrap abbricht ("Failed to take
# /etc/passwd lock: Invalid argument"). Der pi-gen-Container bringt ein
# modernes qemu mit (trixie: 10.x); dieser Entry (neuester gewinnt) shadowed
# den Host-Entry für die Dauer des Builds. Registration geschieht im
# Container-Namespace — der Kernel hält den Interpreter-FD offen (F-Flag),
# auch nach Container-Ende. Achtung: binfmt_misc ist kernel-global; cleanup
# danach!
#
# usage: binfmt.sh setup|cleanup
set -euo pipefail

ENTRY=qemu-aarch64-rpi
# Korrektes 20-Byte-Magic/-Mask (aarch64-ELF, e_type=EXEC, e_machine=EM_AARCH64);
# pi-gens eigener Fallback-String in build-docker.sh ist defekt (24-Byte-Magic
# gegen 20-Byte-Mask -> EINVAL, und bash-echo interpretiert \x ohnehin nicht).
REGISTER=':qemu-aarch64-rpi:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:/usr/bin/qemu-aarch64:F'

# docker ggf. per sudo (gleiches Fallback-Muster wie build-docker.sh)
DOCKER=docker
if ! docker ps >/dev/null 2>&1; then
	DOCKER="sudo docker"
	if ! $DOCKER ps >/dev/null 2>&1; then
		echo "binfmt.sh: docker nicht erreichbar (auch nicht per sudo)" >&2
		exit 1
	fi
fi

cmd="${1:-}"
case "$cmd" in
setup)
	$DOCKER run --rm --privileged pi-gen bash -c "
		set -e
		mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc 2>/dev/null || true
		[ -e /proc/sys/fs/binfmt_misc/$ENTRY ] && echo -1 > /proc/sys/fs/binfmt_misc/$ENTRY || true
		printf '%s' '$REGISTER' > /proc/sys/fs/binfmt_misc/register
		grep -q enabled /proc/sys/fs/binfmt_misc/$ENTRY
		echo \"binfmt: $ENTRY registriert (\$(/usr/bin/qemu-aarch64 --version | head -1))\"
	"
	;;
cleanup)
	$DOCKER run --rm --privileged pi-gen bash -c "
		mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc 2>/dev/null || true
		if [ -e /proc/sys/fs/binfmt_misc/$ENTRY ]; then
			echo -1 > /proc/sys/fs/binfmt_misc/$ENTRY
			echo \"binfmt: $ENTRY entfernt\"
		else
			echo \"binfmt: kein Entry $ENTRY vorhanden\"
		fi
	"
	;;
*)
	echo "usage: binfmt.sh setup|cleanup" >&2
	exit 1
	;;
esac
