"""Docker-Hilfen: RootFS als arm64-Image importieren, Kommandos per binfmt/QEMU
ausfuehren, systemd-Container-Boot fuer Q1a."""

from __future__ import annotations

import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


class DockerError(RuntimeError):
    pass


@dataclass
class RunResult:
    args: list[str]
    rc: int
    stdout: str
    stderr: str

    def summary(self) -> str:
        return (
            f"Befehl: {shlex.join(self.args)}\n"
            f"rc={self.rc}\n--- stdout ---\n{self.stdout}\n--- stderr ---\n{self.stderr}"
        )


def docker_available() -> bool:
    try:
        proc = subprocess.run(["docker", "ps"], capture_output=True, timeout=30)
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def image_exists(tag: str) -> bool:
    proc = subprocess.run(["docker", "image", "inspect", tag], capture_output=True)
    return proc.returncode == 0


def import_rootfs(rootfs: Path, tag: str) -> str:
    # Immer frisch importieren: veraltete/leere Images verursachen kryptische
    # docker-run-Fehler; die ~2 GB laesst sich in ~1 min importieren.
    remove_image(tag)
    cmd = (
        f"tar -C {shlex.quote(str(rootfs))} --numeric-owner --owner=0 --group=0 -cf - ."
        f" | docker import --platform linux/arm64 - {shlex.quote(tag)}"
    )
    proc = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    if proc.returncode != 0:
        raise DockerError(f"docker import fehlgeschlagen:\n{proc.stderr}")
    if not image_exists(tag):
        raise DockerError(f"docker import meldete Erfolg, aber {tag} fehlt.")
    return tag


def run(tag: str, args: list[str], privileged: bool = False,
        timeout: int = 300, extra: list[str] | None = None,
        network: str | None = None) -> RunResult:
    cmd = ["docker", "run", "--rm", "--platform", "linux/arm64"]
    if privileged:
        cmd.append("--privileged")
    if network:
        cmd += ["--network", network]
    cmd += (extra or []) + [tag] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise DockerError(f"Timeout nach {timeout}s: {shlex.join(args)}") from e
    return RunResult(args=args, rc=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def start_systemd(tag: str, name: str) -> None:
    remove_container(name)
    cmd = [
        "docker", "run", "-d", "--privileged", "--platform", "linux/arm64",
        "--name", name, "--tmpfs", "/run", "--tmpfs", "/run/lock", "--tmpfs", "/tmp",
        tag, "/sbin/init",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise DockerError(f"systemd-Container-Start fehlgeschlagen:\n{proc.stderr}")
    time.sleep(1)
    state = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}}", name],
                           capture_output=True, text=True).stdout.strip()
    if state != "running":
        raise DockerError(
            f"Container {name} nicht 'running' (={state}):\n{logs(name)[-2000:]}"
        )


NFT_HELPER_TAG = "ros-pigen-tests-nft:1"
NFT_HELPER_DOCKERFILE = Path(__file__).resolve().parents[1] / "docker" / "nft-helper" / "Dockerfile"
NFT_HELPER_BUILD_TIMEOUT = 600
NFT_HELPER_RETRY_DELAYS = (5, 15, 45)
NFT_HELPER_TRANSIENT_REGISTRY_ERROR = re.compile(
    r"https?://registry-1\.docker\.io(?::\d+)?/\S*?:\s+(?:429|5\d\d)\b",
    re.IGNORECASE,
)


def _build_nft_helper() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker", "build", "--platform", "linux/amd64", "-q", "-t", NFT_HELPER_TAG,
            "-f", str(NFT_HELPER_DOCKERFILE), str(NFT_HELPER_DOCKERFILE.parent),
        ],
        capture_output=True, text=True, timeout=NFT_HELPER_BUILD_TIMEOUT,
    )


def _is_transient_registry_error(stderr: str) -> bool:
    return bool(NFT_HELPER_TRANSIENT_REGISTRY_ERROR.search(stderr))


def ensure_nft_helper() -> str:
    """Build a native amd64 helper for nft syntax checks when it is not cached locally."""
    if image_exists(NFT_HELPER_TAG):
        return NFT_HELPER_TAG
    if not NFT_HELPER_DOCKERFILE.is_file():
        raise DockerError(f"nft-Hilfsimage-Dockerfile fehlt: {NFT_HELPER_DOCKERFILE}")

    for attempt in range(len(NFT_HELPER_RETRY_DELAYS) + 1):
        try:
            proc = _build_nft_helper()
        except subprocess.TimeoutExpired as error:
            raise DockerError(
                f"nft-Hilfsimage-Build nach {NFT_HELPER_BUILD_TIMEOUT}s abgebrochen"
            ) from error
        except OSError as error:
            raise DockerError(f"nft-Hilfsimage-Build konnte nicht gestartet werden: {error}") from error

        if proc.returncode == 0:
            if not image_exists(NFT_HELPER_TAG):
                raise DockerError("nft-Hilfsimage-Build war erfolgreich, aber das Image fehlt.")
            return NFT_HELPER_TAG

        stderr = proc.stderr or ""
        if not _is_transient_registry_error(stderr) or attempt == len(NFT_HELPER_RETRY_DELAYS):
            raise DockerError(f"nft-Hilfsimage-Build fehlgeschlagen:\n{stderr}")

        delay = NFT_HELPER_RETRY_DELAYS[attempt]
        print(
            f"nft-Hilfsimage-Build: temporärer Docker-Hub-Fehler; "
            f"Versuch {attempt + 2}/{len(NFT_HELPER_RETRY_DELAYS) + 1} in {delay}s.",
            flush=True,
        )
        time.sleep(delay)

    raise DockerError("nft-Hilfsimage-Build wurde unerwartet beendet.")


def logs(name: str) -> str:
    proc = subprocess.run(["docker", "logs", name], capture_output=True, text=True,
                          errors="replace")
    return proc.stdout + proc.stderr


def exec_cmd(name: str, args: list[str], timeout: int = 120) -> RunResult:
    cmd = ["docker", "exec", name] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise DockerError(f"Timeout nach {timeout}s (exec): {shlex.join(args)}") from e
    return RunResult(args=args, rc=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def wait_log(name: str, pattern: str, timeout: int, poll: float = 2.0) -> bool:
    import re
    rx = re.compile(pattern)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if rx.search(logs(name)):
            return True
        time.sleep(poll)
    return False


def remove_container(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def remove_image(tag: str) -> None:
    subprocess.run(["docker", "rmi", "-f", tag], capture_output=True)
