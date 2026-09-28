"""Overlay-Guard: prueft die Stage-Dateien direkt im Overlay-Repo (ohne Image).
Fängt Fehler ab, die sonst erst im Build-Log sichtbar wären – z. B. das
fehlende Exec-Bit an NN-run.sh (pi-gen skippt die Stage dann stillschweigend).
Bewusst nur statische Struktur-/Permissions-Checks; tiefere Skript-Prüfung
(shellcheck) läuft separat via make lint.
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


def test_overlay_user_data_stage_installs_seed():
    stage = STAGE_CUSTOM / "04-user-data"
    run = stage / "01-run.sh"
    seed = stage / "files" / "user-data"
    assert run.is_file(), "04-user-data/01-run.sh fehlt"
    assert os.access(run, os.X_OK), "04-user-data/01-run.sh ohne Exec-Bit"
    assert seed.is_file(), "04-user-data/files/user-data fehlt"
    assert '"${ROOTFS_DIR}/boot/firmware/user-data"' in run.read_text()
    assert stage.name < "05-docker-ansible"
    text = seed.read_text()
    assert "users:" in text
    assert "- default" not in text
    assert "- name: robot" in text
    assert "plain_text_passwd: robot" in text
    assert "docker" in text
    assert text.count("ssh_authorized_keys:") == 1
    assert text.count("      - \"ecdsa-sha2-nistp384 ") == 1
    assert text.count("      - \"ssh-rsa ") == 1
    assert "lock_passwd: false" in text
    assert "ssh_pwauth: true" in text
    assert "network:" not in text


def test_overlay_accesspopup_allows_ssh_from_ap():
    rules = STAGE_CUSTOM / "07-accesspopup" / "files" / "nft-accesspopup.rules"
    text = rules.read_text()
    assert 'iifname "wlan0" ip saddr 192.168.50.0/24 tcp dport 22 accept' in text
    assert 'iifname "wlan0" drop comment "AP: kein Docker/ROS/lokale Dienste"' in text


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
    h = {l.strip() for l in headless.read_text().splitlines() if l.strip() and not l.strip().startswith("#")}
    d = {l.strip() for l in desktop.read_text().splitlines() if l.strip() and not l.strip().startswith("#")}
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
    aktiv = [
        l.strip()
        for l in prerun.read_text().splitlines()
        if l.strip() and not l.strip().startswith("#") and "copy_previous" in l
    ]
    assert aktiv, (
        "stage-custom/prerun.sh ohne aktiven copy_previous-Aufruf "
        "(nur auskommentiert?) — stage-custom baute auf leerem RootFS."
    )


def test_overlay_accesspopup_files_komplett():
    files = STAGE_CUSTOM / "07-accesspopup" / "files"
    erwartet = [
        "accesspopup", "accesspopup.conf", "AccessPopup.service", "AccessPopup.timer",
        "AccessPopup.service.d/order.conf", "hostname-ssid.service", "hostname-ssid.sh",
        "dispatcher-90-accesspopup-portal", "dnsmasq-shared.d/01-wildcard.conf",
        "nft-accesspopup.rules", "acpu_web.service", "acpu_web_app.service",
        "acpu_web_app.socket", "VENDORED.md", "LICENSE",
        "accesspopup-connect-request", "accesspopup-connect-worker",
        "acpu_web/acpu_get_std.py", "acpu_web/requirements.txt", "acpu_web/pages/app.py",
        "acpu_web/pages/static/css/style.css",
        "acpu_web/pages/static/img/change_accesspopup_details.png",
        "acpu_web/pages/static/img/guide_home_img_buttons.png",
        "acpu_web/pages/static/img/no_internet_warning.png",
        "acpu_web/pages/templates/add_network.html",
        "acpu_web/pages/templates/add_network_pw.html",
        "acpu_web/pages/templates/add_nw_manual.html",
        "acpu_web/pages/templates/add_network_result.html",
        "acpu_web/pages/templates/ap_delete_confirm.html",
        "acpu_web/pages/templates/ap_edit_details.html",
        "acpu_web/pages/templates/ap_edit.html",
        "acpu_web/pages/templates/component/footer.html",
        "acpu_web/pages/templates/component/header.html",
        "acpu_web/pages/templates/component/menu.html",
        "acpu_web/pages/templates/core.html",
        "acpu_web/pages/templates/guide.html",
        "acpu_web/pages/templates/index.html",
        "acpu_web/pages/templates/nw_edit_details.html",
    ]
    fehlt = [f for f in erwartet if not (files / f).is_file()]
    assert not fehlt, f"AccessPopup-Dateien fehlen im Overlay: {fehlt}"
