from __future__ import annotations

import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACCESSPOPUP_FILES = ROOT / "stage-custom/07-accesspopup/files"
REQUEST_HELPER = ACCESSPOPUP_FILES / "accesspopup-connect-request"
WORKER = ACCESSPOPUP_FILES / "accesspopup-connect-worker"


def load_module(path: Path, name: str):
    namespace = {"__name__": name, "__file__": str(path)}
    exec(compile(path.read_text(), str(path), "exec"), namespace)
    return namespace


def test_accesspopup_worker_creates_persistent_wifi_profile():
    worker = load_module(WORKER, "accesspopup_connect_worker_profile")
    name, content = worker["make_profile"]("Home Network", "correct horse", "12345678-1234-5678-1234-567812345678")
    assert name == "Home WiFi 12345678-1234-5678-1234-567812345678"
    assert "uuid=12345678-1234-5678-1234-567812345678" in content
    assert "ssid=Home Network" in content
    assert "psk=correct horse" in content
    assert "autoconnect=true" in content
    assert "autoconnect-priority=10" in content
    assert "method=auto" in content


def test_accesspopup_worker_escapes_keyfile_values():
    worker = load_module(WORKER, "accesspopup_connect_worker_escape")
    _, content = worker["make_profile"]("Home\\WiFi", "pass word\\key", "12345678-1234-5678-1234-567812345678")
    assert r"ssid=Home\\WiFi" in content
    assert r"psk=pass word\\key" in content


def test_accesspopup_worker_validates_wifi_lengths():
    worker = load_module(WORKER, "accesspopup_connect_worker_validation")
    assert worker["valid_credentials"]("a", "12345678")
    assert not worker["valid_credentials"]("", "12345678")
    assert not worker["valid_credentials"]("a" * 33, "12345678")
    assert not worker["valid_credentials"]("network", "short")
    assert not worker["valid_credentials"]("network", "p" * 64)


def test_accesspopup_web_setup_uses_manual_entry_without_scan():
    app_source = (ACCESSPOPUP_FILES / "acpu_web/pages/app.py").read_text()
    backend_source = (ACCESSPOPUP_FILES / "acpu_web/acpu_get_std.py").read_text()
    landing = (ACCESSPOPUP_FILES / "acpu_web/pages/templates/add_network.html").read_text()
    assert 'RedirectResponse(url="/manual_add"' in app_source
    assert 'Comms.send_out("ADSL", (ssid, password))' in app_source
    assert '"SCAN":' not in backend_source
    assert "Refreshing List" not in landing


def test_accesspopup_ap_profile_uses_explicit_address():
    accesspopup = (ACCESSPOPUP_FILES / "accesspopup").read_text()
    assert 'ipv4.addresses "$ap_ip"' in accesspopup
    assert 'ipv4.addr "$ap_ip"' not in accesspopup
    assert '"$current_ap_ip" != "$ap_ip"' in accesspopup


def test_accesspopup_connect_helpers_guard_requests_and_restore_state():
    request_helper = REQUEST_HELPER.read_text()
    worker = WORKER.read_text()
    assert '"--on-active=5s"' in request_helper
    assert '"/usr/bin/systemd-run"' in request_helper
    assert 'WORKER = "/usr/local/sbin/accesspopup-connect-worker"' in request_helper
    assert '"/usr/bin/systemctl", "stop", "AccessPopup.service"' in worker
    assert 'fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)' in worker
    assert '"/usr/bin/nmcli", "connection", "up", "uuid", profile_uuid' in worker
    assert '"/usr/bin/nmcli", "connection", "delete", "uuid", profile_uuid' in worker
    assert '"/usr/local/bin/accesspopup", "-a"' in worker
    assert '"/usr/bin/systemctl", "start", "AccessPopup.timer"' in worker
