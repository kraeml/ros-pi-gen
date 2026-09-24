"""Gruppe Q – Q1: Boot-Verhalten des Images (Container-Boot, kein QEMU).

Q1a: systemd-Boot des echten RootFS in einem privilegierten arm64-Container
(binfmt/qemu-user) – systemd erreicht 'running'/'degraded', exec-Zugang
moeglich. Staging-Anpassungen (nur Testkopie, nicht das Image):
PARTUUID-fstab-Eintraege neutralisiert (Container ohne Disks) und
systemd-binfmt maskiert (Host-binfmt-Schutz).

Grenze: unter qemu-user 6.2 schlagen systemd-Service-Spawns (clone3/cgroup)
mit 'Result: resources' fehl – ein Emulations-Artefakt, kein Image-Defekt.
Unit-Fehler inkl. ssh werden deshalb nur als Beobachtung ausgegeben; der
Beleg fuer 'Boot + SSH erreichbar' kommt vom Hardware-Lauf
(tests/tools/pi-smoke.sh, Gruppe Q am echten Pi). Ein echter
Kernel-Boot-Test in QEMU (raspi3b, qemu 6.2) wurde abgebrochen – Gruende
und Diagnose: tests/README.md, Abschnitt 'Warum kein QEMU'.
"""

from __future__ import annotations

import time

import pytest

from conftest import BOOT_TIMEOUT
from helpers import container


def _is_system_running(name: str) -> str:
    # Exec-Timeouts sind unter qemu-Emulation normal (Boot-Last) — kein
    # Abbruch, weiterpollen bis BOOT_TIMEOUT (Signature 'haengend').
    try:
        res = container.exec_cmd(name, ["systemctl", "is-system-running"], timeout=120)
    except container.DockerError:
        return "exec-haengend"
    return res.stdout.strip()


def test_q1a_container_boot(container_tag):
    name = "ros-pigen-tests-systemd"
    container.remove_container(name)
    try:
        container.start_systemd(container_tag, name)
        # Poll: 5-s-Intervall, BOOT_TIMEOUT 900 s (conftest) → bis zu 180
        # Zyklen; empirisch erreicht systemd unter qemu 8.x running/degraded
        # in ~1–3 min — das Signal ist ein Grobzustand, kein Timing-Messwert,
        # daher ist grobe Granularität ausreichend (kein per-Zyklus-Output).
        state, deadline = "", time.monotonic() + BOOT_TIMEOUT
        while time.monotonic() < deadline:
            state = _is_system_running(name)
            if state in ("running", "degraded"):
                break
            time.sleep(5)
        assert state in ("running", "degraded"), (
            f"systemd-Boot nicht abgeschlossen nach {BOOT_TIMEOUT}s "
            f"(letzter Zustand: {state!r}).\n"
            "Container-Log (Tail):\n" + container.logs(name)[-2000:]
        )
        res = container.exec_cmd(name, ["true"])
        assert res.rc == 0, res.summary()
        res = container.exec_cmd(name, ["systemctl", "is-active", "ssh"], timeout=60)
        print(f"\n[Beobachtung] ssh.service: {res.stdout.strip() or res.stderr.strip()}")
        failed = container.exec_cmd(
            name, ["systemctl", "list-units", "--state=failed", "--no-legend"], timeout=60
        )
        failed_lines = [l for l in failed.stdout.splitlines() if l.strip()]
        print(f"[Beobachtung] {len(failed_lines)} fehlgeschlagene Units:")
        print(failed.stdout.strip() or "(keine)")
    finally:
        container.remove_container(name)
