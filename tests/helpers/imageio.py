"""Zugriff auf das gebaute pi-gen-Image: Discovery, xz-Entpacken, MBR-Slicing,
Boot-Dateien (7z/FAT), RootFS-Zugriff per debugfs (ext4, ohne Root)."""

from __future__ import annotations

import lzma
import os
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

SECTOR = 512
CHUNK = 8 * 1024 * 1024
MIN_FREE_BYTES = 15 * 1024**3


class ImageError(RuntimeError):
    pass


@dataclass
class Partition:
    index: int
    start: int
    size: int
    ptype: int


@dataclass
class ImagePack:
    source: Path
    cache: Path
    image: Path
    boot_img: Path
    root_img: Path
    boot_dir: Path
    rootfs_dir: Path | None = None


def tests_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def deploy_dirs() -> list[Path]:
    repo_root = tests_dir().parent
    return [
        repo_root.parent / "pi-gen" / "deploy",  # Legacy: Clone als Geschwister
        repo_root / "pi-gen" / "deploy",         # nativer Build (cwd pi-gen)
        repo_root / "deploy",                    # Docker-Build via make build
    ]


def discover_image() -> Path:
    env = os.environ.get("PIGEN_TEST_IMAGE")
    if env:
        p = Path(env).expanduser().resolve()
        if not p.is_file():
            raise ImageError(f"PIGEN_TEST_IMAGE zeigt auf keine Datei: {p}")
        return p
    candidates: list[Path] = []
    for d in deploy_dirs():
        if not d.is_dir():
            continue
        candidates += [
            p for p in d.iterdir()
            if p.is_file() and (p.name.endswith(".img.xz") or p.name.endswith(".img"))
        ]
    if not candidates:
        raise FileNotFoundError(
            "Kein Image gefunden (deploy/, pi-gen/deploy). "
            "Image bauen (make build, siehe README.md) oder PIGEN_TEST_IMAGE setzen."
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)


def cache_root() -> Path:
    root = Path(os.environ.get("PIGEN_TEST_CACHE", tests_dir() / ".work"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _check_disk_free(target: Path, needed: int = MIN_FREE_BYTES) -> None:
    free = shutil.disk_usage(target).free
    if free < needed:
        raise ImageError(
            f"Zu wenig Platz: {free / 1024**3:.1f} GiB frei, "
            f"~{needed / 1024**3:.0f} GiB noetig fuer den Test-Cache ({target})."
        )


def _decompress(source: Path, cache: Path) -> Path:
    if source.name.endswith(".img"):
        return source
    out = cache / "image.img"
    if out.exists() and out.stat().st_size > 0:
        return out
    tmp = out.with_suffix(".img.part")
    with lzma.open(source) as src, open(tmp, "wb") as dst:
        shutil.copyfileobj(src, dst, CHUNK)
    tmp.rename(out)
    return out


def read_partitions(image: Path) -> list[Partition]:
    with image.open("rb") as f:
        f.seek(SECTOR)
        gpt_sig = f.read(8)
        if gpt_sig == b"EFI PART":
            raise ImageError("GPT-Partitionstabelle wird nicht unterstuetzt (pi-gen nutzt MBR).")
        f.seek(0x1BE)
        table = f.read(64)
    parts: list[Partition] = []
    for i in range(4):
        entry = table[i * 16:(i + 1) * 16]
        ptype = entry[3]
        lba, nsec = struct.unpack_from("<I", entry, 8)[0], struct.unpack_from("<I", entry, 12)[0]
        if ptype and nsec:
            parts.append(Partition(i + 1, lba * SECTOR, nsec * SECTOR, ptype))
    if len(parts) < 2:
        raise ImageError(f"MBR von {image} enthaelt weniger als 2 Partitionen.")
    return parts


def _slice(image: Path, part: Partition, out: Path) -> Path:
    if out.exists() and out.stat().st_size == part.size:
        return out
    tmp = out.with_suffix(out.suffix + ".part")
    with image.open("rb") as src, open(tmp, "wb") as dst:
        src.seek(part.start)
        remaining = part.size
        while remaining > 0:
            buf = src.read(min(CHUNK, remaining))
            if not buf:
                raise ImageError(f"Unerwartetes Bild-Ende beim Schneiden von {out.name}.")
            dst.write(buf)
            remaining -= len(buf)
    tmp.rename(out)
    return out


def extract_boot(boot_img: Path, out_dir: Path) -> Path:
    if not (out_dir / "cmdline.txt").exists():
        out_dir.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            ["7z", "x", "-y", f"-o{out_dir}", str(boot_img)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise ImageError(f"7z konnte Boot-Partition nicht entpacken:\n{proc.stderr}")
    return out_dir


def debugfs_run(root_img: Path, command: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["debugfs", "-R", command, str(root_img)],
        capture_output=True, text=True, errors="replace",
    )


def debugfs_stat(root_img: Path, path: str) -> dict:
    proc = debugfs_run(root_img, f"stat \"{path}\"")
    out = proc.stdout + proc.stderr
    if "not such file" in out or "No such file" in out or not proc.stdout.strip():
        raise FileNotFoundError(f"{path} (in {root_img.name})")
    text = proc.stdout
    m_type = re.search(r"Type:\s*([a-z ]+?)\s+Mode:\s*(\d{4,7})", text)
    m_user = re.search(r"User:\s*(\d+)\s+Group:\s*(\d+)", text)
    m_link = re.search(r"Fast link dest: \"?([^\"\n]+)\"?", text)
    if not m_type:
        raise ImageError(f"debugfs-stat-Ausgabe unlesbar fuer {path}:\n{text}")
    kind = m_type.group(1).strip()
    kind = {"symbolic link": "symlink"}.get(kind, kind)
    return {
        "path": path,
        "type": kind,
        "mode": int(m_type.group(2), 8),
        "uid": int(m_user.group(1)) if m_user else -1,
        "gid": int(m_user.group(2)) if m_user else -1,
        "link": m_link.group(1) if m_link else None,
    }


def debugfs_exists(root_img: Path, path: str) -> bool:
    proc = debugfs_run(root_img, f"stat \"{path}\"")
    return "No such file" not in (proc.stdout + proc.stderr) and proc.returncode == 0


def debugfs_cat(root_img: Path, path: str) -> str:
    proc = debugfs_run(root_img, f"cat \"{path}\"")
    if "No such file" in (proc.stdout + proc.stderr):
        raise FileNotFoundError(f"{path} (in {root_img.name})")
    if proc.returncode != 0:
        raise ImageError(f"debugfs cat {path} fehlgeschlagen:\n{proc.stderr}")
    return proc.stdout


def debugfs_ls(root_img: Path, path: str) -> list[str]:
    proc = debugfs_run(root_img, f"ls -l \"{path}\"")
    if proc.returncode != 0 or "No such file" in (proc.stdout + proc.stderr):
        raise FileNotFoundError(f"{path} (in {root_img.name})")
    names: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split(None, 8)
        # Format: <inode> <mode> (<nlink>) <uid> <gid> <size> <date> <time> <name>
        if len(parts) != 9 or not parts[0].isdigit():
            continue
        name = parts[8]
        if name in (".", ".."):
            continue
        names.append(name.rstrip("/"))
    if not names:
        raise ImageError(
            f"debugfs ls -l {path}: keine Eintraege erkannt (Format veraendert?)\n{proc.stdout[:500]}"
        )
    return names


def stage_rootfs(root_img: Path, out_dir: Path) -> Path:
    """RootFS-Inhalt nach out_dir holen (ohne Root; /dev /proc /sys /run /tmp leer)."""
    marker = out_dir / ".stage.complete"
    complete = marker.exists() and (out_dir / "usr").is_dir() and (out_dir / "etc").is_dir()
    if complete:
        return out_dir
    if out_dir.exists():
        shutil.rmtree(out_dir)
    tmp = out_dir.with_name(out_dir.name + ".part")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    SKIP = {"dev", "proc", "sys", "run", "tmp"}
    for name in debugfs_ls(root_img, "/"):
        target = f"/{name}"
        if name in SKIP:
            (tmp / name).mkdir()
            continue
        st = debugfs_stat(root_img, target)
        if st["type"] == "symlink":
            os.symlink(st["link"], tmp / name)
        elif st["type"] == "directory":
            proc = debugfs_run(root_img, f"rdump \"{target}\" \"{tmp}\"")
            bad = [
                ln for ln in (proc.stdout + proc.stderr).splitlines()
                if "error" in ln.lower() and "while changing ownership" not in ln
            ]
            if bad:
                raise ImageError(
                    f"debugfs rdump {target} fehlerhaft:\n" + "\n".join(bad[:10])
                )
        else:
            proc = debugfs_run(root_img, f"dump \"{target}\" \"{tmp / name}\"")
            if proc.returncode != 0:
                raise ImageError(f"debugfs dump {target} fehlgeschlagen:\n{proc.stderr}")
    for name in sorted(SKIP):
        (tmp / name).mkdir(exist_ok=True)
    _neutralize_fstab(tmp)
    _mask_binfmt(tmp)
    entries = len(list(tmp.iterdir()))
    if entries < 10:
        raise ImageError(f"RootFS-Staging unvollstaendig ({entries} Eintraege).")
    tmp.rename(out_dir)
    marker.touch()
    return out_dir


def _neutralize_fstab(stage: Path) -> None:
    """PARTUUID//dev-Eintraege im Staging auskommentieren: der Container hat
    keine Blockdevices, systemd wuerde sonst endlos auf device-units warten.
    (Nur die Staging-Kopie – das Image selbst bleibt unangetastet.)"""
    fstab = stage / "etc" / "fstab"
    if not fstab.is_file():
        return
    lines = []
    for line in fstab.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#") and (s.startswith(("PARTUUID=", "PARTLABEL=", "/dev/"))):
            lines.append("# [Container-Staging] " + line)
        else:
            lines.append(line)
    fstab.write_text("\n".join(lines) + "\n")


def _mask_binfmt(stage: Path) -> None:
    """systemd-binfmt im Staging maskieren: der privilegierte Container koennte
    sonst die binfmt-Handler des HOSTS ueberschreiben (Image-fremde Pfade)."""
    unit_dir = stage / "etc" / "systemd" / "system"
    if unit_dir.is_dir():
        mask = unit_dir / "systemd-binfmt.service"
        if not mask.exists():
            os.symlink("/dev/null", mask)


def prepare(source: Path) -> ImagePack:
    cache = cache_root() / f"{source.name}.{int(source.stat().st_mtime)}-{source.stat().st_size:x}"
    _check_disk_free(cache_root())
    if not cache.exists():
        cache.mkdir(parents=True)
    image = _decompress(source, cache)
    parts = read_partitions(image)
    boot_img = _slice(image, parts[0], cache / "boot.img")
    root_img = _slice(image, parts[1], cache / "root.img")
    boot_dir = extract_boot(boot_img, cache / "boot")
    return ImagePack(
        source=source, cache=cache, image=image,
        boot_img=boot_img, root_img=root_img, boot_dir=boot_dir,
    )


def clean_cache() -> None:
    shutil.rmtree(cache_root(), ignore_errors=True)


def find_build_log(source: Path) -> Path | None:
    candidates = [source.parent / "build-docker.log", source.parent / "build.log"]
    existing = [p for p in candidates if p.is_file()]
    return max(existing, key=lambda p: p.stat().st_mtime) if existing else None
