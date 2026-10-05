from __future__ import annotations

import os
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGE = REPO_ROOT / "stage-custom" / "08-ansible-roles"
ANSIBLE_ROOT = STAGE / "files" / "pi-base-ansible"
EXPECTED_ROLES = {"robot_jupyter", "robot_codeserver", "robot_platformio"}


def test_ansible_stage_structure():
    run_script = STAGE / "01-run.sh"
    assert (STAGE / "00-packages").is_file()
    assert run_script.is_file()
    assert os.access(run_script, os.X_OK), "08-ansible-roles/01-run.sh muss ausführbar sein"
    assert (ANSIBLE_ROOT / "playbook.yml").is_file()
    assert {path.name for path in (ANSIBLE_ROOT / "roles").iterdir() if path.is_dir()} >= EXPECTED_ROLES


def test_ansible_stage_wires_build_user_and_local_playbook():
    script = (STAGE / "01-run.sh").read_text()
    assert 'CHROOT_TARGET_DIR="/home/${FIRST_USER_NAME}/pi-base-ansible"' in script
    assert 'chown --recursive "${FIRST_USER_NAME}:${FIRST_USER_NAME}"' in script
    assert '--inventory "localhost,"' in script
    assert "--connection local" in script
    assert 'robot_codeserver_user=${FIRST_USER_NAME}' in script
    assert "ansible-playbook" in script


def test_ansible_playbook_declares_expected_roles():
    playbook = yaml.safe_load((ANSIBLE_ROOT / "playbook.yml").read_text())
    assert isinstance(playbook, list) and len(playbook) == 1
    roles = {entry["role"] for entry in playbook[0]["roles"] if isinstance(entry, dict) and "role" in entry}
    assert roles == EXPECTED_ROLES


def test_ansible_role_yaml_syntax():
    yaml_files = sorted(ANSIBLE_ROOT.rglob("*.yml"))
    assert yaml_files, "Keine Ansible-YAML-Dateien gefunden"
    for path in yaml_files:
        with path.open() as stream:
            yaml.safe_load(stream)


def test_ansible_role_entrypoints_exist():
    for role in EXPECTED_ROLES:
        role_dir = ANSIBLE_ROOT / "roles" / role
        assert (role_dir / "tasks" / "main.yml").is_file(), f"{role}: tasks/main.yml fehlt"
        assert (role_dir / "defaults" / "main.yml").is_file(), f"{role}: defaults/main.yml fehlt"
    assert (ANSIBLE_ROOT / "roles/robot_jupyter/templates/jupyter.service.j2").is_file()
    assert (ANSIBLE_ROOT / "roles/robot_codeserver/handlers/main.yml").is_file()
    assert (ANSIBLE_ROOT / "roles/robot_platformio/Readme.md").is_file()
