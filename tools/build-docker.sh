#!/usr/bin/env bash
# Docker-Build-Orchestrierung: qemu-Entry setzen -> bauen -> Entry immer
# aufräumen. Der trap (EXIT|INT|TERM) schließt Ctrl+C/SIGINT ein — nur
# SIGKILL bleibt unbeherrscht (Selbstheilung: der nächste binfmt-setup
# deregistert Alt-Einträge zuerst; manuell: tools/binfmt.sh cleanup).
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

"$BINFMT" setup
# || true: der Exit-Status des Skripts wäre sonst der des letzten Trap-
# Befehls — ein fehlgeschlagenes Cleanup würde den Build-Exit-Code
# maskieren (cleanup meldet seinen Fehlschlag selbst auf stderr).
trap '"$BINFMT" cleanup || true' EXIT INT TERM

rc=0
cd "$REPO_ROOT" || exit 1
CONTINUE="${CONTINUE:-0}" \
PRESERVE_CONTAINER="${PRESERVE_CONTAINER:-0}" \
PIGEN_DOCKER_OPTS="${PIGEN_DOCKER_OPTS:-}" \
  "$REPO_ROOT/pi-gen/build-docker.sh" -c "$REPO_ROOT/config" || rc=$?

exit "$rc"
