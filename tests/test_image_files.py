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
    ("/etc/nftables.d/accesspopup.rules", 'marker:tcp dport 22 accept comment "AP: SSH zum Pi"'),
    # Web-UI
    ("/etc/systemd/system/acpu_web.service", "exists"),
    ("/etc/systemd/system/acpu_web_app.service", "exists"),
    ("/etc/systemd/system/acpu_web_app.socket", "marker:ListenStream=0.0.0.0:8052"),
    ("/usr/local/bin/acpu_web/app.py", "exists"),
    ("/usr/local/bin/acpu_web/acpu_get_std.py", "exists"),
    ("/usr/local/bin/acpu_web/requirements.txt", "exists"),
    ("/usr/local/sbin/accesspopup-connect-request", "exists"),
    ("/usr/local/sbin/accesspopup-connect-worker", "exists"),
    ("/usr/local/bin/acpu_web/pages/templates/add_network_result.html", "exists"),
    ("/usr/local/bin/acpu_web/pages/templates/add_nw_manual.html", "exists"),
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
    # Cloud-init-Templates (Imager-2.0-Voraussetzung, stage2/04-cloud-init):
    # müssen auf bootfs liegen, sonst überspringt Imager 2.0 bei
    # "Use custom" die OS-Customization komplett (filesystem entry fehlt).
    "meta-data",
    "network-config",
    "user-data",
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
        if path == "/usr/local/bin/accesspopup":
            assert 'ipv4.addresses "$ap_ip"' in content
            assert 'ipv4.addr "$ap_ip"' not in content
    else:
        pytest.fail(f"unbekannte Erwartung: {expectation!r}")


def _ansible_home(pack) -> str:
    homes = imageio.debugfs_ls(pack.root_img, "/home")
    matches = [
        f"/home/{name}/pi-base-ansible"
        for name in homes
        if imageio.debugfs_exists(pack.root_img, f"/home/{name}/pi-base-ansible/playbook.yml")
    ]
    assert len(matches) == 1, f"Erwartete genau ein pi-base-ansible-Home, gefunden: {matches}"
    return matches[0]


def test_image_ansible_roles_ausgerollt(pack):
    base = _ansible_home(pack)
    expected = [
        "playbook.yml",
        "roles/robot_jupyter/tasks/main.yml",
        "roles/robot_jupyter/defaults/main.yml",
        "roles/robot_jupyter/templates/jupyter.service.j2",
        "roles/robot_codeserver/tasks/main.yml",
        "roles/robot_codeserver/defaults/main.yml",
        "roles/robot_platformio/tasks/main.yml",
        "roles/robot_platformio/defaults/main.yml",
    ]
    missing = [f"{base}/{relative}" for relative in expected if not imageio.debugfs_exists(pack.root_img, f"{base}/{relative}")]
    assert not missing, f"Ansible-Rollen-Dateien fehlen im Image: {missing}"


def test_image_ansible_user_services_expected_config(pack):
    base = _ansible_home(pack)
    user_home = base.removesuffix("/pi-base-ansible")
    username = user_home.removeprefix("/home/")
    jupyter = imageio.debugfs_cat(pack.root_img, "/etc/systemd/system/jupyter.service")
    assert f"User={username}" in jupyter
    assert f"WorkingDirectory={user_home}" in jupyter
    assert "--ip=0.0.0.0" in jupyter
    assert "--ServerApp.token=''" in jupyter
    assert "--ServerApp.password=''" in jupyter
    assert "--ServerApp.disable_check_xsrf=True" in jupyter
    assert "WantedBy=multi-user.target" in jupyter
    assert imageio.debugfs_exists(
        pack.root_img,
        "/etc/systemd/system/multi-user.target.wants/jupyter.service",
    ), "Jupyter-Systemdienst ist nicht aktiviert"
    assert imageio.debugfs_exists(pack.root_img, f"{user_home}/jupyter-env/bin/jupyter")
    assert imageio.debugfs_exists(pack.root_img, f"{user_home}/platformio-env/bin/pio")
    assert imageio.debugfs_exists(
        pack.root_img,
        f"/etc/systemd/system/multi-user.target.wants/code-server@{username}.service",
    ), "code-server-Systemdienst ist nicht aktiviert"
    assert imageio.debugfs_exists(pack.root_img, "/etc/udev/rules.d/99-platformio-udev.rules")

    config_path = f"{user_home}/.config/code-server/config.yaml"
    config = imageio.debugfs_cat(pack.root_img, config_path)
    assert "bind-addr: 0.0.0.0:8080" in config
    assert "password: change_me" in config
    stat = imageio.debugfs_stat(pack.root_img, config_path)
    assert stat["type"] == "regular"
    assert stat["mode"] == 0o644
    passwd = imageio.debugfs_cat(pack.root_img, "/etc/passwd")
    user_records = [line.split(":") for line in passwd.splitlines() if line.startswith(f"{username}:")]
    assert len(user_records) == 1, f"Build-Benutzer {username} fehlt oder ist mehrfach vorhanden"
    assert stat["uid"] == int(user_records[0][2]), "code-server-Konfiguration gehört nicht dem Build-Benutzer"

    groups = imageio.debugfs_cat(pack.root_img, "/etc/group")
    dialout = [line.split(":") for line in groups.splitlines() if line.startswith("dialout:")]
    assert len(dialout) == 1 and username in dialout[0][3].split(","), (
        f"Build-Benutzer {username} ist nicht Mitglied von dialout"
    )


@pytest.mark.parametrize("name", BOOT_MANIFEST, ids=lambda v: f"boot/{v}")
def test_image_boot_datei(pack, name):
    assert (pack.boot_dir / name).is_file(), f"fehlt in Boot-Partition: {name}"


@pytest.mark.parametrize(
    "name,erlaubte_schluessel",
    [
        ("network-config", set()),
        # meta-data ist absichtlich NICHT leer: dsmode: local = user-data
        # vor dem Netzwerk-Start anwenden; instance_id = feste NoCloud-ID
        # (Aenderung wuerde First-Setup erneut triggern).
        ("meta-data", {"dsmode", "instance_id"}),
    ],
    ids=lambda v: f"boot/{v}",
)
def test_image_boot_cloudinit_template_inert(pack, name, erlaubte_schluessel):
    """Netzwerk-Template bleibt inert; meta-data enthaelt nur NoCloud-Werte."""
    text = (pack.boot_dir / name).read_text()
    assert text.lstrip().startswith("#"), f"{name} ist kein Kommentartemplate"
    aktiv = {
        zeile.split(":")[0].strip()
        for zeile in text.splitlines()
        if zeile.strip() and not zeile.lstrip().startswith("#")
    }
    assert aktiv <= erlaubte_schluessel, (
        f"{name} enthaelt unerwartete aktive Schluessel: {sorted(aktiv - erlaubte_schluessel)!r}"
    )


def test_image_boot_user_data_matches_build_mode(pack):
    """`boot/user-data` hat zwei gueltige, sich gegenseitig ausschliessende
    Zustaende, je nachdem ob 04-user-data/SKIP beim Build gesetzt war.
    RELEASE_BUILD=1 ist Makefile-Default (gilt lokal wie im GitHub-
    Actions-Workflow) und setzt die SKIP-Datei -> inertes Template.
    RELEASE_BUILD=0 ist ein expliziter, ausschliesslich lokaler Opt-in
    fuer den Gate-1-Schnelltest (README "Schnellstart") und laesst den
    Testbenutzer robot aktiv; dieser Modus darf nie auf GitHub laufen.

    - aktiv (Quickfix, nur bei explizitem RELEASE_BUILD=0): exakt der
      bekannte Platzhalter-Benutzer `robot` mit Testpasswort/-SSH-
      Schluesseln (Übergangsloesung, siehe README.md "Erster Benutzer")
    - inert (Release, Default): reines Kommentar-Template ohne aktive
      Zugangsdaten (von tools/package_image.py:audit_release_image vor
      jeder Veroeffentlichung zusaetzlich geprueft)

    Ein Mischzustand (z. B. nur teilweise aktive Zeilen) ist in beiden
    Faellen ein Fehler.
    """
    text = (pack.boot_dir / "user-data").read_text()
    assert text.startswith("#cloud-config\n")
    active = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    has_quickfix_markers = any("plain_text_passwd:" in line for line in active)
    if has_quickfix_markers:
        assert "- name: robot" in text
        assert "groups: [adm, audio, cdrom, dialout, docker, games, gpio, i2c, input, lpadmin, netdev, plugdev, render, spi, sudo, users, video]" in text
        assert "plain_text_passwd: robot" in text
        assert text.count("ssh_authorized_keys:") == 1
        assert text.count("      - \"ecdsa-sha2-nistp384 ") == 1
        assert text.count("      - \"ssh-rsa ") == 1
        assert "lock_passwd: false" in text
        assert "ssh_pwauth: true" in text
        assert "hostname:" not in text
        assert "network:" not in text
    else:
        assert not any("ssh_authorized_keys:" in line for line in active)
        assert not any("ssh_pwauth: true" in line for line in active)
        assert not any(line.lstrip().startswith("- name: robot") for line in active)
