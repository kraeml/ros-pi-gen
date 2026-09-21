"""Fixtures der AccessPopup-Testinfra (Gruppe Q des Abnahmeprotokolls)."""

from __future__ import annotations

import hashlib
import os

import pytest

from helpers import container, imageio

BOOT_TIMEOUT = int(os.environ.get("PIGEN_TEST_BOOT_TIMEOUT", "900"))
DOCKER_TIMEOUT = int(os.environ.get("PIGEN_TEST_DOCKER_TIMEOUT", "300"))


def pytest_configure(config):
    if os.environ.get("PIGEN_TEST_CLEAN"):
        imageio.clean_cache()


@pytest.fixture(scope="session")
def image_path():
    try:
        return imageio.discover_image()
    except FileNotFoundError as e:
        pytest.skip(str(e))
    except imageio.ImageError as e:
        pytest.skip(str(e))


@pytest.fixture(scope="session")
def pack(image_path):
    try:
        return imageio.prepare(image_path)
    except imageio.ImageError as e:
        pytest.skip(str(e))


@pytest.fixture(scope="session")
def build_log_path(pack):
    return imageio.find_build_log(pack.source)


@pytest.fixture(scope="session")
def build_log_text(build_log_path):
    if build_log_path is None:
        pytest.skip("Kein Build-Log neben dem Image gefunden (build-docker.log/build.log).")
    return build_log_path.read_text(errors="replace")


@pytest.fixture(scope="session")
def rootfs(pack):
    stage = pack.cache / "rootfs"
    imageio.stage_rootfs(pack.root_img, stage)
    return stage


@pytest.fixture(scope="session")
def container_tag(rootfs):
    if not container.docker_available():
        pytest.skip("Docker nicht verfuegbar (docker ps fehlgeschlagen).")
    digest = hashlib.sha256(str(rootfs).encode()).hexdigest()[:8]
    tag = f"ros-pigen-tests:{digest}"
    return container.import_rootfs(rootfs, tag)


@pytest.fixture(scope="session")
def crun(container_tag):
    def _run(args, privileged=False, timeout=DOCKER_TIMEOUT, network=None):
        return container.run(container_tag, args, privileged=privileged,
                             timeout=timeout, network=network)
    return _run
