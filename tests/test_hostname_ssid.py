"""First-Boot-SSID-Logik (AccessPopup.md §8.6): hostname-ssid.sh aus dem Overlay
wird in einem arm64-Container (debian:trixie) mit stub-Hosnamen ausgeführt und
das Ergebnis in /etc/accesspopup.conf geprüft – unabhängig vom gebauten Image.
Ein zweiter Testfall prüft den Hostnamenwechsel (NM-Dispatcher-Event 'hostname'):
die SSID muss aus dem NEUEN Hostnamen neu berechnet werden."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from helpers import container

FILES_DIR = (
    Path(__file__).resolve().parent.parent / "stage-custom" / "07-accesspopup" / "files"
)

SCRIPT = """set -e
cp /src/accesspopup.conf /etc/accesspopup.conf
mkdir -p /tmp/stub
cat > /tmp/host.txt <<'HOSTEOF'
{host}
HOSTEOF
cat > /tmp/stub/hostname <<'STUBEOF'
#!/bin/sh
cat /tmp/host.txt
STUBEOF
chmod +x /tmp/stub/hostname
export PATH=/tmp/stub:$PATH
/src/hostname-ssid.sh
/src/hostname-ssid.sh
grep '^ap_ssid=' /etc/accesspopup.conf
"""

# Wechsel-Fall (Dispatcher-Analogie): EIN Container, die conf aus Lauf 1
# bleibt für Lauf 2 bestehen — beweist, dass die SSID aus dem hostname-
# Befehl NEU berechnet wird statt am bestehenden ap_ssid weiterzurechnen
# (sonst würde -AP-AP oder der alte Name stehenbleiben).
WECHSEL = ("roboter-07", "roboter-08")

CASES = [
    ("roboter-07", "roboter-07-AP"),
    ("ROBOTER-07", "roboter-07-AP"),
    # 802.11: SSID max. 32 Bytes inkl. Suffix (Skript: max = 32 - len("-AP"))
    # → 40 Zeichen Eingabe werden auf 29 + "-AP" = 32 gekürzt.
    ("r" * 40, "r" * 29 + "-AP"),
    # Fallback bei vollständig nicht-SSID-tauglichem Hostnamen: Konstante
    # FALLBACK="Roboter" im Skript (Projekt-Default, siehe AccessPopup.md-
    # Defaults / TODO Block 2).
    ("###", "Roboter-AP"),
]


# Wechsel-Template: EIN Container, conf bleibt zwischen den Läufen bestehen —
# Lauf 2 erbt ap_ssid aus Lauf 1 (echter -AP-AP-Detektor, siehe Test unten).
SCRIPT_WECHSEL = """set -e
cp /src/accesspopup.conf /etc/accesspopup.conf
mkdir -p /tmp/stub
cat > /tmp/stub/hostname <<'STUBEOF'
#!/bin/sh
cat /tmp/host.txt
STUBEOF
chmod +x /tmp/stub/hostname
export PATH=/tmp/stub:$PATH

echo '{host_a}' > /tmp/host.txt
/src/hostname-ssid.sh
grep '^ap_ssid=' /etc/accesspopup.conf

echo '{host_b}' > /tmp/host.txt
/src/hostname-ssid.sh
grep '^ap_ssid=' /etc/accesspopup.conf
"""


def _run_case(host: str) -> tuple[str, str, int]:
    script = SCRIPT.format(host=host)
    # Bewusst direkter subprocess statt helpers.container.run: der Lauf piped
    # das Skript per stdin (bash -s) — die Helper-Signatur (nur args, kein
    # input) deckt das nicht ab.
    proc = subprocess.run(
        [
            "docker", "run", "--rm", "-i", "--platform", "linux/arm64",
            "-v", f"{FILES_DIR}:/src:ro", "debian:trixie", "bash", "-s",
        ],
        input=script, capture_output=True, text=True, timeout=300,
    )
    return proc.stdout, proc.stderr, proc.returncode


def _run_wechsel(host_a: str, host_b: str) -> tuple[str, str, int]:
    script = SCRIPT_WECHSEL.format(host_a=host_a, host_b=host_b)
    proc = subprocess.run(
        [
            "docker", "run", "--rm", "-i", "--platform", "linux/arm64",
            "-v", f"{FILES_DIR}:/src:ro", "debian:trixie", "bash", "-s",
        ],
        input=script, capture_output=True, text=True, timeout=300,
    )
    return proc.stdout, proc.stderr, proc.returncode


def _skip_docker():
    if not container.docker_available():
        pytest.skip("Docker nicht verfuegbar.")


@pytest.mark.parametrize("host,expected", CASES, ids=lambda v: v if len(v) < 40 else "truncate")
def test_hostname_ssid(host, expected):
    # Doppellauf (zweimal /src/hostname-ssid.sh) prüft Idempotenz wasserdicht:
    # das Skript nimmt seine Eingabe AUSSCHLIESSLICH vom hostname-Befehl
    # (Skript-Zeile 'h="$(hostname …)"') und ersetzt ap_ssid per sed komplett
    # (Zeile "s/^ap_ssid=.*/…") — ein doppeltes -AP ist strukturell unmöglich.
    _skip_docker()
    stdout, stderr, rc = _run_case(host)
    assert rc == 0, f"rc={rc}\nstderr:\n{stderr}"
    line = stdout.strip()
    assert line == f"ap_ssid='{expected}'", f"host={host!r}: {line!r}"


def test_hostname_ssid_wechsel():
    # Echter -AP-AP-Detektor: EIN Container, die conf aus Lauf 1
    # (ap_ssid='roboter-07-AP') bleibt für Lauf 2 bestehen. Nimmt das
    # Skript versehentlich den bestehenden ap_ssid-Wert statt des
    # hostname-Befehls als Eingabe, hängt Lauf 2 ein zweites '-AP' an
    # oder behält den alten Namen — beides würde hier auffliegen.
    #
    # Negativprobe (2026-09-24): gemutete Skript-Kopie (h aus der bestehenden
    # ap_ssid-Zeile statt hostname, -AP nicht gestrippt) → Wechsel-Test rot
    # mit ap_ssid='apssidapssidaccesspopup-ap-AP' statt 'roboter-08-AP' —
    # bestätigt Detektor-Qualität. Änderung zurückgesetzt, nicht Teil der
    # Suite.
    _skip_docker()
    stdout, stderr, rc = _run_wechsel(*WECHSEL)
    assert rc == 0, f"rc={rc}\nstderr:\n{stderr}"

    zeilen = stdout.strip().splitlines()
    assert len(zeilen) == 2, f"Erwartet 2 Zeilen (Lauf 1 + Lauf 2), erhalten: {zeilen!r}"
    lauf1, lauf2 = zeilen
    assert lauf1 == f"ap_ssid='{WECHSEL[0]}-AP'", lauf1
    assert lauf2 == f"ap_ssid='{WECHSEL[1]}-AP'", (
        f"SSID folgt dem Hostnamenwechsel nicht (Lauf 1: {lauf1!r}, Lauf 2: {lauf2!r})"
    )
