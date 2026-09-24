"""Fixtures der AccessPopup-Testinfra (Gruppe Q des Abnahmeprotokolls)."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from helpers import container, imageio

BOOT_TIMEOUT = int(os.environ.get("PIGEN_TEST_BOOT_TIMEOUT", "900"))
DOCKER_TIMEOUT = int(os.environ.get("PIGEN_TEST_DOCKER_TIMEOUT", "300"))

BINFMT_SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "binfmt.sh"


def _binfmt(what: str) -> None:
    proc = subprocess.run([str(BINFMT_SCRIPT), what])
    if proc.returncode != 0:
        print(
            f"[Warnung] binfmt.sh {what} fehlgeschlagen (rc={proc.returncode}). "
            "Q1a (systemd-Boot) braucht einen OFD-tauglichen arm64-Interpreter "
            "(qemu >= 8, Container-Entry); unter altem Host-qemu (< 8) wedged "
            "der Boot. pi-gen-Image vorhanden? (make build legt es an) "
            "Opt-out: PIGEN_TEST_NO_BINFMT=1",
            flush=True,
        )


@pytest.fixture(scope="session", autouse=True)
def binfmt_guard():
    """arm64-Emulation für die Container-Tests sicherstellen.

    make build registriert für die Build-Dauer einen modernen Container-qemu-
    Entry (OFD-tauglich, tools/binfmt.sh Version-Gate) und entfernt ihn im
    Trap VOR den Tests — danach würde alles arm64 unter dem Host-Interpreter
    laufen (ggf. qemu 4.x: fcntl(F_OFD_SETLKW) → EINVAL, systemd wedged beim
    Container-Boot, Q1a-Timeout). Die Suite setzt denselben Entry daher
    selbst (identischer Mechanismus/Gate wie der Build; auf qemu >= 8-Hosts
    No-op) und räumt ihn am Session-Ende wieder ab.
    """
    if not os.environ.get("PIGEN_TEST_NO_BINFMT"):
        _binfmt("setup")
    yield
    if not os.environ.get("PIGEN_TEST_NO_BINFMT"):
        _binfmt("cleanup")


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
