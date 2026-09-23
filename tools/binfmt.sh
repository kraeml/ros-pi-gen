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
# danach (trap-gesichert, siehe tools/build-docker.sh)!
#
# Version-Gate: setup prüft zuerst den aktiven Host-Interpreter (aus dem
# binfmt-Entry, F-Flag-Varianten nutzen ihn in jedem chroot). Ab qemu >= 8
# ist die OFD-Emulation korrekt — dann passiert HIER nichts (kein Entry,
# kein Docker-Aufruf, kein Kernel-Eingriff), der Build läuft mit dem
# Host-Interpreter weiter (z. B. Ubuntu-Vagrant-VM 24.04). Nur bei älterem
# oder fehlendem Interpreter wird der Container-Entry registriert.
#
# usage: binfmt.sh setup|cleanup
set -euo pipefail

ENTRY=qemu-aarch64-rpi
MIN_MAJOR=8
# Korrektes 20-Byte-Magic/-Mask (aarch64-ELF, e_type=EXEC, e_machine=EM_AARCH64);
# pi-gens eigener Fallback-String in build-docker.sh ist defekt (24-Byte-Magic
# gegen 20-Byte-Mask -> EINVAL, und bash-echo interpretiert \x ohnehin nicht).
REGISTER=':qemu-aarch64-rpi:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:/usr/bin/qemu-aarch64:F'

# Aktiven Interpreter des aarch64-binfmt-Entrys ermitteln (leer, wenn kein
# Entry existiert). Der Kernel listet ihn in der Datei des Entrys.
active_interpreter() {
	local entry
	for entry in qemu-aarch64 qemu-aarch64-static; do
		local f="/proc/sys/fs/binfmt_misc/${entry}"
		if [ -r "$f" ]; then
			sed -n 's/^interpreter //p' "$f" | tail -1
			return 0
		fi
	done
	echo ""
}

interpreter_major() {
	# <interpreter> --version -> "qemu-aarch64 version 4.2.1 (…)"
	local out
	out="$("$1" --version 2>/dev/null | head -1)" || return 1
	echo "$out" | sed -n 's/.* version \([0-9][0-9]*\)\..*/\1/p'
}

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
	# Version-Gate: moderner Host-Interpreter -> nichts zu tun
	active="$(active_interpreter)"
	if [ -n "$active" ]; then
		if major="$(interpreter_major "$active")" && [ -n "$major" ] && [ "$major" -ge "$MIN_MAJOR" ]; then
			echo "binfmt: aktiver Host-Interpreter $active (qemu $major.x) ist OFD-tauglich — kein Entry nötig."
			exit 0
		fi
		echo "binfmt: Host-Interpreter $active (qemu ${major:-unbekannt}.x < $MIN_MAJOR.x) emuliert OFD nicht — registriere Container-Entry."
	else
		echo "binfmt: kein aarch64-Host-Entry registriert — registriere Container-Entry."
	fi
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
	if [ -e "/proc/sys/fs/binfmt_misc/$ENTRY" ]; then
		$DOCKER run --rm --privileged pi-gen bash -c "
			mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc 2>/dev/null || true
			echo -1 > /proc/sys/fs/binfmt_misc/$ENTRY
			echo \"binfmt: $ENTRY entfernt\"
		"
	else
		echo "binfmt: kein Entry $ENTRY vorhanden"
	fi
	;;
*)
	echo "usage: binfmt.sh setup|cleanup" >&2
	exit 1
	;;
esac
