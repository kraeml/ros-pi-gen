#!/usr/bin/env bash
# Q1a-Versions-Probe: systemd-Container-Boot (Q1a) unter einem GEBENEN
# qemu-aarch64-Interpreter fahren — empirische Versionsmatrix für MIN_MAJOR
# im binfmt.sh-Version-Gate (statt der 8er-Annahme).
#
# Ablauf pro Probe:
#   1. Probe-Binary als temporären binfmt-Interpreter registrieren (F-Flag;
#      Binary wird per Bind-Mount in den pi-gen-Container gehängt — der
#      Kernel hält den FD offen, kein Host-root nötig)
#   2. Q1a (test_q1_boot.py) mit PIGEN_TEST_NO_BINFMT=1 fahren (das Session-
#      Fixture überschreibt unseren Entry sonst mit dem Container-Entry)
#      und PIGEN_TEST_BOOT_TIMEOUT=300 (Wedges bounden statt 15-min-Timeout)
#   3. Ergebnis klassifizieren (PASS / WEDGE / FAIL) + Log-Tail
#   4. Entry entfernen
#
# Der VORGEDRUCKTE Interpreter (/usr/bin/qemu-aarch64) in der Registrierung
# wird durch die Probe-Binary ersetzt (Bind-Mount-Ziel).
#
# usage: q1a-probe.sh <qemu-aarch64-binary> [label]
# Reihenfolge-Empfehlung: 4.2.1 (Negativkontrolle — muss scheitern) →
# 6.2 (jammy) → 8.2.2 → 10.0.13 (pi-gen-Container, Positivkontrolle).
set -uo pipefail

BOOT_TIMEOUT=300
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ $# -ge 1 ] || { echo "usage: q1a-probe.sh <qemu-binary> [label]" >&2; exit 2; }
QEMU_BIN="$(readlink -f "$1")"
LABEL="${2:-$(basename "$QEMU_BIN")}"

[ -x "$QEMU_BIN" ] || { echo "q1a-probe: $QEMU_BIN nicht ausführbar" >&2; exit 2; }

# Probe-Binary muss ins pi-gen-Image bind-mount-bar sein (absoluter Pfad)
docker image inspect pi-gen >/dev/null 2>&1 || {
	echo "q1a-probe: pi-gen-Image fehlt (make build legt es an)" >&2
	exit 2
}

ver="$("$QEMU_BIN" --version 2>/dev/null | head -1)" || ver=""
echo "════ q1a-probe [$LABEL] — $ver ════"

# 1) Probe-Entry registrieren (F-Flag; Kernel hält den FD des Probe-Binary)
docker run --rm --privileged \
	-v "$QEMU_BIN":/probe/qemu-aarch64:ro \
	pi-gen bash -c '
		set -e
		mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc 2>/dev/null || true
		[ -e /proc/sys/fs/binfmt_misc/qemu-aarch64-rpi ] && echo -1 > /proc/sys/fs/binfmt_misc/qemu-aarch64-rpi || true
		printf "%s" ":qemu-aarch64-rpi:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:/probe/qemu-aarch64:F" > /proc/sys/fs/binfmt_misc/register
		grep -q enabled /proc/sys/fs/binfmt_misc/qemu-aarch64-rpi
		echo "probe-entry registriert (F-Flag → /probe/qemu-aarch64)"
'

# 2) Q1a fahren (NO_BINFMT=1 → Fixture rührt unseren Entry nicht)
rc=0
cd "$REPO_ROOT" || exit 1
PIGEN_TEST_NO_BINFMT=1 PIGEN_TEST_BOOT_TIMEOUT=$BOOT_TIMEOUT \
	bash -c 'tests/run_tests.sh -k q1a -q' 2>&1 | tee /tmp/q1a-probe-last.log || rc=$?

# 3) Klassifikation
verdict="FAIL"
if grep -q "1 passed" /tmp/q1a-probe-last.log; then
	verdict="PASS"
elif grep -qE "Boot nicht abgeschlossen|exec-haengend|haengend" /tmp/q1a-probe-last.log; then
	verdict="WEDGE"
elif grep -q "passwd lock" /tmp/q1a-probe-last.log; then
	verdict="FAIL-OFD"
fi
echo "════ Ergebnis [$LABEL]: $verdict (rc=$rc) ════"
grep -A6 "Boot nicht abgeschlossen\|Beobachtung" /tmp/q1a-probe-last.log | head -10 || true

# 4) Entry entfernen
docker run --rm --privileged pi-gen bash -c '
	mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc 2>/dev/null || true
	[ -e /proc/sys/fs/binfmt_misc/qemu-aarch64-rpi ] && echo -1 > /proc/sys/fs/binfmt_misc/qemu-aarch64-rpi && echo "probe-entry entfernt" || true
'

exit 0
