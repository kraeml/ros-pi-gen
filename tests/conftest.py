"""Fixtures der AccessPopup-Testinfra (Gruppe Q des Abnahmeprotokolls)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import warnings
from pathlib import Path

import pytest

from helpers import container, imageio

BOOT_TIMEOUT = int(os.environ.get("PIGEN_TEST_BOOT_TIMEOUT", "900"))
DOCKER_TIMEOUT = int(os.environ.get("PIGEN_TEST_DOCKER_TIMEOUT", "300"))

BINFMT_SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "binfmt.sh"


def _binfmt(what: str) -> None:
    proc = subprocess.run([str(BINFMT_SCRIPT), what])
    if proc.returncode != 0:
        # warnings.warn statt print: landet im pytest-Warnings-Summary — ein
        # späterer Q1a-Timeout ist dann als Folge des binfmt-Fehlschlags
        # rückschließbar, nicht als unabhängiger Fehler (fail-soft bleibt).
        warnings.warn(
            f"binfmt.sh {what} fehlgeschlagen (rc={proc.returncode}). "
            "Q1a (systemd-Boot) braucht einen OFD-tauglichen arm64-Interpreter "
            "(qemu >= 8, Container-Entry); unter altem Host-qemu (< 8) wedged "
            "der Boot. pi-gen-Image vorhanden? (make build legt es an) "
            "Opt-out: PIGEN_TEST_NO_BINFMT=1",
            RuntimeWarning,
            stacklevel=2,
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

    autouse=True, weil arm64-Braucher über mehrere Module verteilt sind:
    - test_q1_boot (systemd-Container-Boot, Q1a)
    - test_q2_q9_smoke / test_extras_buildstack / test_image_files (crun-
      Container-Execs)
    - test_hostname_ssid (arm64-Container — Teil des lint-Subsets)
    Die Overlay-Guard-Tests (test_overlay_files) sind reine Datei-Checks
    ohne arm64 — autouse wäre dafür Overhead, aber das Version-Gate macht
    setup/cleanup auf qemu >= 8-Hosts zu einem No-op (kein Docker-Aufruf).
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
    # Tag ist ein Label, kein Cache-Key: container.import_rootfs (container.py)
    # entfernt den Tag zuerst (remove_image) und reimportiert das RootFS immer
    # frisch. Der Pfad-Digest wechselt pro Image-Build (prepare() nimmt mtime
    # + size in den Cache-Pfad auf) — ein altes Tag für ein neues Image ist
    # damit unmöglich; doppelter Stale-Schutz.
    digest = hashlib.sha256(str(rootfs).encode()).hexdigest()[:8]
    tag = f"ros-pigen-tests:{digest}"
    return container.import_rootfs(rootfs, tag)


@pytest.fixture(scope="session")
def crun(container_tag):
    def _run(args, privileged=False, timeout=DOCKER_TIMEOUT, network=None):
        return container.run(container_tag, args, privileged=privileged,
                             timeout=timeout, network=network)
    return _run
