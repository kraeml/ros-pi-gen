"""Overlay-Guard: prueft die Stage-Dateien direkt im Overlay-Repo (ohne Image).
Fängt Fehler ab, die sonst erst im Build-Log sichtbar wären – z. B. das
fehlende Exec-Bit an NN-run.sh (pi-gen skippt die Stage dann stillschweigend).
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGE_CUSTOM = REPO_ROOT / "stage-custom"
VARIANT_STAGES = ("06-variant-headless", "06-variant-desktop")


def _sub_stages() -> list[Path]:
    return sorted(p for p in STAGE_CUSTOM.iterdir() if p.is_dir())


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
    files = STAGE_CUSTOM / "07-accesspopup" / "files"
    skripte = ["accesspopup", "hostname-ssid.sh", "dispatcher-90-accesspopup-portal"]
    broken = [s for s in skripte if not os.access(files / s, os.X_OK)]
    assert not broken, f"Skripte ohne Exec-Bit: {broken} (chmod +x in Overlay + pi-gen-Kopie)"


def test_overlay_00_packages_vorhanden():
    fehlend = []
    for stage in _sub_stages():
        if not (stage / "00-packages").is_file():
            fehlend.append(str((stage / "00-packages").relative_to(REPO_ROOT)))
    assert not fehlend, f"Sub-Stages ohne 00-packages: {fehlend}"


def test_overlay_varianten_konsistent():
    """Varianten-Split: beide 06-variant-*-Stages mit 00-packages vorhanden,
    headless-Paketliste ist echte Teilmenge der Desktop-Liste (gleiche Basis,
    Desktop ergänzt nur)."""
    headless = STAGE_CUSTOM / "06-variant-headless" / "00-packages"
    desktop = STAGE_CUSTOM / "06-variant-desktop" / "00-packages"
    fehlen = [str(p.relative_to(REPO_ROOT)) for p in (headless, desktop) if not p.is_file()]
    assert not fehlen, f"Varianten-Stages unvollständig: {fehlen}"
    h = {l for l in headless.read_text().splitlines() if l and not l.startswith("#")}
    d = {l for l in desktop.read_text().splitlines() if l and not l.startswith("#")}
    assert h <= d, (
        f"headless-Pakete fehlen in der Desktop-Liste: {sorted(h - d)} "
        "(Varianten driften auseinander)"
    )


def test_overlay_export_image_vorhanden():
    """stage-custom exportiert das Image (Skip-Images liegt stattdessen in
    pi-gen/stage2, gesetzt von make setup)."""
    export = STAGE_CUSTOM / "EXPORT_IMAGE"
    assert export.is_file(), "stage-custom/EXPORT_IMAGE fehlt — es würde kein Image exportiert."
    assert 'IMG_SUFFIX="-lite"' in export.read_text(), (
        "EXPORT_IMAGE ohne -lite-Suffix (Imagenamen-Konvention geändert?)"
    )


def test_overlay_prerun_copy_previous():
    prerun = STAGE_CUSTOM / "prerun.sh"
    assert prerun.is_file(), "stage-custom/prerun.sh fehlt — stage-custom erhält kein stage2-RootFS."
    assert os.access(prerun, os.X_OK), "stage-custom/prerun.sh ohne Exec-Bit (pi-gen skippt sie still)."
    assert "copy_previous" in prerun.read_text(), (
        "stage-custom/prerun.sh ohne copy_previous — stage-custom baute auf leerem RootFS."
    )


def test_overlay_accesspopup_files_komplett():
    files = STAGE_CUSTOM / "07-accesspopup" / "files"
    erwartet = [
        "accesspopup", "accesspopup.conf", "AccessPopup.service", "AccessPopup.timer",
        "AccessPopup.service.d/order.conf", "hostname-ssid.service", "hostname-ssid.sh",
        "dispatcher-90-accesspopup-portal", "dnsmasq-shared.d/01-wildcard.conf",
        "nft-accesspopup.rules", "acpu_web.service", "acpu_web_app.service",
        "acpu_web_app.socket", "VENDORED.md",
    ]
    fehlt = [f for f in erwartet if not (files / f).is_file()]
    assert not fehlt, f"AccessPopup-Dateien fehlen im Overlay: {fehlt}"
