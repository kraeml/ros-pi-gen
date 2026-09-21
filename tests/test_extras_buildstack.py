"""Ergaenzende Smoke-Checks (TODO Block 3, pi-gen-Basis): Docker/Ansible im
Image, docker.service enabled, cloud-init ohne Fehler. Keine Protokoll-IDs –
Unterstuetzung fuer die pi-gen-Abnahme."""

from __future__ import annotations


def test_extras_docker_ce_inst(crun):
    for pkg in ("docker-ce", "docker-ce-cli", "containerd.io"):
        res = crun(["dpkg-query", "-W", "-f=${Status} ${Version}\n", pkg])
        assert res.rc == 0 and "install ok installed" in res.stdout, res.summary()


def test_extras_ansible_inst(crun):
    for pkg in ("ansible", "ansible-core"):
        res = crun(["dpkg-query", "-W", "-f=${Status} ${Version}\n", pkg])
        assert res.rc == 0 and "install ok installed" in res.stdout, res.summary()


def test_extras_docker_service_enabled(crun):
    res = crun(["systemctl", "is-enabled", "docker.service"])
    assert res.rc == 0 and res.stdout.strip() == "enabled", res.summary()


def test_extras_cloud_init_nicht_defekt(crun):
    res = crun(["systemctl", "is-active", "cloud-init.service"])
    assert res.stdout.strip() != "failed", res.summary()
