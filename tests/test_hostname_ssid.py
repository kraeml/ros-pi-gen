"""First-Boot-SSID-Logik (AccessPopup.md §8.6): hostname-ssid.sh aus dem Overlay
wird in einem arm64-Container (debian:trixie) mit stub-Hosnamen ausgeführt und
das Ergebnis in /etc/accesspopup.conf geprüft – unabhängig vom gebauten Image."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from helpers import container

FILES_DIR = Path(__file__).resolve().parent.parent / "stage2" / "07-accesspopup" / "files"

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

CASES = [
    ("roboter-07", "roboter-07-AP"),
    ("ROBOTER-07", "roboter-07-AP"),
    ("Röboter-ß", "roeboter-ss-AP"),
    ("r" * 40, "r" * 29 + "-AP"),
    ("###", "Roboter-AP"),
]


def _run_case(host: str) -> str:
    script = SCRIPT.format(host=host)
    proc = subprocess.run(
        [
            "docker", "run", "--rm", "-i", "--platform", "linux/arm64",
            "-v", f"{FILES_DIR}:/src:ro", "debian:trixie", "bash", "-s",
        ],
        input=script, capture_output=True, text=True, timeout=300,
    )
    return proc.stdout, proc.stderr, proc.returncode


@pytest.mark.parametrize("host,expected", CASES, ids=lambda v: v if len(v) < 40 else "truncate")
def test_hostname_ssid(host, expected):
    if not container.docker_available():
        pytest.skip("Docker nicht verfuegbar.")
    stdout, stderr, rc = _run_case(host)
    assert rc == 0, f"rc={rc}\nstderr:\n{stderr}"
    line = stdout.strip()
    assert line == f"ap_ssid='{expected}'", f"host={host!r}: {line!r}"
