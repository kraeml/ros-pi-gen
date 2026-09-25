"""Gruppe Q – Smoke-Tests Q2 bis Q9 gegen das gebaute Image.

Q1 (Boot) liegt in test_q1_boot.py. Laeuft weitgehend in einem arm64-Container
des echten RootFS (binfmt/qemu-user), damit die echten Tools (systemctl, visudo,
nft) geprueft werden; Rechte/Inhalte kommen zusaetzlich direkt per debugfs aus
dem Image (Q5/Q7).
"""

from __future__ import annotations

import re
import subprocess

import pytest

from helpers import imageio

CONF_PATH = "/etc/accesspopup.conf"
DISPATCHER_PATH = "/etc/NetworkManager/dispatcher.d/90-accesspopup-portal"
NFT_RULES_PATH = "/etc/nftables.d/accesspopup.rules"
SUDOERS_PATH = "/etc/sudoers.d/acpu"
AP_PW = "Pi-WLAN-Setup-2026"


def _fail(res) -> str:
    return res.summary()


def test_q2_accesspopup_timer_enabled(crun, pack):
    if not imageio.debugfs_exists(pack.root_img, "/etc/systemd/system/AccessPopup.timer"):
        pytest.fail("AccessPopup.timer fehlt im Image (07-accesspopup nicht installiert?)")
    res = crun(["systemctl", "is-enabled", "AccessPopup.timer"])
    assert res.rc == 0 and res.stdout.strip() == "enabled", _fail(res)


def test_q3_hostname_ssid_enabled(crun, pack):
    if not imageio.debugfs_exists(pack.root_img, "/etc/systemd/system/hostname-ssid.service"):
        pytest.fail(
            "hostname-ssid.service fehlt im Image (07-accesspopup nicht installiert?)"
        )
    res = crun(["systemctl", "is-enabled", "hostname-ssid.service"])
    assert res.rc == 0 and res.stdout.strip() == "enabled", _fail(res)


def test_q4_web_units_disabled(crun, pack):
    for unit in ("acpu_web.service", "acpu_web_app.socket"):
        unit_path = f"/etc/systemd/system/{unit}"
        if not imageio.debugfs_exists(pack.root_img, unit_path):
            pytest.fail(f"{unit_path} fehlt im Image (07-accesspopup nicht installiert?)")
        res = crun(["systemctl", "is-enabled", unit])
        state = res.stdout.strip()
        # 'not enabled': keine Install-Sektion; 'disabled': Install-Sektion, kein
        # wants-Link. Beide = Dispatcher-Gating intakt (Q4 erwartet "nicht enabled").
        assert res.rc != 0 and state in ("disabled", "not enabled"), _fail(res)
    for wants in ("multi-user.target.wants", "sockets.target.wants", "timers.target.wants"):
        for name in imageio.debugfs_ls(pack.root_img, f"/etc/systemd/system/{wants}"):
            assert "acpu_web" not in name, (
                f"Web-Unit im wants-Verzeichnis {wants}: {name} (Dispatcher-Gating verletzt)"
            )


def test_q5_accesspopup_conf(pack):
    if not imageio.debugfs_exists(pack.root_img, CONF_PATH):
        pytest.fail(f"{CONF_PATH} fehlt im Image (07-accesspopup nicht installiert?)")
    conf = imageio.debugfs_cat(pack.root_img, CONF_PATH)
    pw = re.search(r"^ap_pw='([^']*)'", conf, re.MULTILINE)
    assert pw, f"ap_pw fehlt in {CONF_PATH}:\n{conf}"
    assert pw.group(1) == AP_PW, f"ap_pw ist {pw.group(1)!r}, erwartet {AP_PW!r}"
    assert re.search(r"^ap_ssid=", conf, re.MULTILINE), (
        f"ap_ssid-Platzhalter fehlt in {CONF_PATH}:\n{conf}"
    )
    accesspopup = imageio.debugfs_cat(pack.root_img, "/usr/local/bin/accesspopup")
    assert 'ipv4.addresses "$ap_ip"' in accesspopup
    assert 'ipv4.addr "$ap_ip"' not in accesspopup


def test_q6_nft_syntax(crun, pack):
    from helpers import container as cnt

    if not imageio.debugfs_exists(pack.root_img, NFT_RULES_PATH):
        pytest.fail(
            f"{NFT_RULES_PATH} fehlt im Image (07-accesspopup nicht installiert?)"
        )
    if not cnt.docker_available():
        pytest.skip("Docker nicht verfuegbar.")
    rules_file = pack.cache / "nft-check" / "accesspopup.rules"
    rules_file.parent.mkdir(parents=True, exist_ok=True)
    rules_file.write_text(imageio.debugfs_cat(pack.root_img, NFT_RULES_PATH))
    cnt.ensure_nft_helper(pack.cache)
    # --network host: der Docker-Netns dieser Kernel-Version bietet kein
    # NETLINK_NETFILTER; im Host-Netns funktioniert der nft-Dry-Run nativ
    # (amd64). '-c' prueft nur, es wird nichts angewendet.
    proc = subprocess.run(
        ["docker", "run", "--rm", "--privileged", "--network", "host",
         "-v", f"{rules_file}:/rules/accesspopup.rules:ro",
         cnt.NFT_HELPER_TAG, "nft", "-c", "-f", "/rules/accesspopup.rules"],
        capture_output=True, text=True, errors="replace", timeout=300,
    )
    if proc.returncode != 0 and "Protocol not supported" in proc.stderr:
        pytest.skip(
            "NETLINK_NETFILTER im Host-Kernel-Netns nicht verfuegbar "
            "(nfnetlink/nf_tables geladen?) - Q6 kann nicht geprueft werden."
        )
    assert proc.returncode == 0, (
        f"nft -c rc={proc.returncode}\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )


def test_q7_dispatcher_rechte(pack):
    if not imageio.debugfs_exists(pack.root_img, DISPATCHER_PATH):
        pytest.fail(
            f"{DISPATCHER_PATH} fehlt im Image (07-accesspopup nicht installiert?)"
        )
    st = imageio.debugfs_stat(pack.root_img, DISPATCHER_PATH)
    assert st["type"] != "symlink", f"{DISPATCHER_PATH} ist ein Symlink"
    assert st["mode"] == 0o755, f"Mode ist {oct(st['mode'])}, erwartet 0o755"
    assert st["uid"] == 0 and st["gid"] == 0, (
        f"Besitzer ist {st['uid']}:{st['gid']}, erwartet 0:0"
    )


def test_q8_visudo(crun, pack, build_log_text):
    if not imageio.debugfs_exists(pack.root_img, SUDOERS_PATH):
        pytest.fail(f"{SUDOERS_PATH} fehlt im Image (07-accesspopup nicht installiert?)")
    res = crun(["visudo", "-cf", SUDOERS_PATH])
    assert res.rc == 0 and "parsed OK" in res.stdout, _fail(res)
    assert "parsed OK" in build_log_text and SUDOERS_PATH in build_log_text, (
        "visudo-Ergebnis nicht im Build-Log belegbar (Q8 erwartet 'OK (im Build-Log)')"
    )


def test_q9_nm_dispatcher_unit(crun):
    res = crun(["systemctl", "is-enabled", "NetworkManager-dispatcher"])
    state = res.stdout.strip()
    assert res.rc == 0, _fail(res)
    assert state in ("enabled", "enabled-runtime", "static", "indirect"), (
        f"NetworkManager-dispatcher ist {state!r}; erwartet aktivierbare Unit"
    )
