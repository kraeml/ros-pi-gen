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
# Ubuntu 24.04 registriert als Interpreter einen Symlink mit abweichendem
# Namen (/usr/libexec/qemu-binfmt/aarch64-binfmt-P -> /usr/bin/qemu-
# aarch64-static): der Ubuntu-Patch im Binary verweigert Direktaufrufe
# unter -binfmt-P-Namen — beobachtet (Live-Test 2026-09-24, verbatim:
# "qemu: … has to be run using kernel binfmt-misc subsystem", rc 1;
# Patch-Dokumentation nicht recherchiert) — deshalb löst das Gate den
# Pfad via readlink -f auf und fragt die Version am echten Binary. Echte
# Wrapper-Skripte (#!, Debian-Format: Shebang in Zeile 1, exec-Zeile in
# Zeile 2) werden auf die Kopfzeilen begrenzt geparst; unauflösbar ->
# fail-safe: registrieren.
#
# Bekannte Einschränkungen (bewusst dokumentiert statt verschwiegen):
# - MIN_MAJOR=8 ist eine Beobachtung, kein verbriefender Changelog-Beleg:
#   gemessen 4.2.1 = defekt (EINVAL), 10.0.13 = ok, 8.2.2 (VM) = ok. Bei
#   Zweifeln regelt das fail-safe-Verhalten (unlesbares Format ->
#   Fallback-Registrierung).
# - F-Flag/Inode-Randfall: der Kernel hält den Interpreter als Inode-Referenz
#   offen; der Pfad im Entry zeigt nach einem `apt upgrade qemu-user-static`
#   ggf. auf eine NEUE Version, während der Kernel noch die ALTE Inode nutzt.
#   Das Version-Gate liest den Pfad — im Zweifel Entry löschen/neu
#   registrieren (make binfmt-cleanup && make binfmt-setup) oder rebooten;
#   Symptom sonst: passwd-lock-Fehler trotz moderner Version am Pfad.
# - interpreter_major($active) mit totem Pfad/nonstandard-Format: getestet
#   (2026-09-23, bash 5.0.17) — if-Kontext schluckt rc != 0 trotz set -e,
#   leeres Ergebnis führt in den (sicheren) Fallback-Registrierungspfad.
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
	# <binary> --version -> "qemu-aarch64 version 8.2.2 (…)" — 4.2.1 (der
	# ursprüngliche Auslöser) liefert dasselbe Format, beide Fälle sind im
	# Gate lebendig. Unverständliches Format -> leerer Output -> Aufrufer
	# fällt in den sicheren Fallback (registrieren statt überspringen).
	local out
	out="$("$1" --version 2>/dev/null | head -1)" || return 1
	echo "$out" | sed -n 's/.* version \([0-9][0-9]*\)\..*/\1/p'
}

# Major-Version des effektiven Interpreters ermitteln (leer = unauflösbar
# -> Aufrufer fällt in den sicheren Fallback). Sequenzielle Fallbacks:
#   1. direkt: <interpreter> --version (z. B. Host 20.04: qemu-aarch64-static)
#   2. Symlink auflösen: Ubuntu 24.04 registriert -binfmt-P-Symlinks, deren
#      Ziel sich unter dem -binfmt-P-Namen nicht direkt aufrücken lässt
#      (beobachtet: "has to be run using kernel binfmt-misc subsystem") —
#      Version am echten Binary (readlink -f) fragen
#   3. #-Skripte (Debian-Wrapper-Format: Shebang Zeile 1 OHNE qemu-Pfad,
#      exec-Zeile Zeile 2 — Zeile-1-only-Parsen wäre daher wirkungslos):
#      Suche auf die Kopfzeilen (head -n 3) begrenzt, um späte False-Hits
#      in längeren Skripten auszuschließen (Review 2026-09-24)
# Kein globaler Seiteneffekt: Major wird hier berechnet (local) und einmalig
# zurückgegeben (Review: doppelte Berechnung/versteckte Abhängigkeit entfernt).
effective_major() {
	local path="$1" resolved cand m
	m="$(interpreter_major "$path")" || m=""
	if [ -n "$m" ]; then
		echo "$m"
		return 0
	fi
	resolved="$(readlink -f "$path" 2>/dev/null)" || resolved=""
	if [ -n "$resolved" ] && [ "$resolved" != "$path" ]; then
		m="$(interpreter_major "$resolved")" || m=""
		[ -n "$m" ] && { echo "$m"; return 0; }
	fi
	if [ -f "$path" ] && [ "$(head -c 2 "$path" 2>/dev/null)" = "#!" ]; then
		# Alle Kandidaten der Kopfzeilen prüfen: ein inkommentierter Fake-Pfad
		# (z. B. in einer Kommentarzeile) darf die exec-Zeile nicht verdrängen
		# — erster Kandidat, der ausführbar ist UND eine Version liefert, gilt.
		while IFS= read -r cand; do
			if [ -n "$cand" ] && [ -x "$cand" ]; then
				m="$(interpreter_major "$cand")" || m=""
				if [ -n "$m" ]; then
					echo "$m"
					return 0
				fi
			fi
		done <<< "$(head -n 3 "$path" | grep -a -o '/[A-Za-z0-9/_.-]*qemu-aarch64[A-Za-z0-9_.-]*')"
	fi
	echo ""
}

# docker ggf. per sudo (gleiches Fallback-Muster wie build-docker.sh).
# Aufgabenbezogen aufrufen: cleanup muss auch ohne docker in die
# Handlungsanweisung laufen können (der frühere Top-Guard hätte den
# Fallback-Zweig nie erreicht).
require_docker() {
	DOCKER=docker
	if ! docker ps >/dev/null 2>&1; then
		DOCKER="sudo docker"
		if ! $DOCKER ps >/dev/null 2>&1; then
			echo "binfmt.sh: docker nicht erreichbar (auch nicht per sudo)" >&2
			return 1
		fi
	fi
}

cmd="${1:-}"
case "$cmd" in
setup)
	# Version-Gate: moderner Host-Interpreter -> nichts zu tun
	active="$(active_interpreter)"
	if [ -n "$active" ]; then
		if major="$(effective_major "$active")" && [ -n "$major" ] && [ "$major" -ge "$MIN_MAJOR" ]; then
			echo "binfmt: aktiver Host-Interpreter $active (qemu $major.x) ist OFD-tauglich — kein Entry nötig."
			exit 0
		fi
		echo "binfmt: Host-Interpreter $active (qemu ${major:-unbekannt}.x < $MIN_MAJOR.x) emuliert OFD nicht — registriere Container-Entry."
	else
		echo "binfmt: kein aarch64-Host-Entry registriert — registriere Container-Entry."
	fi
	require_docker || exit 1
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
	if [ ! -e "/proc/sys/fs/binfmt_misc/$ENTRY" ]; then
		echo "binfmt: kein Entry $ENTRY vorhanden"
		exit 0
	fi
	docker_ok=1
	if ! require_docker; then
		docker_ok=0
	elif ! $DOCKER run --rm --privileged pi-gen bash -c "
			mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc 2>/dev/null || true
			echo -1 > /proc/sys/fs/binfmt_misc/$ENTRY
			echo \"binfmt: $ENTRY entfernt\"
		"; then
		docker_ok=0
	fi
	if [ "$docker_ok" -ne 1 ]; then
		# Bewusst non-interaktiv: keine sudo-Passwortabfrage im Trap-Kontext —
		# stattdessen klare Handlungsanweisung (rc 1; der Wrapper-Trap
		# entschärft via || true, der Build-Exit-Code bleibt erhalten).
		echo "binfmt: $ENTRY konnte nicht per Docker entfernt werden — manuell:" >&2
		echo "  sudo bash -c 'echo -1 > /proc/sys/fs/binfmt_misc/$ENTRY'" >&2
		echo "  (oder rebooten — binfmt_misc-Einträge überleben keinen Neustart)" >&2
		exit 1
	fi
	;;
*)
	echo "usage: binfmt.sh setup|cleanup" >&2
	exit 1
	;;
esac
