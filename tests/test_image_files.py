"""Datei-Manifest gegen das gebaute Image (einfachste Erstellungspruefung).

Prueft per debugfs (read-only, ohne Root), ob die von den Overlay-Stages
installierten Dateien im RootFS der Root-Partition ankommen – plus
Inhalts-Marker (Schluesselzeilen) und die Dateien der Boot-Partition.
Eine parametrisierte Testfunktion pro Eintrag; fehlende Dateien fallen
einzeln mit klarem Pfad auf.
"""

from __future__ import annotations

import pytest

from helpers import imageio

# (Pfad im RootFS, Erwartung)
#   "exists"            – Datei/Verzeichnis vorhanden
#   "symlink"           – Symlink vorhanden
#   reguläre Datei + Prüfung eines Inhalts-Markers über "marker:"-Präfix
ROOTFS_MANIFEST: list[tuple[str, str]] = [
    # AccessPopup Kern
    ("/usr/local/bin/accesspopup", "marker:RaspberryConnect.com"),
    ("/etc/accesspopup.conf", "marker:ap_pw='Pi-WLAN-Setup-2026'"),
    ("/etc/systemd/system/AccessPopup.service", "marker:ExecStart=/usr/local/bin/accesspopup"),
    ("/etc/systemd/system/AccessPopup.timer", "marker:OnBootSec=0min"),
    ("/etc/systemd/system/AccessPopup.service.d/order.conf", "exists"),
    # hostname-SSID
    ("/usr/local/sbin/hostname-ssid.sh", "marker:ap_ssid="),
    ("/etc/systemd/system/hostname-ssid.service", "marker:hostname-ssid.sh"),
    # Dispatcher / dnsmasq / nftables
    ("/etc/NetworkManager/dispatcher.d/90-accesspopup-portal", "marker:AccessPopup"),
    ("/etc/NetworkManager/dnsmasq-shared.d/01-wildcard.conf", "marker:192.168.50.5"),
    ("/etc/nftables.d/accesspopup.rules", "marker:table ip accesspopup"),
    ("/etc/nftables.d/accesspopup.rules", "marker:redirect to :8052"),
    # Web-UI
    ("/etc/systemd/system/acpu_web.service", "exists"),
    ("/etc/systemd/system/acpu_web_app.service", "exists"),
    ("/etc/systemd/system/acpu_web_app.socket", "marker:ListenStream=0.0.0.0:8052"),
    ("/usr/local/bin/acpu_web/app.py", "exists"),
    ("/usr/local/bin/acpu_web/acpu_get_std.py", "exists"),
    ("/usr/local/bin/acpu_web/requirements.txt", "exists"),
    ("/usr/local/bin/acpu_web/venv/bin/python3", "symlink"),
    # sudoers + Systemuser
    ("/etc/sudoers.d/acpu", "marker:/usr/local/bin/accesspopup"),
    ("/etc/passwd", "marker:acpu:"),
    # Build-Stack (Dateipfade; Paketebene deckt test_extras_buildstack.py ab)
    ("/usr/bin/docker", "exists"),
    ("/usr/bin/dockerd", "exists"),
    ("/usr/bin/ansible", "exists"),
    ("/usr/bin/ansible-playbook", "exists"),
]

BOOT_MANIFEST: list[str] = [
    "kernel8.img",
    "bcm2710-rpi-3-b.dtb",
    "cmdline.txt",
    "config.txt",
]


@pytest.mark.parametrize("path,expectation", ROOTFS_MANIFEST, ids=lambda v: v if "/" in str(v) else "")
def test_image_rootfs_datei(pack, path, expectation):
    if expectation == "exists":
        assert imageio.debugfs_exists(pack.root_img, path), f"fehlt: {path}"
    elif expectation == "symlink":
        st = imageio.debugfs_stat(pack.root_img, path)
        assert st["type"] == "symlink", f"{path} ist kein Symlink (type={st['type']})"
    elif expectation.startswith("marker:"):
        content = imageio.debugfs_cat(pack.root_img, path)
        marker = expectation.removeprefix("marker:")
        assert marker in content, f"Inhalts-Marker fehlt in {path}: {marker!r}"
    else:
        pytest.fail(f"unbekannte Erwartung: {expectation!r}")


@pytest.mark.parametrize("name", BOOT_MANIFEST, ids=lambda v: f"boot/{v}")
def test_image_boot_datei(pack, name):
    assert (pack.boot_dir / name).is_file(), f"fehlt in Boot-Partition: {name}"
