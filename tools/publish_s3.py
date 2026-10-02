#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import package_image

BUCKET = "ros-pi-gen-images"
TEST_PREFIX = "ros-pi-gen-test"

# Ziel-Allowlist: Profil+Endpoint+Region müssen als zusammengehöriges
# Tripel auf genau einen Eintrag passen (kein freies Mischen, z. B. kein
# OMV-Profil mit Hetzner-Endpoint). Jedes Ziel hat einen eigenen
# Freigabeschalter (ENV-Variable), damit eine für ein Ziel erteilte
# Freigabe nicht versehentlich einen Upload zum anderen Ziel auslöst.
TARGETS = {
    "omv": {
        "profile": "s3-intern-admin",
        "endpoint": "https://s3-intern.kraeml-bayern.de",
        "region": "eu-central-1",
        "default_public_base_url": "https://s3-intern.kraeml-bayern.de/ros-pi-gen-images",
        "write_approval_env": "ROS_PI_GEN_GATE2_WRITE_APPROVED",
    },
    "hetzner": {
        "profile": "hetzner-prod",
        "endpoint": "https://hel1.your-objectstorage.com",
        "region": "hel1",
        # Path-Style angenommen (analog zur bestätigten OMV-Installation);
        # gemäß AGENTS.md vor dem ersten echten Schreibzugriff anonym
        # verifizieren ("Keine Basis-URL raten") und ggf. korrigieren.
        "default_public_base_url": "https://hel1.your-objectstorage.com/ros-pi-gen-images",
        "write_approval_env": "ROS_PI_GEN_GATE3_WRITE_APPROVED",
    },
}
# Rückwärtskompatible Aliase für bestehende Aufrufer/Tests (Gate-2-Ziel).
EXPECTED_TEST_PROFILE = TARGETS["omv"]["profile"]
EXPECTED_ENDPOINT = TARGETS["omv"]["endpoint"]
EXPECTED_REGION = TARGETS["omv"]["region"]
DEFAULT_PUBLIC_BASE_URL = TARGETS["omv"]["default_public_base_url"]
VERSION_PATTERN = re.compile(r"^(\d{4})\.(\d{2})\.(\d+)-test$")
REQUIRED_PACKAGE_FILES = {
    "package.json",
    "SHA256SUMS",
    "roboter-os.svg",
    "os-list.json",
    "roboter-os-{version}-headless.img.xz",
}


class PublishError(RuntimeError):
    pass


def resolve_target(profile: str, endpoint: str, region: str) -> dict:
    """Findet den Zielnamen, dessen Profil+Endpoint+Region exakt dem
    übergebenen Tripel entspricht. Kein Eintrag passt -> PublishError
    (keine freie Kombination erlaubt, kein Raten einer Basis-URL)."""
    for name, target in TARGETS.items():
        if (target["profile"], target["endpoint"], target["region"]) == (profile, endpoint, region):
            return {"name": name, **target}
    allowed = ", ".join(
        f"{t['profile']}/{t['endpoint']}/{t['region']}" for t in TARGETS.values()
    )
    raise PublishError(
        f"Profil/Endpoint/Region passen zu keinem bekannten Ziel (erlaubt: {allowed})"
    )


def run_aws(args: list[str], profile: str, endpoint: str, region: str, *, allow_failure: bool = False) -> subprocess.CompletedProcess:
    command = [
        "aws",
        "--profile", profile,
        "--endpoint-url", endpoint,
        "--region", region,
        *args,
    ]
    environment = os.environ.copy()
    environment["AWS_REQUEST_CHECKSUM_CALCULATION"] = "when_required"
    environment["AWS_RESPONSE_CHECKSUM_VALIDATION"] = "when_required"
    result = subprocess.run(command, capture_output=True, text=True, env=environment)
    if result.returncode and not allow_failure:
        details = result.stderr.strip() or result.stdout.strip()
        raise PublishError(f"AWS CLI fehlgeschlagen ({result.returncode}): {details}")
    allowed_read_checks = {
        ("s3api", "list-objects-v2"),
    }
    if result.returncode and allow_failure and tuple(args[:2]) not in allowed_read_checks:
        details = result.stderr.strip() or result.stdout.strip()
        raise PublishError(f"AWS CLI-Leseprüfung fehlgeschlagen ({result.returncode}): {details}")
    return result


def validate_package(package_dir: Path) -> dict:
    package_dir = package_dir.resolve()
    metadata_path = package_dir / "package.json"
    if not package_dir.is_dir() or not metadata_path.is_file():
        raise PublishError("Release-Paketverzeichnis oder package.json fehlt")
    try:
        metadata = json.loads(metadata_path.read_text())
    except json.JSONDecodeError as error:
        raise PublishError("package.json ist ungültig") from error
    version = metadata.get("version")
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise PublishError("Gate-2-Publish verlangt eine annotierte Testversion image-YYYY.MM.PATCH-test")
    status = metadata.get("status")
    if status != "test":
        raise PublishError("Nur Paketstatus test darf veröffentlicht werden")
    date = metadata.get("release_date")
    try:
        import datetime as dt
        release_date = dt.date.fromisoformat(date)
    except (ValueError, TypeError) as error:
        raise PublishError("release_date ist kein ISO-Datum") from error
    match = VERSION_PATTERN.fullmatch(version)
    if (release_date.year, release_date.month) != (int(match.group(1)), int(match.group(2))):
        raise PublishError("Test-Tagmonat stimmt nicht mit release_date überein")
    if metadata.get("rpi_imager_commit") != package_image.PIN["rpi_imager_commit"]:
        raise PublishError("Paket hat einen unerwarteten Imager-Schema-Pin")
    if not isinstance(metadata.get("tag"), str) or metadata["tag"] != f"image-{version}":
        raise PublishError("Paketversion und annotierter Test-Tag stimmen nicht überein")
    if metadata.get("variant") != "headless":
        raise PublishError("Gate-2-Ausnahme akzeptiert ausschließlich die Variante headless; Desktop bleibt bis zur erfolgreichen Desktop-Bereitstellung zurückgestellt")
    if metadata.get("schema_version") != 1:
        raise PublishError("Unbekannte Test-Paketdatenversion")
    if not isinstance(metadata.get("tag"), str) or metadata["tag"] != f"image-{version}":
        raise PublishError("Headless-Paketversion passt nicht zum annotierten Test-Tag")
    expected_names = {
        name.format(version=version)
        for name in REQUIRED_PACKAGE_FILES
        if "{version}" in name
    }
    static_package_files = REQUIRED_PACKAGE_FILES - {name for name in REQUIRED_PACKAGE_FILES if "{version}" in name}
    for filename in static_package_files:
        if not (package_dir / filename).is_file():
            raise PublishError(f"Vollständiges Release-Paket enthält {filename} nicht")
    for filename in expected_names:
        if not (package_dir / filename).is_file():
            raise PublishError(f"Vollständiges Release-Paket enthält {filename} nicht")
    package_entries = list(package_dir.iterdir())
    if any(not path.is_file() for path in package_entries):
        raise PublishError("Paketverzeichnis enthält Unterverzeichnisse oder nicht reguläre Dateien")
    package_files = {path.name for path in package_entries}
    if any(path.name.endswith("-desktop.img.xz") for path in package_entries):
        raise PublishError("Gate-2-Ausnahme verbietet Desktop-Images im Headless-Paket")
    if package_files != static_package_files | expected_names:
        raise PublishError("Paketverzeichnis enthält fehlende oder nicht erwartete Dateien")
    if not isinstance(metadata.get("image_download_sha256"), str) or not package_image.SHA256_PATTERN.fullmatch(metadata["image_download_sha256"]):
        raise PublishError("Headless-Paketdaten enthalten keinen gültigen Download-Hash")
    if not isinstance(metadata.get("image_download_size"), int) or metadata["image_download_size"] <= 0:
        raise PublishError("Headless-Paketdaten enthalten keine gültige Download-Größe")
    if not isinstance(metadata.get("extract_sha256"), str) or not package_image.SHA256_PATTERN.fullmatch(metadata["extract_sha256"]):
        raise PublishError("Headless-Paketdaten enthalten keinen gültigen Extrakt-Hash")
    if not isinstance(metadata.get("extract_size"), int) or metadata["extract_size"] <= 0:
        raise PublishError("Headless-Paketdaten enthalten keine gültige Extraktgröße")
    if "desktop-os-list.json" in package_files or "headless-os-list.json" in package_files:
        raise PublishError("Gate-2-Headless-Paket muss genau os-list.json enthalten")
    checksum_entries = {}
    for line in (package_dir / "SHA256SUMS").read_text().splitlines():
        match_line = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match_line or match_line.group(2) in checksum_entries:
            raise PublishError("SHA256SUMS hat ungültige oder doppelte Zeilen")
        checksum_entries[match_line.group(2)] = match_line.group(1)
    if expected_names != {f"roboter-os-{version}-headless.img.xz"}:
        raise PublishError("Gate-2-Paketmenge ist nicht exakt Headless-only")
    if metadata.get("variant") != "headless":
        raise PublishError("Gate-2-Ausnahme erlaubt nur Variante headless")
    if set(checksum_entries) != expected_names:
        raise PublishError("Gate-2-SHA256SUMS muss genau das Headless-Image enthalten")
    if package_image.sha256_file(package_dir / "roboter-os.svg") != package_image.sha256_file(ROOT / "assets/roboter-os.svg"):
        raise PublishError("Imager-Icon im Testpaket entspricht nicht dem gepinnten Projekt-Icon")
    schema_path, catalog_path = package_image.pinned_sources()
    variant = "headless"
    filename = f"roboter-os-{version}-{variant}.img.xz"
    if metadata.get("tag") != f"image-{version}":
        raise PublishError("Paket-Tag und Testversion stimmen nicht überein")
    if metadata.get("release_date") != release_date.isoformat():
        raise PublishError("Paketdaten verwenden ein anderes release_date")
    if metadata.get("rpi_imager_commit") != package_image.PIN["rpi_imager_commit"]:
        raise PublishError("Paketdaten verwenden einen abweichenden Imager-Schema-Pin")
    if metadata.get("image_file") != filename:
        raise PublishError("Paket enthält keinen kanonischen Headless-Dateinamen")
    image = package_dir / filename
    if not image.is_file() or image.stat().st_size != metadata.get("image_download_size"):
        raise PublishError("Headless-Image fehlt oder seine Größe stimmt nicht")
    digest = package_image.sha256_file(image)
    if digest != metadata.get("image_download_sha256") or checksum_entries[filename] != digest:
        raise PublishError("Headless-Image-Prüfsumme stimmt nicht")
    manifest_path = package_dir / "os-list.json"
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise PublishError("Headless-Manifest fehlt oder ist ungültig") from error
    if "imager" in manifest or not isinstance(manifest.get("os_list"), list) or len(manifest["os_list"]) != 1:
        raise PublishError("Gate-2-Headless-Manifest muss genau einen Eintrag enthalten")
    entry = manifest["os_list"][0]
    if entry.get("url", "").split("/")[-1] != filename:
        raise PublishError("Headless-Manifest verweist nicht auf das kanonische Image")
    if entry.get("image_download_size") != image.stat().st_size:
        raise PublishError("Manifest-Größe für Headless stimmt nicht")
    if entry.get("image_download_sha256") != digest:
        raise PublishError("Manifest-Hash passt nicht zum Headless-Image")
    if entry.get("devices") != package_image.PIN["required_device_tags"]:
        raise PublishError("Manifest-Gerätetags für Headless sind inkonsistent")
    if not entry.get("name", "").endswith("(Headless)"):
        raise PublishError("Headless-Manifestname ist inkonsistent")
    try:
        package_image.validate_manifest(manifest, schema_path, catalog_path)
    except package_image.PackageError as error:
        raise PublishError(f"Headless-Manifest verletzt das gepinnte Schema: {error}") from error
    return metadata



def destination_url(base_url: str, key: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise PublishError("--public-base-url muss eine bestätigte HTTPS-Objektbasis sein")
    return base_url.rstrip("/") + "/" + key


def list_version_objects(profile: str, endpoint: str, region: str, prefix: str) -> list[str]:
    if prefix != f"{TEST_PREFIX}/" and not re.fullmatch(r"ros-pi-gen-test/releases/\d{4}\.\d{2}\.\d+-test/", prefix):
        raise PublishError("Versionsprüfung ist auf ros-pi-gen-test/ beschränkt")
    response = run_aws(
        ["s3api", "list-objects-v2", "--bucket", BUCKET, "--prefix", prefix, "--output", "json", "--no-paginate"],
        profile,
        endpoint,
        region,
        allow_failure=True,
    )
    if response.returncode:
        details = response.stderr.strip() or response.stdout.strip()
        if any(marker in details for marker in ("NoSuchBucket", "Not Found", "404")):
            raise PublishError(f"Bucket {BUCKET} fehlt oder ist nicht erreichbar; Anlage ist nicht Teil des Publishers")
        raise PublishError(f"Version kann nicht sicher auf Wiederverwendung geprüft werden: {details}")
    try:
        result = json.loads(response.stdout)
    except json.JSONDecodeError as error:
        raise PublishError("S3-Liste lieferte ungültiges JSON") from error
    if not isinstance(result, dict):
        raise PublishError("S3-Objektliste hat einen ungültigen Antworttyp")
    if "Contents" in result and not isinstance(result["Contents"], list):
        raise PublishError("S3-Objektliste hat ein ungültiges Contents-Feld")
    if result.get("KeyCount", len(result.get("Contents", []))) > 1000:
        raise PublishError("Versionsprüfung überschreitet die nicht-paginierte S3-Listengrenze")
    if result.get("IsTruncated") is True:
        raise PublishError("Versionsprüfung erhielt nur einen unvollständigen Objektlistenausschnitt")
    contents = result.get("Contents", [])
    if any(not isinstance(item, dict) or not isinstance(item.get("Key"), str) for item in contents):
        raise PublishError("S3-Objektliste enthält unvollständige Objektschlüssel")
    return [item["Key"] for item in contents]


def publish_test_package(
    package_dir: Path,
    profile: str,
    endpoint: str,
    region: str,
    public_base_url: str,
    *,
    dry_run: bool = False,
) -> None:
    target = resolve_target(profile, endpoint, region)
    if not dry_run and os.environ.get(target["write_approval_env"]) != "yes":
        raise PublishError(
            f"S3-Schreibzugriff für Ziel '{target['name']}' ist noch nicht ausdrücklich freigegeben "
            f"({target['write_approval_env']}=yes erforderlich)"
        )
    metadata = validate_package(package_dir)
    version = metadata["version"]
    if metadata.get("variant") != "headless":
        raise PublishError("Gate-2-Ausnahme akzeptiert ausschließlich die Variante headless")
    base = public_base_url.rstrip("/")
    if not dry_run:
        parsed_base = urlsplit(base)
        if parsed_base.scheme != "https" or not parsed_base.netloc or parsed_base.query or parsed_base.fragment:
            raise PublishError("Die bestätigte öffentliche HTTPS-Objektbasis ist zwingend erforderlich")
    image_name = f"roboter-os-{version}-headless.img.xz"
    image_key = f"{TEST_PREFIX}/releases/{version}/{image_name}"

    schema_path, catalog_path = package_image.pinned_sources()
    with tempfile.TemporaryDirectory(prefix="ros-pi-gen-test-publish-") as temporary:
        temp_dir = Path(temporary)
        version_manifests: dict[str, Path] = {}
        stable_manifests: dict[str, Path] = {}
        manifest = json.loads((package_dir / "os-list.json").read_text())
        entry = manifest["os_list"][0]
        entry["url"] = (
            f"https://validation.invalid/{image_key}"
            if dry_run else destination_url(base, image_key)
        )
        entry["icon"] = (
            f"https://validation.invalid/{TEST_PREFIX}/releases/{version}/roboter-os.svg"
            if dry_run else destination_url(base, f"{TEST_PREFIX}/releases/{version}/roboter-os.svg")
        )
        package_image.validate_manifest(manifest, schema_path, catalog_path)
        version_path = temp_dir / "os-list.json"
        version_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        version_manifests["headless"] = version_path
        stable_path = temp_dir / "stable-os-list.json"
        stable_manifest = json.loads(json.dumps(manifest))
        stable_path.write_text(json.dumps(stable_manifest, indent=2, ensure_ascii=False) + "\n")
        stable_manifests["headless"] = stable_path
        objects = [] if dry_run else list_version_objects(
            profile,
            endpoint,
            region,
            f"{TEST_PREFIX}/releases/{metadata['version']}/",
        )
        if objects:
            raise PublishError(f"Version {version} enthält bereits Objekte unter {TEST_PREFIX}; nächste Version erforderlich")
        if dry_run:
            return
        parsed_base = urlsplit(base)
        if parsed_base.scheme != "https" or not parsed_base.netloc or parsed_base.query or parsed_base.fragment:
            raise PublishError("Die bestätigte öffentliche HTTPS-Objektbasis ist zwingend erforderlich")
        run_aws(
            ["s3", "cp", str(package_dir / image_name), f"s3://{BUCKET}/{image_key}", "--no-progress"],
            profile,
            endpoint,
            region,
        )
        item = metadata
        remote_image = temp_dir / f"download-{image_name}"
        run_aws(
            ["s3", "cp", f"s3://{BUCKET}/{image_key}", str(remote_image), "--no-progress"],
            profile,
            endpoint,
            region,
        )
        if package_image.sha256_file(remote_image) != item["image_download_sha256"]:
            raise PublishError("Nach Upload geladene Prüfsumme stimmt für Headless nicht")
        run_aws(
            ["s3", "cp", str(package_dir / "roboter-os.svg"), f"s3://{BUCKET}/{TEST_PREFIX}/releases/{version}/roboter-os.svg", "--no-progress"],
            profile,
            endpoint,
            region,
        )
        self_url = destination_url(base, image_key)
        public_probe = subprocess.run(
            ["curl", "--fail", "--silent", "--show-error", "--head", self_url],
            capture_output=True,
            text=True,
        )
        if public_probe.returncode:
            raise PublishError(f"Anonymer HTTPS-Imagezugriff für Headless nicht bestätigt: {public_probe.stderr.strip()}")
        version_key = f"{TEST_PREFIX}/releases/{version}/headless-os-list.json"
        run_aws(
            ["s3", "cp", str(version_manifests["headless"]), f"s3://{BUCKET}/{version_key}", "--no-progress"],
            profile,
            endpoint,
            region,
        )
        self_manifest_probe = subprocess.run(
            ["curl", "--fail", "--silent", "--show-error", "--head", destination_url(base, version_key)],
            capture_output=True,
            text=True,
        )
        if self_manifest_probe.returncode:
            raise PublishError(f"Anonymer HTTPS-Manifestzugriff für Headless nicht bestätigt: {self_manifest_probe.stderr.strip()}")
        fetched_manifest = subprocess.run(
            ["curl", "--fail", "--silent", "--show-error", destination_url(base, version_key)],
            capture_output=True,
            text=True,
        )
        if fetched_manifest.returncode or json.loads(fetched_manifest.stdout) != json.loads(version_manifests["headless"].read_text()):
            raise PublishError("Versioniertes Headless-Manifest kann nicht anonym gelesen oder stimmt nicht überein")
        stable_key = f"{TEST_PREFIX}/imager/headless/s3/os-list.json"
        run_aws(
            ["s3", "cp", str(stable_manifests["headless"]), f"s3://{BUCKET}/{stable_key}", "--no-progress"],
            profile,
            endpoint,
            region,
        )
        stable_probe = subprocess.run(
            ["curl", "--fail", "--silent", "--show-error", "--head", destination_url(base, stable_key)],
            capture_output=True,
            text=True,
        )
        if stable_probe.returncode:
            raise PublishError(f"Anonymer HTTPS-Stabilmanifestzugriff für Headless nicht bestätigt: {stable_probe.stderr.strip()}")
        fetched_stable = subprocess.run(
            ["curl", "--fail", "--silent", "--show-error", destination_url(base, stable_key)],
            capture_output=True,
            text=True,
        )
        if fetched_stable.returncode or json.loads(fetched_stable.stdout) != json.loads(stable_manifests["headless"].read_text()):
            raise PublishError("Stabiles Headless-Manifest kann nicht anonym gelesen oder stimmt nicht überein")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package_dir", type=Path, nargs="?")
    parser.add_argument("--read-only-check", action="store_true")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--public-base-url", default=DEFAULT_PUBLIC_BASE_URL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        if args.read_only_check:
            if args.package_dir is not None:
                raise PublishError("--read-only-check akzeptiert kein Paketverzeichnis")
            resolve_target(args.profile, args.endpoint, args.region)
            keys = list_version_objects(
                args.profile,
                args.endpoint,
                args.region,
                f"{TEST_PREFIX}/",
            )
            print(f"S3-Lesezugriff geprüft; Testpräfix enthält {len(keys)} Objekte.")
            return 0
        if args.package_dir is None:
            raise PublishError("Paketverzeichnis fehlt")
        metadata = validate_package(args.package_dir)
        target = resolve_target(args.profile, args.endpoint, args.region)
        if args.dry_run:
            if not args.public_base_url.startswith("https://"):
                raise PublishError("Dry-Run benötigt eine plausible HTTPS-Basis-URL, ändert aber keine Bucket-Objekte")
        else:
            if os.environ.get(target["write_approval_env"]) != "yes":
                raise PublishError(
                    f"S3-Schreibzugriff für Ziel '{target['name']}' ist noch nicht ausdrücklich freigegeben "
                    f"({target['write_approval_env']}=yes erforderlich)"
                )
        publish_test_package(
            args.package_dir,
            args.profile,
            args.endpoint,
            args.region,
            args.public_base_url,
            dry_run=args.dry_run,
        )
    except (PublishError, package_image.PackageError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"S3-Testveröffentlichung abgebrochen: {error}", file=sys.stderr)
        return 1
    print("Testpaket veröffentlicht und geprüft.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
