#!/usr/bin/env bash
# Docker-Build-Orchestrierung: pi-gen-Image sicherstellen -> qemu-Entry
# setzen -> bauen -> Entry immer aufräumen. Der trap (EXIT|INT|TERM)
# schließt Ctrl+C/SIGINT ein — nur SIGKILL bleibt unbeherrscht
# (Selbstheilung: der nächste binfmt-setup deregistert Alt-Einträge
# zuerst; manuell: tools/binfmt.sh cleanup).
#
# Image vor Entry: die binfmt-Registrierung läuft im pi-gen-Container —
# auf einem frischen Host (kein Image, z. B. nach docker system prune)
# würde setup sonst scheitern und der Build ohne Entry starten (stummer
# OFD-Bug auf alten Hosts). Identische Build-Argumente wie in pi-gens
# build-docker.sh → dessen eigener Build ist danach Cache-Hit.
#
# binfmt_misc ist kernel-global: während des Laufs gilt der Container-
# Entry für den gesamten Host (F-Flag hält den Interpreter-FD offen, auch
# über Container-Ende hinaus) — cleanup danach ist Pflicht.
#
# Umgebung (von make übergeben): CONTINUE, PRESERVE_CONTAINER,
# PIGEN_DOCKER_OPTS.
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BINFMT="$REPO_ROOT/tools/binfmt.sh"

# pi-gen-Image sicherstellen (identische Argumente wie pi-gen build-docker.sh)
docker image inspect pi-gen >/dev/null 2>&1 || \
	docker build --build-arg BASE_IMAGE=docker.io/debian:trixie -t pi-gen "$REPO_ROOT/pi-gen"

"$BINFMT" setup
# || true: der Exit-Status des Skripts wäre sonst der des letzten Trap-
# Befehls — ein fehlgeschlagenes Cleanup würde den Build-Exit-Code
# maskieren (cleanup meldet seinen Fehlschlag selbst auf stderr).
trap '"$BINFMT" cleanup || true' EXIT INT TERM

# GIT_HASH: pi-gen schreibt ihn ins Image (etc/rpi-issue → *.info) und
# nimmt ${GIT_HASH:-"$(git rev-parse HEAD)"} — also den Commit des CWD.
# Der CWD hier ist der Repo-Root; ohne Export würde der Commit des
# Wrappers (c54ac3a) statt des gepinnten Submoduls (74d08a3) landen
# (Q0b). Fehlschlag (kein .git): ungesetzt lassen → pi-gen-Default.
if _pigen_hash="$(git -C "$REPO_ROOT/pi-gen" rev-parse HEAD 2>/dev/null)"; then
	export GIT_HASH="$_pigen_hash"
else
	echo "build-docker.sh: pi-gen-Commit nicht ermittelbar — .info ohne GIT_HASH" >&2
fi

rc=0
cd "$REPO_ROOT" || exit 1
CONTINUE="${CONTINUE:-0}" \
PRESERVE_CONTAINER="${PRESERVE_CONTAINER:-0}" \
PIGEN_DOCKER_OPTS="${PIGEN_DOCKER_OPTS:-}" \
  "$REPO_ROOT/pi-gen/build-docker.sh" -c "$REPO_ROOT/config" || rc=$?

exit "$rc"
