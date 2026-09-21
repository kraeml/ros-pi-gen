"""Overlay-Guard: prueft die Stage-Dateien direkt im Overlay-Repo (ohne Image).
Fängt Fehler ab, die sonst erst im Build-Log sichtbar wären – z. B. das
fehlende Exec-Bit an NN-run.sh (pi-gen skippt die Stage dann stillschweigend).
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGE2 = REPO_ROOT / "stage2"


def _sub_stages() -> list[Path]:
    return sorted(p for p in STAGE2.iterdir() if p.is_dir())


def test_overlay_run_sh_executable():
    broken = [
        str(run.relative_to(REPO_ROOT))
        for stage in _sub_stages()
        for run in stage.glob("*-run.sh")
        if not os.access(run, os.X_OK)
    ]
    assert not broken, (
        f"NN-run.sh ohne Exec-Bit (pi-gen skippt diese Stages still): {broken}. "
        "Fix: chmod +x <datei> (Overlay + pi-gen-Kopie), dann Rebuild."
    )


def test_overlay_skripte_executable():
    files = STAGE2 / "07-accesspopup" / "files"
    skripte = ["accesspopup", "hostname-ssid.sh", "dispatcher-90-accesspopup-portal"]
    broken = [s for s in skripte if not os.access(files / s, os.X_OK)]
    assert not broken, f"Skripte ohne Exec-Bit: {broken} (chmod +x in Overlay + pi-gen-Kopie)"


def test_overlay_00_packages_vorhanden():
    fehlend = []
    for stage in _sub_stages():
        if not (stage / "00-packages").is_file():
            fehlend.append(str((stage / "00-packages").relative_to(REPO_ROOT)))
    assert not fehlend, f"Sub-Stages ohne 00-packages: {fehlend}"


def test_overlay_accesspopup_files_komplett():
    files = STAGE2 / "07-accesspopup" / "files"
    erwartet = [
        "accesspopup", "accesspopup.conf", "AccessPopup.service", "AccessPopup.timer",
        "AccessPopup.service.d/order.conf", "hostname-ssid.service", "hostname-ssid.sh",
        "dispatcher-90-accesspopup-portal", "dnsmasq-shared.d/01-wildcard.conf",
        "nft-accesspopup.rules", "acpu_web.service", "acpu_web_app.service",
        "acpu_web_app.socket", "VENDORED.md",
    ]
    fehlt = [f for f in erwartet if not (files / f).is_file()]
    assert not fehlt, f"AccessPopup-Dateien fehlen im Overlay: {fehlt}"
