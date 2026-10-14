from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from helpers import container

STAGE = Path(__file__).resolve().parent.parent / "stage-custom" / "10-doitpi-firstboot"
SCRIPT = STAGE / "files" / "doitpi_firstboot.sh"
UNIT = STAGE / "files" / "doitpi_firstboot.service"
DOCKER_IMAGE = "ros-pigen-tests-firstboot:local"
DOCKERFILE = Path(__file__).resolve().parent / "docker" / "firstboot" / "Dockerfile"


def _status(*, end: str | None = "2026-10-13 12:00:00", errors=None) -> dict:
    stage = {"errors": [] if errors is None else errors}
    if end is not None:
        stage["end"] = end
    return {"v1": {"init": stage}}


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


@pytest.fixture(scope="module")
def firstboot_image():
    if not container.docker_available():
        pytest.skip("Docker nicht verfuegbar.")
    if subprocess.run(
        ["docker", "image", "inspect", DOCKER_IMAGE], capture_output=True
    ).returncode:
        build = subprocess.run(
            ["docker", "build", "--platform", "linux/amd64", "--tag", DOCKER_IMAGE,
             "--file", str(DOCKERFILE), str(DOCKERFILE.parent)],
            capture_output=True, text=True, timeout=300,
        )
        assert build.returncode == 0, build.stderr
    return DOCKER_IMAGE


def _run_firstboot(
    tmp_path: Path,
    status: dict,
    image: str,
    *,
    passwd_entry: str | None = None,
    user_home: str = "/home/robot",
    primary_group: str = "robot",
    success_after_sleep: int = 0,
    ansible_rc: int = 0,
    marker_exists: bool = False,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    if passwd_entry is None:
        passwd_entry = f"robot:x:1000:1000::{user_home}:/bin/bash"

    fixture = tmp_path / "fixture"
    home_relative = Path(user_home).relative_to("/")
    for relative in (
        "stubs",
        "logs",
        "var-lib-doitpi",
        "var-log",
        "apt-conf",
        "systemd-units",
        Path("home") / home_relative.relative_to("home"),
    ):
        (fixture / relative).mkdir(parents=True, exist_ok=True)

    if marker_exists:
        (fixture / "var-lib-doitpi" / "firstboot.done").touch()

    run_dir = fixture / "run"
    cloud_init_dir = run_dir / "cloud-init"
    cloud_init_dir.mkdir(parents=True, exist_ok=True)
    status_file = cloud_init_dir / "status.json"
    status_file.write_text(json.dumps(status))
    success_file = fixture / "status-success.json"
    success_file.write_text(json.dumps(_status()))

    stub_dir = fixture / "stubs"
    _write_executable(
        stub_dir / "getent",
        '#!/bin/sh\nprintf "%s\\n" "$FIRSTBOOT_PASSWD_ENTRY"\n',
    )
    _write_executable(
        stub_dir / "id",
        '#!/bin/sh\nprintf "%s\\n" "$FIRSTBOOT_PRIMARY_GROUP"\n',
    )
    _write_executable(stub_dir / "ansible", "#!/bin/sh\nexit \"${FIRSTBOOT_ANSIBLE_RC:-0}\"\n")
    _write_executable(
        stub_dir / "systemctl",
        '#!/bin/sh\nprintf "%s\\n" "$*" >> /test/logs/systemctl\nexit 0\n',
    )
    _write_executable(
        stub_dir / "sleep",
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> /test/logs/sleep\n"
        "if [ \"${FIRSTBOOT_SUCCESS_AFTER_SLEEP:-0}\" -gt 0 ] && "
        "[ \"$(wc -l < /test/logs/sleep)\" -eq \"$FIRSTBOOT_SUCCESS_AFTER_SLEEP\" ]; then\n"
        "  cp /test/status-success.json /run/cloud-init/status.json\n"
        "fi\n",
    )
    _write_executable(
        stub_dir / "chown",
        '#!/bin/sh\nprintf "%s\\n" "$*" >> /test/logs/chown\n',
    )
    _write_executable(stub_dir / "sync", "#!/bin/sh\nexit 0\n")

    volumes = [
        (SCRIPT, "/src/doitpi_firstboot.sh", "ro"),
        (fixture, "/test", "rw"),
        (cloud_init_dir, "/run/cloud-init", "rw"),
        (fixture / "var-lib-doitpi", "/var/lib/doitpi", "rw"),
        (fixture / "var-log", "/var/log", "rw"),
        (fixture / "apt-conf", "/etc/apt/apt.conf.d", "rw"),
        (fixture / "systemd-units", "/etc/systemd/system", "rw"),
        (fixture / home_relative, user_home, "rw"),
    ]
    command = ["docker", "run", "--rm", "--platform", "linux/amd64"]
    for source, target, mode in volumes:
        command.extend(["--volume", f"{source}:{target}:{mode}"])
    command.extend(
        [
            "--entrypoint",
            "/bin/sh",
            "--env",
            f"FIRSTBOOT_PASSWD_ENTRY={passwd_entry}",
            "--env",
            f"FIRSTBOOT_PRIMARY_GROUP={primary_group}",
            "--env",
            f"FIRSTBOOT_SUCCESS_AFTER_SLEEP={success_after_sleep}",
            "--env",
            f"FIRSTBOOT_ANSIBLE_RC={ansible_rc}",
            image,
            "-c",
            "PATH=/test/stubs:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin exec bash /src/doitpi_firstboot.sh",
            "bash",
            "/src/doitpi_firstboot.sh",
        ]
    )
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    return result, fixture


def test_firstboot_stage_installs_script_and_unit():
    installer = (STAGE / "01-run.sh").read_text()
    assert os.access(STAGE / "01-run.sh", os.X_OK)
    assert 'install -m 755 files/doitpi_firstboot.sh' in installer
    assert 'install -m 644 files/doitpi_firstboot.service' in installer
    assert "systemctl enable doitpi_firstboot.service" in installer


def test_firstboot_unit_orders_cloudinit_and_guards_marker():
    unit = UNIT.read_text()
    assert "Wants=cloud-init-network.service" in unit
    assert "After=cloud-init-network.service" in unit
    assert "ConditionPathExists=!/var/lib/doitpi/firstboot.done" in unit
    assert "ExecStart=/usr/local/sbin/doitpi_firstboot.sh" in unit
    assert "TimeoutStartSec=300" in unit


def test_firstboot_cloudinit_success_on_first_check(tmp_path, firstboot_image):
    result, fixture = _run_firstboot(tmp_path, _status(), firstboot_image)
    assert result.returncode == 0, result.stderr
    assert (fixture / "var-lib-doitpi" / "firstboot.done").is_file()
    assert not (fixture / "logs" / "sleep").exists()


def test_firstboot_cloudinit_delayed_success_uses_real_parser(tmp_path, firstboot_image):
    result, fixture = _run_firstboot(
        tmp_path, _status(end=None), firstboot_image, success_after_sleep=2
    )
    assert result.returncode == 0, result.stderr
    assert json.loads((fixture / "run" / "cloud-init" / "status.json").read_text()) == _status()
    assert (fixture / "logs" / "sleep").read_text().splitlines() == ["2", "2"]
    assert (fixture / "var-lib-doitpi" / "firstboot.done").is_file()


@pytest.mark.parametrize(
    "status",
    [
        _status(end=None),
        _status(errors=["cloud-init module failed"]),
        {"v1": {"init": []}},
    ],
    ids=["unfinished", "errors", "unexpected-structure"],
)
def test_firstboot_cloudinit_failure_does_not_mark_done(tmp_path, status, firstboot_image):
    result, fixture = _run_firstboot(tmp_path, status, firstboot_image)
    assert result.returncode != 0
    assert not (fixture / "var-lib-doitpi" / "firstboot.done").exists()
    assert not (fixture / "logs" / "systemctl").exists()


def test_firstboot_cloudinit_timeout_checks_all_sixty_times(tmp_path, firstboot_image):
    result, fixture = _run_firstboot(tmp_path, _status(end=None), firstboot_image)
    assert result.returncode != 0
    assert len((fixture / "logs" / "sleep").read_text().splitlines()) == 60
    assert not (fixture / "var-lib-doitpi" / "firstboot.done").exists()


def test_firstboot_existing_marker_exits_without_other_actions(tmp_path, firstboot_image):
    result, fixture = _run_firstboot(tmp_path, {}, firstboot_image, marker_exists=True)
    assert result.returncode == 0, result.stderr
    assert not (fixture / "logs" / "systemctl").exists()
    assert not (fixture / "logs" / "sleep").exists()


def test_firstboot_missing_uid_1000_user_does_not_mark_done(tmp_path, firstboot_image):
    result, fixture = _run_firstboot(tmp_path, _status(), firstboot_image, passwd_entry="")
    assert result.returncode != 0
    assert not (fixture / "var-lib-doitpi" / "firstboot.done").exists()


def test_firstboot_replaces_paths_without_prefix_collisions(tmp_path, firstboot_image):
    home = "/home/robot"
    units = tmp_path / "fixture" / "systemd-units"
    units.mkdir(parents=True)
    (units / "nodered.service.d").mkdir()
    (units / "nodered.service.d" / "override.conf").write_text(
        "[Service]\nUser=pi\nGroup=pi\nWorkingDirectory=/home/pi\n"
        "Environment=OTHER=/home/pi-extra\n"
    )
    home_file = tmp_path / "fixture" / "home" / "robot" / "setup.txt"
    home_file.parent.mkdir(parents=True)
    home_file.write_text(
        "venv=/home/pi/platformio-env\n"
        "extra=/home/pi-extra/path\n"
        "quoted_single='/home/pi'\n"
        "quoted_single_child='/home/pi/x'\n"
        'quoted_double="/home/pi"\n'
        "child_slash=/home/pi/x/\n"
        "at_eol=/home/pi\n"
        "adjacent=/home/pi:/home/pi\n"
        "other=/home/pilot\n"
        "pixel=/home/pixel\n"
        "backup=/home/pi.bak\n"
        "escape=/home/pi\\n\n"
        "escaped_space=/home/pi\\ extra\n"
    )

    result, fixture = _run_firstboot(
        tmp_path, _status(), firstboot_image, user_home=home, primary_group="robot-group"
    )
    assert result.returncode == 0, result.stderr
    unit_text = (units / "nodered.service.d" / "override.conf").read_text()
    assert "User=robot" in unit_text
    assert "Group=robot-group" in unit_text
    assert "WorkingDirectory=/home/robot" in unit_text
    assert "OTHER=/home/pi-extra" in unit_text
    home_text = home_file.read_text()
    assert "venv=/home/robot/platformio-env" in home_text, (
        f"{result.stdout}\nhome-content={home_text!r}"
    )
    assert "extra=/home/pi-extra/path" in home_text
    assert "quoted_single='/home/robot'" in home_text
    assert "quoted_single_child='/home/robot/x'" in home_text
    assert 'quoted_double="/home/robot"' in home_text
    assert "child_slash=/home/robot/x/" in home_text
    assert "at_eol=/home/robot" in home_text
    assert "adjacent=/home/robot:/home/robot" in home_text
    assert "other=/home/pilot" in home_text
    assert "pixel=/home/pixel" in home_text
    assert "backup=/home/pi.bak" in home_text
    assert "escape=/home/pi\\n" in home_text
    assert "escaped_space=/home/pi\\ extra" in home_text
    assert (fixture / "logs" / "chown").is_file()
    systemctl_calls = (fixture / "logs" / "systemctl").read_text()
    assert "enable code-server@robot.service" in systemctl_calls
    assert "reboot" in systemctl_calls


def test_firstboot_replacement_escapes_ampersand_in_home_path(tmp_path, firstboot_image):
    home = "/home/robot&lab"
    home_file = tmp_path / "fixture" / "home" / "robot&lab" / "setup.txt"
    home_file.parent.mkdir(parents=True)
    home_file.write_text("venv=/home/pi/platformio-env\nother=/home/pi-extra\n")

    result, _ = _run_firstboot(tmp_path, _status(), firstboot_image, user_home=home)
    assert result.returncode == 0, result.stderr
    assert home_file.read_text() == (
        "venv=/home/robot&lab/platformio-env\nother=/home/pi-extra\n"
    )


def test_firstboot_ansible_warning_does_not_prevent_completion(tmp_path, firstboot_image):
    result, fixture = _run_firstboot(tmp_path, _status(), firstboot_image, ansible_rc=1)
    assert result.returncode == 0, result.stderr
    assert "Ansible-Test (ping) fehlgeschlagen" in result.stdout
    assert (fixture / "var-lib-doitpi" / "firstboot.done").is_file()
