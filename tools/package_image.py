#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import lzma
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
PIN_PATH = ROOT / "tools" / "imager-schema-pin.json"
PIN = json.loads(PIN_PATH.read_text())
VARIANTS = {"headless": "Headless", "desktop": "Desktop"}
IMAGE_PATTERN = re.compile(r"^image_(\d{4}-\d{2}-\d{2})-raspberrypi-trixie-custom-lite\.img\.xz$")
TAG_PATTERN = re.compile(r"^image-(\d{4})\.(\d{2})\.(\d+)(-test)?$")
PACKAGE_VERSION_PATTERN = re.compile(r"^(\d{4})\.(\d{2})\.(\d+)(-test)?$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CACHE = ROOT / ".cache" / "imager" / PIN["rpi_imager_commit"]


class PackageError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_sha256sums(entries: dict[str, str]) -> str:
    """Rendert einen `SHA256SUMS`-Dateiinhalt im Standardformat von
    `sha256sum` (`<hash>  <dateiname>\\n`) für beliebig viele Dateien,
    sortiert nach Dateiname für deterministische Ausgabe.

    Aktuell schreiben `package_image()` und `merge_headless_package()`
    jeweils nur eine Zeile (Headless-only-Übergangsregelung, AGENTS.md).
    Diese Funktion ist bewusst generisch für mehrere Einträge gehalten,
    damit ein künftiger vollständiger Produktions-Merge (Headless+Desktop)
    dieselbe Funktion ohne Formatänderung wiederverwenden kann.
    """
    if not entries:
        raise PackageError("SHA256SUMS benötigt mindestens einen Dateieintrag")
    for name, digest in entries.items():
        if not SHA256_PATTERN.fullmatch(digest):
            raise PackageError(f"Ungültiger SHA-256-Hash für {name!r}")
    return "".join(f"{digest}  {name}\n" for name, digest in sorted(entries.items()))


def fetch_pinned(url: str, target: Path, expected: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and sha256_file(target) == expected:
        return target
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "ros-pi-gen-package/1"})
        with urllib.request.urlopen(request, timeout=45) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        actual = sha256_file(temporary)
        if actual != expected:
            raise PackageError(f"SHA-256 der gepinnten Quelle stimmt nicht: {url} ({actual})")
        temporary.replace(target)
    except (OSError, urllib.error.URLError) as error:
        temporary.unlink(missing_ok=True)
        raise PackageError(f"Gepinnte Imager-Quelle nicht abrufbar: {url}: {error}") from error
    finally:
        temporary.unlink(missing_ok=True)
    return target


def fetch_device_catalog(url: str, target: Path, expected_devices_sha256: str) -> Path:
    """Lädt den offiziellen Imager-Gerätekatalog und pinnt nur den stabilen
    `imager.devices`-Teilblock per SHA-256 — nicht die Gesamtdatei.

    Die Datei unter `device_catalog_url` ist kein stabiles Release-Artefakt:
    sie enthält neben den Geräte-Metadaten auch die komplette, täglich neu
    generierte OS-Liste (u. a. Nightly-Builds), die sich faktisch jeden Tag
    ändert (siehe AGENTS.md § „devices-Tags" — nur die Gerätetags müssen
    verifiziert werden). Ein SHA-256-Pin auf die Gesamtdatei würde daher bei
    jedem frischen Abruf ohne lokalen Cache zuverlässig fehlschlagen (beob.
    2026-10-02: identischer `imager.devices`-Block, aber geänderter
    Gesamt-Hash durch Nightly-Einträge). Gepinnt wird stattdessen der
    deterministisch (sort_keys) serialisierte `devices`-Block.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        try:
            cached_devices = json.loads(target.read_text()).get("imager", {}).get("devices")
        except (OSError, json.JSONDecodeError):
            cached_devices = None
        if isinstance(cached_devices, list) and cached_devices:
            cached_payload = json.dumps(cached_devices, sort_keys=True, ensure_ascii=False).encode()
            if hashlib.sha256(cached_payload).hexdigest() == expected_devices_sha256:
                return target
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "ros-pi-gen-package/1"})
        with urllib.request.urlopen(request, timeout=45) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        try:
            catalog = json.loads(temporary.read_text())
        except json.JSONDecodeError as error:
            raise PackageError(f"Gerätekatalog ist kein gültiges JSON: {url}") from error
        devices = catalog.get("imager", {}).get("devices")
        if not isinstance(devices, list) or not devices:
            raise PackageError(f"Gerätekatalog enthält keinen imager.devices-Block: {url}")
        payload = json.dumps(devices, sort_keys=True, ensure_ascii=False).encode()
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected_devices_sha256:
            raise PackageError(
                f"SHA-256 des imager.devices-Blocks stimmt nicht: {url} ({actual})"
            )
        temporary.replace(target)
    except (OSError, urllib.error.URLError) as error:
        temporary.unlink(missing_ok=True)
        raise PackageError(f"Gepinnte Imager-Quelle nicht abrufbar: {url}: {error}") from error
    finally:
        temporary.unlink(missing_ok=True)
    return target


def pinned_sources() -> tuple[Path, Path]:
    commit = PIN["rpi_imager_commit"]
    schema = fetch_pinned(
        f"https://raw.githubusercontent.com/raspberrypi/rpi-imager/{commit}/{PIN['schema_path']}",
        CACHE / "os-list-schema.json",
        PIN["schema_sha256"],
    )
    catalog = fetch_device_catalog(
        PIN["device_catalog_url"],
        CACHE / "os_list_imagingutility_v4.json",
        PIN["device_catalog_devices_sha256"],
    )
    return schema, catalog


def validate_manifest(manifest: dict, schema_path: Path, catalog_path: Path) -> None:
    try:
        import jsonschema
    except ImportError as error:
        raise PackageError("jsonschema fehlt; bitte make venv ausführen") from error
    schema = json.loads(schema_path.read_text())
    jsonschema.Draft7Validator.check_schema(schema)
    errors = sorted(jsonschema.Draft7Validator(schema).iter_errors(manifest), key=lambda item: list(map(str, item.path)))
    if errors:
        details = "; ".join(f"{'/'.join(map(str, item.path))}: {item.message}" for item in errors[:5])
        raise PackageError(f"Manifest verletzt das gepinnte Imager-V4-Schema: {details}")
    if "imager" in manifest:
        raise PackageError("Sublist darf keinen imager-Katalogblock enthalten")
    if not isinstance(manifest.get("os_list"), list) or len(manifest["os_list"]) != 1:
        raise PackageError("Manifest muss genau einen OS-Eintrag enthalten")
    catalog = json.loads(catalog_path.read_text())
    catalog_tags = {
        tag
        for device in catalog.get("imager", {}).get("devices", [])
        for tag in device.get("tags", [])
    }
    expected = PIN["required_device_tags"]
    if any(tag not in catalog_tags for tag in expected):
        raise PackageError("Gepinnter offizieller Imager-Katalog enthält nicht alle benötigten Gerätetags")
    entry = manifest["os_list"][0]
    variant = "desktop" if entry.get("name", "").endswith("(Desktop)") else "headless"
    filename = entry.get("url", "").split("/")[-1]
    if not filename.startswith("roboter-os-") or not filename.endswith(("-headless.img.xz", "-desktop.img.xz")):
        raise PackageError("Manifest-URL verwendet keinen kanonischen Image-Dateinamen")
    if entry.get("devices") != expected:
        raise PackageError(f"Gerätetags müssen exakt {expected} sein")
    if "capabilities" in entry:
        raise PackageError("OS capabilities sind für dieses Manifest nicht freigegeben")
    if "image_download_sha256" in entry and not SHA256_PATTERN.fullmatch(entry["image_download_sha256"]):
        raise PackageError("image_download_sha256 ist kein SHA-256-Hash")
    if not SHA256_PATTERN.fullmatch(entry["extract_sha256"]):
        raise PackageError("extract_sha256 ist kein SHA-256-Hash")
    if entry["extract_size"] <= 0 or entry["image_download_size"] <= 0:
        raise PackageError("Image-Größen müssen positiv sein")
    if not isinstance(entry.get("icon"), str) or not entry["icon"]:
        raise PackageError("Manifest-Icon muss eine nichtleere URL oder einen Pfad sein")
    parsed_icon_url = urlsplit(entry["icon"])
    if parsed_icon_url.scheme not in {"http", "https"} or not parsed_icon_url.netloc:
        raise PackageError("Manifest-Icon muss eine HTTP(S)-URL sein")
    if entry.get("init_format") != "cloudinit-rpi":
        raise PackageError("init_format muss cloudinit-rpi sein")
    parsed_image_url = urlsplit(entry.get("url", ""))
    if parsed_image_url.scheme not in {"http", "https"} or not parsed_image_url.netloc:
        raise PackageError("Image-URL muss eine HTTP(S)-URL sein")


def build_info(image: Path, deploy_dir: Path, variant: str) -> tuple[Path, dt.date]:
    matches = [path for path in deploy_dir.iterdir() if path.is_file() and IMAGE_PATTERN.fullmatch(path.name)]
    if len(matches) != 1:
        raise PackageError(f"Erwartete genau ein Build-Artefakt in {deploy_dir}, gefunden: {len(matches)}")
    artifact = matches[0]
    if artifact.resolve() != image.resolve():
        raise PackageError("Ausgewähltes Artefakt stimmt nicht mit dem eindeutigen Build-Artefakt überein")
    match = IMAGE_PATTERN.fullmatch(artifact.name)
    if not match:
        raise PackageError(f"Ungültiger pi-gen-Artefaktname: {artifact.name}")
    build_date = dt.date.fromisoformat(match.group(1))
    logs = [deploy_dir / "build-docker.log", deploy_dir / "build.log"]
    log = next((path for path in logs if path.is_file()), None)
    if log is None:
        raise PackageError("Build-Log fehlt; Varianten-Build kann nicht verifiziert werden")
    text = log.read_text(errors="replace")
    actual = {
        item
        for item in VARIANTS
        if f"/stage-custom/06-variant-{item}" in text or f"/stage2/06-variant-{item}" in text
    }
    if actual != {variant}:
        raise PackageError(f"Build-Log belegt nicht exakt VARIANT={variant}: {sorted(actual)}")
    return artifact, build_date


def current_tag() -> tuple[str | None, dt.date | None, str | None]:
    proc = subprocess.run(
        ["git", "tag", "--points-at", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    tags = [tag for tag in proc.stdout.splitlines() if tag.startswith("image-")]
    if len(tags) > 1:
        raise PackageError(f"Mehrere Image-Tags zeigen auf HEAD: {tags}")
    all_tags = proc.stdout.splitlines()
    non_image_tags = [tag for tag in all_tags if tag and not tag.startswith("image-")]
    if non_image_tags:
        raise PackageError(f"Unpassender zusätzlicher Tag auf HEAD: {non_image_tags}")
    if not tags:
        return None, None, None
    tag = tags[0]
    match = TAG_PATTERN.fullmatch(tag)
    kind = subprocess.run(
        ["git", "cat-file", "-t", f"refs/tags/{tag}"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    if kind != "tag":
        raise PackageError(f"Release-Tag {tag} ist nicht annotiert")
    if not match:
        raise PackageError(f"Ungültiges Imager-CalVer-Tag: {tag}")
    timestamp = subprocess.run(
        ["git", "for-each-ref", "--format=%(taggerdate:unix)", f"refs/tags/{tag}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not timestamp:
        raise PackageError(f"Tagger-Zeitstempel fehlt: {tag}")
    tag_date = dt.datetime.fromtimestamp(int(timestamp), dt.timezone.utc).date()
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12 or int(match.group(3)) < 1:
        raise PackageError(f"Ungültige CalVer-Komponenten: {tag}")
    if (year, month) != (tag_date.year, tag_date.month):
        raise PackageError(f"Tagmonat passt nicht zum UTC-Tagger-Datum {tag_date.isoformat()}: {tag}")
    return tag, tag_date, tag


def audit_release_image(image: Path) -> None:
    sys.path.insert(0, str(ROOT / "tests"))
    from helpers import imageio

    previous_cache = os.environ.get("PIGEN_TEST_CACHE")
    with tempfile.TemporaryDirectory(prefix="ros-pi-gen-package-") as temporary:
        os.environ["PIGEN_TEST_CACHE"] = str(Path(temporary) / "cache")
        try:
            pack = imageio.prepare(image)
            rootfs = imageio.stage_rootfs(pack.root_img, pack.cache / "rootfs")
            boot_files = [path for path in pack.boot_dir.iterdir() if path.is_file()]
            seed_source = ROOT / "stage-custom" / "04-user-data" / "files" / "user-data"
            quickfix_seed = seed_source.read_text() if seed_source.is_file() else ""
            user_data = pack.boot_dir / "user-data"
            if user_data.is_file():
                content = user_data.read_text(errors="replace")
                active_content = "\n".join(
                    line for line in content.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                )
                if quickfix_seed:
                    active_seed = "\n".join(
                        line for line in quickfix_seed.splitlines()
                        if line.strip() and not line.lstrip().startswith("#")
                    )
                    if active_content == active_seed:
                        raise PackageError("Aktiver Quickfix-Seed user-data ist im Image enthalten")
                if re.search(r"^\s*plain_text_passwd:\s*robot\s*$", active_content, re.I | re.M):
                    raise PackageError("Quickfix-Passwort ist im Image enthalten")
                if re.search(r"^\s*ssh_pwauth:\s*true\s*$", active_content, re.I | re.M):
                    raise PackageError("Passwort-SSH ist im Image aktiviert")
                if re.search(r"^\s*-\s*name:\s*robot\s*$", active_content, re.I | re.M):
                    raise PackageError("Quickfix-Benutzer robot ist im Image enthalten")
            passwd = rootfs / "etc/passwd"
            if passwd.is_file() and any(line.startswith("robot:") for line in passwd.read_text(errors="replace").splitlines()):
                raise PackageError("Quickfix-Benutzer robot ist im Image vorhanden")
            if quickfix_seed:
                keys = [line.strip().strip('"') for line in quickfix_seed.splitlines() if line.lstrip().startswith("- \"")]
                for key in keys:
                    if any(key in path.read_text(errors="replace") for path in boot_files):
                        raise PackageError("Betreiber-SSH-Schlüssel aus dem Quickfix-Seed sind im Boot-Image enthalten")
                    for directory in (rootfs / "root" / ".ssh", rootfs / "home"):
                        if directory.is_dir():
                            for path in directory.rglob("authorized_keys"):
                                if key in path.read_text(errors="replace"):
                                    raise PackageError("Betreiber-SSH-Schlüssel aus dem Quickfix-Seed sind im RootFS enthalten")
            ssh_configs = list((rootfs / "etc/ssh").glob("sshd_config*")) if (rootfs / "etc/ssh").is_dir() else []
            ssh_configs.extend((rootfs / "etc/ssh/sshd_config.d").glob("*.conf") if (rootfs / "etc/ssh/sshd_config.d").is_dir() else [])
            for path in ssh_configs:
                if path.is_file() and re.search(r"^\s*PasswordAuthentication\s+yes\s*(?:#.*)?$", path.read_text(errors="replace"), re.I | re.M):
                    raise PackageError(f"Passwort-SSH ist aktiviert: {path.relative_to(rootfs)}")
        finally:
            if previous_cache is None:
                os.environ.pop("PIGEN_TEST_CACHE", None)
            else:
                os.environ["PIGEN_TEST_CACHE"] = previous_cache


def render_manifest(metadata: dict, base_url: str) -> dict:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
        raise PackageError("BASE_URL muss eine explizite HTTP(S)-Basis-URL ohne Query oder Fragment sein")
    base = base_url.rstrip("/") + "/"
    variant = metadata["variant"]
    status = metadata["status"]
    if status not in {"local-test", "test", "production"}:
        raise PackageError(f"Unbekannter Paketstatus: {status}")
    if status == "local-test" and (metadata.get("version") is not None or metadata.get("tag") is not None):
        raise PackageError("local-test-Pakete dürfen keinen Release-Tag oder keine Releaseversion enthalten")
    expected_image_name = f"roboter-os-{metadata['version'] or 'local-test'}-{variant}.img.xz"
    if metadata.get("image_file") != expected_image_name:
        raise PackageError("Image-Dateiname entspricht nicht der kanonischen Variante/Version")
    if metadata.get("rpi_imager_commit") != PIN["rpi_imager_commit"]:
        raise PackageError("Paketdaten wurden mit einem anderen Imager-Schema-Pin erzeugt")
    if status == "local-test" and metadata.get("version") is not None:
        raise PackageError("local-test-Pakete dürfen keine Releaseversion enthalten")
    if status in {"test", "production"}:
        version_match = PACKAGE_VERSION_PATTERN.fullmatch(metadata.get("version", ""))
        if not version_match or (status == "test") != bool(version_match.group(4)):
            raise PackageError("Test-/Produktionspakete benötigen eine zum Status passende Paketversion")
        if metadata.get("tag") != f"image-{metadata['version']}":
            raise PackageError("Annotierter Tag stimmt nicht mit der Paketversion überein")
    if status == "local-test":
        display_name = f"Roboter-OS (Lokaler Test, nicht veröffentlichbar) ({VARIANTS[variant]})"
    else:
        display_version = metadata["version"].removeprefix("image-")
        marker = " (Test)" if status == "test" else ""
        display_name = f"Roboter-OS {display_version}{marker} ({VARIANTS[variant]})"
    icon_path = ROOT / "assets" / "roboter-os.svg"
    if not icon_path.is_file():
        raise PackageError("Imager-Icon fehlt: assets/roboter-os.svg")
    entry = {
        "name": display_name,
        "description": f"ros-pi-gen {VARIANTS[variant]}-Image",
        "icon": base + "roboter-os.svg",
        "url": base + metadata["image_file"],
        "release_date": metadata["release_date"],
        "image_download_size": metadata["image_download_size"],
        "image_download_sha256": metadata["image_download_sha256"],
        "extract_size": metadata["extract_size"],
        "extract_sha256": metadata["extract_sha256"],
        "devices": PIN["required_device_tags"],
        "init_format": "cloudinit-rpi",
    }
    return {"os_list": [entry]}


def write_manifest(
    package_dir: Path,
    base_url: str,
    *,
    output_name: str = "os-list.json",
    output_dir: Path | None = None,
) -> Path:
    """Rendert und validiert ein Imager-Manifest für das Paket in
    `package_dir` gegen `base_url` und schreibt es unter `output_name` in
    `output_dir` (Default: dasselbe Verzeichnis `package_dir`).

    `output_name` ist bewusst parametrisiert statt hart auf `os-list.json`
    verdrahtet: Der S3-Publish-Pfad nutzt weiterhin den Default
    `os-list.json` (stabiles/-versioniertes S3-Manifest, AGENTS.md), ein
    GitHub-Release-Adapter kann denselben Renderer für die
    variantenpräfigierten GitHub-Assets (`headless-os-list.json`,
    `desktop-os-list.json`) mit derselben Schemavalidierung, aber einer
    eigenen, versionierten GitHub-Release-Asset-Basis-URL wiederverwenden
    (AGENTS.md § „make package und Manifest-Rendering“, Punkt 4: Schema ist
    identisch, nur Dateiname und Basis-URL unterscheiden sich je Ziel).

    `output_dir` ist separat von `package_dir` parametrisiert, damit der
    GitHub-Release-Adapter (tools/github_release.py) das GitHub-Manifest
    in ein eigenes Verzeichnis schreiben kann, ohne das S3-Produktions-
    paketverzeichnis zu verändern -- publish_s3.validate_production_package()
    erwartet dort weiterhin exakt den ursprünglichen, unveränderten
    Dateisatz (Image, SHA256SUMS, Icon, os-list.json, package.json).
    """
    metadata_path = package_dir / "package.json"
    metadata = json.loads(metadata_path.read_text())
    status = metadata.get("status")
    if status not in {"local-test", "test", "production"}:
        raise PackageError(f"Unbekannter Paketstatus: {status}")
    variant = metadata.get("variant")
    if variant not in VARIANTS:
        raise PackageError(f"Unbekannte Paketvariante: {variant}")
    if status == "local-test" and (metadata.get("version") is not None or metadata.get("tag") is not None):
        raise PackageError("local-test-Pakete dürfen keinen Release-Tag oder keine Releaseversion enthalten")
    expected_image_name = f"roboter-os-{metadata.get('version') or 'local-test'}-{variant}.img.xz"
    if metadata.get("image_file") != expected_image_name:
        raise PackageError("Image-Dateiname entspricht nicht der kanonischen Variante/Version")
    if metadata.get("rpi_imager_commit") != PIN["rpi_imager_commit"]:
        raise PackageError("Paketdaten wurden mit einem anderen Imager-Schema-Pin")
    if status == "local-test" and (metadata.get("version") is not None or metadata.get("tag") is not None):
        raise PackageError("local-test-Pakete dürfen keinen Release-Tag oder keine Releaseversion enthalten")

    if status in {"test", "production"}:
        version_match = PACKAGE_VERSION_PATTERN.fullmatch(metadata.get("version", ""))
        if not version_match or (status == "test") != bool(version_match.group(4)):
            raise PackageError("Test-/Produktionspakete benötigen eine zum Status passende Paketversion")
        if metadata.get("tag") != f"image-{metadata['version']}":
            raise PackageError("Annotierter Tag stimmt nicht mit der Paketversion überein")
        release_date = dt.date.fromisoformat(metadata.get("release_date", ""))
        if (release_date.year, release_date.month) != (int(version_match.group(1)), int(version_match.group(2))):
            raise PackageError("Paketversion passt nicht zu release_date")
    sums_path = package_dir / "SHA256SUMS"
    expected_sums = f"{metadata.get('image_download_sha256')}  {expected_image_name}\n"
    if not sums_path.is_file() or sums_path.read_text() != expected_sums:
        raise PackageError("SHA256SUMS fehlt oder stimmt nicht mit den Paketdaten überein")
    schema_path, catalog_path = pinned_sources()
    manifest = render_manifest(metadata, base_url)
    validate_manifest(manifest, schema_path, catalog_path)
    icon_source = ROOT / "assets" / "roboter-os.svg"
    if not icon_source.is_file():
        raise PackageError("Imager-Icon fehlt: assets/roboter-os.svg")
    target_dir = output_dir if output_dir is not None else package_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(icon_source, target_dir / "roboter-os.svg")
    output = target_dir / output_name
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    subprocess.run([sys.executable, "-m", "json.tool", str(output)], check=True, stdout=subprocess.DEVNULL)
    image_path = package_dir / metadata["image_file"]
    if image_path.is_file() and sha256_file(image_path) != metadata["image_download_sha256"]:
        raise PackageError("Komprimiertes Image stimmt nicht mit package.json überein")
    sums_path = package_dir / "SHA256SUMS"
    if sums_path.is_file():
        expected_sums = f"{metadata['image_download_sha256']}  {metadata['image_file']}\n"
        if sums_path.read_text() != expected_sums:
            raise PackageError("SHA256SUMS stimmt nicht mit den Paketdaten überein")
    return output


def github_manifest_name(variant: str) -> str:
    """Kanonischer GitHub-Release-Asset-Dateiname je Variante
    (`headless-os-list.json` / `desktop-os-list.json`, AGENTS.md § „Ein
    vollständiges Produktionsrelease“)."""
    if variant not in VARIANTS:
        raise PackageError(f"Unbekannte Paketvariante: {variant}")
    return f"{variant}-os-list.json"


def write_github_manifest(
    package_dir: Path, release_asset_base_url: str, *, output_dir: Path | None = None
) -> Path:
    """Rendert das variantenspezifische GitHub-Release-Manifest
    (`<variant>-os-list.json`) für das Paket in `package_dir` gegen die
    versionierte GitHub-Release-Asset-Basis-URL. Nutzt denselben
    Schema-validierten Renderer wie das S3-Manifest (write_manifest);
    unterscheidet sich ausschließlich in Zieldateiname und Basis-URL.

    `output_dir` (Default: `package_dir`) steuert, wohin das Manifest (und
    die dabei mitkopierte Icon-Datei) geschrieben wird -- siehe
    write_manifest()-Docstring für die Begründung, warum der
    GitHub-Release-Adapter dies von `package_dir` entkoppeln muss."""
    metadata = json.loads((package_dir / "package.json").read_text())
    variant = metadata.get("variant")
    return write_manifest(
        package_dir,
        release_asset_base_url,
        output_name=github_manifest_name(variant),
        output_dir=output_dir,
    )


def package_image(variant: str, deploy_dir: Path, output_dir: Path, base_url: str, release_build: bool) -> None:
    if variant not in VARIANTS:
        raise PackageError("VARIANT muss headless oder desktop sein")
    deploy_dir = deploy_dir.resolve()
    candidates = [path for path in deploy_dir.iterdir() if path.is_file() and IMAGE_PATTERN.fullmatch(path.name)]
    if len(candidates) != 1:
        raise PackageError(f"Erwartete genau ein Build-Artefakt in {deploy_dir}, gefunden: {len(candidates)}")
    artifact, build_date = build_info(candidates[0], deploy_dir, variant)
    tag, tag_date, version = current_tag()
    if release_build and not tag:
        raise PackageError("RELEASE_BUILD=1 benötigt ein annotiertes image-YYYY.MM.PATCH[-test]-Tag")
    if tag and not version:
        raise PackageError("Paketstatus oder Version fehlt am Image-Tag")
    if tag and not release_build:
        raise PackageError("Ein image-Tag darf ausschließlich mit RELEASE_BUILD=1 paketiert werden")
    if tag:
        test_tag = tag.endswith("-test")
        status = "test" if test_tag else "production"
        release_date = tag_date.isoformat()
    else:
        status = "local-test"
        version = None
        release_date = build_date.isoformat()
    stage_skip = ROOT / "stage-custom" / "04-user-data" / "SKIP"
    if release_build and not stage_skip.is_file():
        raise PackageError("Release-Build ist nicht durch 04-user-data/SKIP abgesichert; make build RELEASE_BUILD=1 erforderlich")
    if release_build:
        audit_release_image(artifact)
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise PackageError(f"Paketverzeichnis ist nicht leer oder kein Verzeichnis: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    package_version = version.removeprefix("image-") if version else None
    image_name = f"roboter-os-{package_version or 'local-test'}-{variant}.img.xz"
    output_image = output_dir / image_name
    shutil.copyfile(artifact, output_image)
    extracted_digest = hashlib.sha256()
    extracted_size = 0
    try:
        with lzma.open(artifact, "rb") as source:
            for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                extracted_digest.update(chunk)
                extracted_size += len(chunk)
    except (OSError, lzma.LZMAError):
        output_image.unlink(missing_ok=True)
        raise
    metadata = {
        "schema_version": 1,
        "status": status,
        "version": package_version,
        "tag": version,
        "variant": variant,
        "release_date": release_date,
        "source_artifact": artifact.name,
        "image_file": image_name,
        "image_download_size": output_image.stat().st_size,
        "image_download_sha256": sha256_file(output_image),
        "extract_size": extracted_size,
        "extract_sha256": extracted_digest.hexdigest(),
        "rpi_imager_commit": PIN["rpi_imager_commit"],
    }
    (output_dir / "package.json").write_text(json.dumps(metadata, indent=2) + "\n")
    sums = output_dir / "SHA256SUMS"
    sums.write_text(render_sha256sums({image_name: metadata["image_download_sha256"]}))
    try:
        write_manifest(output_dir, base_url)
    except Exception:
        output_image.unlink(missing_ok=True)
        (output_dir / "package.json").unlink(missing_ok=True)
        (output_dir / "roboter-os.svg").unlink(missing_ok=True)
        (output_dir / "os-list.json").unlink(missing_ok=True)
        sums.unlink(missing_ok=True)
        raise
    print(f"Paket erstellt: {output_dir}")
    print(f"Status: {status}; Variante: {variant}; Image: {image_name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("variant")
    parser.add_argument("deploy_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("base_url")
    parser.add_argument("release_build", choices=("0", "1"))
    args = parser.parse_args()
    try:
        package_image(args.variant, args.deploy_dir, args.output_dir, args.base_url, args.release_build == "1")
    except (PackageError, OSError, subprocess.CalledProcessError, json.JSONDecodeError, lzma.LZMAError) as error:
        print(f"Paketierung fehlgeschlagen: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
