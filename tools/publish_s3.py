#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import package_image

BUCKET = "ros-pi-gen-images"
TEST_PREFIX = "ros-pi-gen-test"
# Produktionspräfix (Etappe 4, AGENTS.md): ausschließlich über
# publish_production_package() erreichbar, die zusätzlich zur
# Freigabe-Env strukturell auf das Ziel 'hetzner' beschränkt ist — OMV
# darf niemals Produktionsschreibrechte erhalten.
PRODUCTION_PREFIX = "ros-pi-gen"
PRODUCTION_WRITE_APPROVAL_ENV = "ROS_PI_GEN_PRODUCTION_WRITE_APPROVED"

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
# Produktionsversion: identisches CalVer-Schema wie VERSION_PATTERN, aber
# ohne das -test-Suffix (analog zu package_image.PACKAGE_VERSION_PATTERN).
PRODUCTION_VERSION_PATTERN = re.compile(r"^(\d{4})\.(\d{2})\.(\d+)$")
# Erlaubtes Teilpräfix für die Produktions-Versions-Wiederverwendungs-
# prüfung (list_version_objects). Bewusst NUR die konkrete Versions-
# Unterebene, kein bloßes "ros-pi-gen/" — eine bucketweite Produktions-
# Listung ist kein Bestandteil dieses Publish-Pfads.
PRODUCTION_VERSION_SUBPREFIX_PATTERN = re.compile(r"^ros-pi-gen/releases/\d{4}\.\d{2}\.\d+/$")
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


# Nach-Upload-Downloadverifikation braucht robustere Netzwerk-Defaults als
# der Rest des Publishers: bei einem Headless-Image von ~800 MB reicht das
# AWS-CLI-Standardtimeout nicht immer aus und ein einzelner transienter
# Verbindungsabbruch (z. B. "IncompleteRead") darf nicht sofort den
# gesamten Produktions-/Test-Publish-Lauf abbrechen (AGENTS.md: bei einem
# Teilfehler die Version nicht erneut verwenden -- ein robuster Download
# verringert, wie oft dieser Fall überhaupt eintritt). Download-Timeout
# bewusst deutlich höher als das Standard-CLI-Timeout (60s); Anzahl und
# Basis-Backoff über Konstanten statt Magic-Numbers im Aufruf.
DOWNLOAD_VERIFY_MAX_ATTEMPTS = 3
DOWNLOAD_VERIFY_BACKOFF_SECONDS = 5
DOWNLOAD_VERIFY_CLI_READ_TIMEOUT = 600
DOWNLOAD_VERIFY_CLI_CONNECT_TIMEOUT = 60


def download_for_verification(
    key: str,
    destination: Path,
    profile: str,
    endpoint: str,
    region: str,
    *,
    error_prefix: str,
) -> None:
    """Lädt ein zuvor hochgeladenes Objekt zur Prüfsummenverifikation
    erneut herunter -- mit erhöhten CLI-Timeouts und begrenzten
    Wiederholungen mit Backoff, da ein einzelner transienter
    Verbindungsabbruch (beobachtet: 'IncompleteRead' bei einem ~800-MB-
    Headless-Image) sonst den gesamten Publish-Lauf ohne Not abbricht.
    Ein partiell geschriebenes Ziel wird vor jedem Versuch entfernt, damit
    kein angebrochener Download fälschlich als vollständig geprüft wird."""
    last_error: PublishError | None = None
    for attempt in range(1, DOWNLOAD_VERIFY_MAX_ATTEMPTS + 1):
        destination.unlink(missing_ok=True)
        try:
            run_aws(
                [
                    "s3", "cp", f"s3://{BUCKET}/{key}", str(destination), "--no-progress",
                    "--cli-read-timeout", str(DOWNLOAD_VERIFY_CLI_READ_TIMEOUT),
                    "--cli-connect-timeout", str(DOWNLOAD_VERIFY_CLI_CONNECT_TIMEOUT),
                ],
                profile,
                endpoint,
                region,
            )
            return
        except PublishError as error:
            last_error = error
            if attempt < DOWNLOAD_VERIFY_MAX_ATTEMPTS:
                time.sleep(DOWNLOAD_VERIFY_BACKOFF_SECONDS * attempt)
    destination.unlink(missing_ok=True)
    raise PublishError(
        f"{error_prefix}-Downloadverifikation nach {DOWNLOAD_VERIFY_MAX_ATTEMPTS} Versuchen "
        f"fehlgeschlagen: {last_error}"
    )


def _validate_headless_package(
    package_dir: Path,
    *,
    status: str,
    version_pattern: re.Pattern,
    error_prefix: str,
) -> dict:
    """Gemeinsame Validierungslogik für Headless-only-Release-Pakete, die
    nach S3 veröffentlicht werden sollen — parametrisiert nach Status
    (test/production) und dem dazu passenden Versions-Suffix-Muster.

    `error_prefix` fließt nur in Fehlermeldungen ein (z. B. "Gate-2" vs.
    "Produktions"), ändert aber keine Prüflogik: Beide Status durchlaufen
    exakt dieselben strukturellen Checks (genau eine Headless-Variante,
    kanonische Dateinamen, Schema-Validierung, Prüfsummen-Konsistenz).
    """
    package_dir = package_dir.resolve()
    metadata_path = package_dir / "package.json"
    if not package_dir.is_dir() or not metadata_path.is_file():
        raise PublishError("Release-Paketverzeichnis oder package.json fehlt")
    try:
        metadata = json.loads(metadata_path.read_text())
    except json.JSONDecodeError as error:
        raise PublishError("package.json ist ungültig") from error
    version = metadata.get("version")
    if not isinstance(version, str) or not version_pattern.fullmatch(version):
        raise PublishError(f"{error_prefix}-Publish verlangt eine annotierte Version zum passenden Versionsmuster")
    actual_status = metadata.get("status")
    if actual_status != status:
        raise PublishError(f"Nur Paketstatus {status} darf über diesen Pfad veröffentlicht werden")
    date = metadata.get("release_date")
    try:
        import datetime as dt
        release_date = dt.date.fromisoformat(date)
    except (ValueError, TypeError) as error:
        raise PublishError("release_date ist kein ISO-Datum") from error
    match = version_pattern.fullmatch(version)
    if (release_date.year, release_date.month) != (int(match.group(1)), int(match.group(2))):
        raise PublishError(f"{error_prefix}-Tagmonat stimmt nicht mit release_date überein")
    if metadata.get("rpi_imager_commit") != package_image.PIN["rpi_imager_commit"]:
        raise PublishError("Paket hat einen unerwarteten Imager-Schema-Pin")
    if not isinstance(metadata.get("tag"), str) or metadata["tag"] != f"image-{version}":
        raise PublishError(f"Paketversion und annotierter {error_prefix}-Tag stimmen nicht überein")
    if metadata.get("variant") != "headless":
        raise PublishError(
            f"{error_prefix}-Ausnahme akzeptiert ausschließlich die Variante headless; Desktop bleibt bis zur "
            "erfolgreichen Desktop-Bereitstellung zurückgestellt"
        )
    if metadata.get("schema_version") != 1:
        raise PublishError(f"Unbekannte {error_prefix}-Paketdatenversion")
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
        raise PublishError(f"{error_prefix}-Ausnahme verbietet Desktop-Images im Headless-Paket")
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
        raise PublishError(f"{error_prefix}-Headless-Paket muss genau os-list.json enthalten")
    checksum_entries = {}
    for line in (package_dir / "SHA256SUMS").read_text().splitlines():
        match_line = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match_line or match_line.group(2) in checksum_entries:
            raise PublishError("SHA256SUMS hat ungültige oder doppelte Zeilen")
        checksum_entries[match_line.group(2)] = match_line.group(1)
    if expected_names != {f"roboter-os-{version}-headless.img.xz"}:
        raise PublishError(f"{error_prefix}-Paketmenge ist nicht exakt Headless-only")
    if set(checksum_entries) != expected_names:
        raise PublishError(f"{error_prefix}-SHA256SUMS muss genau das Headless-Image enthalten")
    if package_image.sha256_file(package_dir / "roboter-os.svg") != package_image.sha256_file(ROOT / "assets/roboter-os.svg"):
        raise PublishError(f"Imager-Icon im {error_prefix}-Paket entspricht nicht dem gepinnten Projekt-Icon")
    schema_path, catalog_path = package_image.pinned_sources()
    variant = "headless"
    filename = f"roboter-os-{version}-{variant}.img.xz"
    if metadata.get("release_date") != release_date.isoformat():
        raise PublishError("Paketdaten verwenden ein anderes release_date")
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
        raise PublishError(f"{error_prefix}-Headless-Manifest muss genau einen Eintrag enthalten")
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


def validate_package(package_dir: Path) -> dict:
    """Validiert ein Gate-2/3-Testpaket (Status test, Version mit
    -test-Suffix) vor dem Publish nach ros-pi-gen-test/."""
    return _validate_headless_package(
        package_dir, status="test", version_pattern=VERSION_PATTERN, error_prefix="Gate-2"
    )


def validate_production_package(package_dir: Path) -> dict:
    """Validiert ein Headless-only-Produktionspaket (Status production,
    Version ohne -test-Suffix) vor dem Publish nach ros-pi-gen/ (Etappe 4,
    AGENTS.md Headless-only-Übergangsregelung). Identische Strukturprüfung
    wie validate_package(), nur mit dem Produktions-Versionsmuster."""
    return _validate_headless_package(
        package_dir,
        status="production",
        version_pattern=PRODUCTION_VERSION_PATTERN,
        error_prefix="Produktions",
    )



def destination_url(base_url: str, key: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise PublishError("--public-base-url muss eine bestätigte HTTPS-Objektbasis sein")
    return base_url.rstrip("/") + "/" + key


def list_version_objects(profile: str, endpoint: str, region: str, prefix: str) -> list[str]:
    allowed = (
        prefix == f"{TEST_PREFIX}/"
        or re.fullmatch(r"ros-pi-gen-test/releases/\d{4}\.\d{2}\.\d+-test/", prefix)
        or PRODUCTION_VERSION_SUBPREFIX_PATTERN.fullmatch(prefix)
    )
    if not allowed:
        raise PublishError(
            f"Versionsprüfung ist auf {TEST_PREFIX}/ oder eine konkrete "
            f"{PRODUCTION_PREFIX}/releases/<version>/-Unterebene beschränkt"
        )
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
        download_for_verification(image_key, remote_image, profile, endpoint, region, error_prefix="Gate-2/3")
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


def _require_production_target_and_approval(profile: str, endpoint: str, region: str, *, dry_run: bool) -> None:
    """Gemeinsame Sicherheitsprüfung für publish_production_image() und
    publish_production_manifests(): strukturell auf das Ziel 'hetzner'
    beschränkt — OMV darf niemals Produktionsschreibrechte erhalten,
    unabhängig davon, ob dessen eigener Gate-2-Freigabeschalter gesetzt
    ist. Nutzt einen eigenen Freigabeschalter
    (PRODUCTION_WRITE_APPROVAL_ENV), damit eine für Gate 3
    (Testveröffentlichung auf Hetzner) erteilte Freigabe niemals
    automatisch auch einen Produktionsupload erlaubt. Jede der beiden
    Funktionen prüft dies eigenständig (kein gemeinsamer Zustand), damit
    ein isolierter Aufruf (z. B. nur Manifeste erneut veröffentlichen)
    denselben Schutz erhält wie der volle Ablauf."""
    target = resolve_target(profile, endpoint, region)
    if target["name"] != "hetzner":
        raise PublishError(
            "Produktions-Publish ist ausschließlich für das Ziel hetzner zulässig "
            f"(angefordert: {target['name']})"
        )
    if not dry_run and os.environ.get(PRODUCTION_WRITE_APPROVAL_ENV) != "yes":
        raise PublishError(
            "S3-Produktions-Schreibzugriff ist noch nicht ausdrücklich freigegeben "
            f"({PRODUCTION_WRITE_APPROVAL_ENV}=yes erforderlich)"
        )


def _require_https_base(base: str) -> None:
    parsed_base = urlsplit(base)
    if parsed_base.scheme != "https" or not parsed_base.netloc or parsed_base.query or parsed_base.fragment:
        raise PublishError("Die bestätigte öffentliche HTTPS-Objektbasis ist zwingend erforderlich")


def publish_production_image(
    package_dir: Path,
    profile: str,
    endpoint: str,
    region: str,
    public_base_url: str,
    *,
    dry_run: bool = False,
) -> dict:
    """Veröffentlicht ausschließlich Image + Icon eines Headless-only-
    Produktionspakets (Status production) unter ros-pi-gen/releases/<version>/
    auf Hetzner und verifiziert beide anonym per HTTPS (Etappe 4,
    AGENTS.md Headless-only-Übergangsregelung).

    Lädt bewusst NICHT die S3-Manifeste hoch (siehe
    publish_production_manifests()): AGENTS.md verlangt für
    Produktionsreleases die Reihenfolge Image -> GitHub-Draft (mit allen
    Assets, inkl. desselben Image als separatem GitHub-Release-Asset) ->
    S3-Manifeste (versioniert, dann stabil) -> GitHub-Release
    veröffentlichen. Der aufrufende Workflow ruft publish_production_image(),
    dann den GitHub-Draft-Schritt, dann publish_production_manifests(),
    dann die GitHub-Veröffentlichung — in dieser Reihenfolge.

    Prüft die Versions-Wiederverwendung (list_version_objects) bereits
    hier, vor jeglichem Upload, damit ein Workflow-Abbruch vor dem
    GitHub-Draft-Schritt keine Teil-Veröffentlichung hinterlässt.

    Gibt die validierten Paketdaten (metadata) zurück, damit der
    aufrufende Workflow denselben, einmal geprüften Stand für den
    GitHub-Draft-Schritt wiederverwenden kann (AGENTS.md: "Hashes und
    Größen werden einmal im Paket erzeugt").
    """
    _require_production_target_and_approval(profile, endpoint, region, dry_run=dry_run)
    metadata = validate_production_package(package_dir)
    version = metadata["version"]
    base = public_base_url.rstrip("/")
    if not dry_run:
        _require_https_base(base)
    image_name = f"roboter-os-{version}-headless.img.xz"
    image_key = f"{PRODUCTION_PREFIX}/releases/{version}/{image_name}"

    with tempfile.TemporaryDirectory(prefix="ros-pi-gen-production-image-publish-") as temporary:
        temp_dir = Path(temporary)
        objects = [] if dry_run else list_version_objects(
            profile,
            endpoint,
            region,
            f"{PRODUCTION_PREFIX}/releases/{version}/",
        )
        if objects:
            raise PublishError(f"Version {version} enthält bereits Objekte unter {PRODUCTION_PREFIX}; nächste Version erforderlich")
        if dry_run:
            return metadata
        _require_https_base(base)
        run_aws(
            ["s3", "cp", str(package_dir / image_name), f"s3://{BUCKET}/{image_key}", "--no-progress"],
            profile,
            endpoint,
            region,
        )
        remote_image = temp_dir / f"download-{image_name}"
        download_for_verification(image_key, remote_image, profile, endpoint, region, error_prefix="Produktions")
        if package_image.sha256_file(remote_image) != metadata["image_download_sha256"]:
            raise PublishError("Nach Upload geladene Prüfsumme stimmt für Headless nicht")
        run_aws(
            ["s3", "cp", str(package_dir / "roboter-os.svg"), f"s3://{BUCKET}/{PRODUCTION_PREFIX}/releases/{version}/roboter-os.svg", "--no-progress"],
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
    return metadata


def publish_production_manifests(
    package_dir: Path,
    profile: str,
    endpoint: str,
    region: str,
    public_base_url: str,
    *,
    dry_run: bool = False,
) -> None:
    """Veröffentlicht die S3-Manifeste (versioniert, dann stabil) eines
    Headless-only-Produktionspakets auf Hetzner (Etappe 4, AGENTS.md
    Headless-only-Übergangsregelung).

    Setzt voraus, dass publish_production_image() für dieselbe Version
    bereits erfolgreich war (Image+Icon liegen unter
    ros-pi-gen/releases/<version>/ und sind anonym erreichbar) — dies wird
    hier NICHT erneut geprüft, da das stabile Manifest laut AGENTS.md
    ohnehin erst nach erfolgreichem GitHub-Draft-Schritt aktualisiert
    werden darf, der bereits auf denselben Image-Upload aufsetzt.

    Prüft die Versions-Wiederverwendung erneut und eigenständig (nicht nur
    im Image-Schritt), damit ein isolierter Aufruf dieser Funktion
    denselben Schutz erhält.
    """
    _require_production_target_and_approval(profile, endpoint, region, dry_run=dry_run)
    metadata = validate_production_package(package_dir)
    version = metadata["version"]
    base = public_base_url.rstrip("/")
    if not dry_run:
        _require_https_base(base)
    image_key = f"{PRODUCTION_PREFIX}/releases/{version}/roboter-os-{version}-headless.img.xz"

    schema_path, catalog_path = package_image.pinned_sources()
    with tempfile.TemporaryDirectory(prefix="ros-pi-gen-production-manifest-publish-") as temporary:
        temp_dir = Path(temporary)
        manifest = json.loads((package_dir / "os-list.json").read_text())
        entry = manifest["os_list"][0]
        entry["url"] = (
            f"https://validation.invalid/{image_key}"
            if dry_run else destination_url(base, image_key)
        )
        entry["icon"] = (
            f"https://validation.invalid/{PRODUCTION_PREFIX}/releases/{version}/roboter-os.svg"
            if dry_run else destination_url(base, f"{PRODUCTION_PREFIX}/releases/{version}/roboter-os.svg")
        )
        package_image.validate_manifest(manifest, schema_path, catalog_path)
        version_path = temp_dir / "os-list.json"
        version_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        stable_path = temp_dir / "stable-os-list.json"
        stable_manifest = json.loads(json.dumps(manifest))
        stable_path.write_text(json.dumps(stable_manifest, indent=2, ensure_ascii=False) + "\n")
        objects = [] if dry_run else list_version_objects(
            profile,
            endpoint,
            region,
            f"{PRODUCTION_PREFIX}/releases/{version}/",
        )
        if not dry_run and not objects:
            raise PublishError(
                f"Version {version} hat noch keine Objekte unter {PRODUCTION_PREFIX} — "
                "publish_production_image() muss zuerst erfolgreich gelaufen sein"
            )
        if dry_run:
            return
        _require_https_base(base)
        version_key = f"{PRODUCTION_PREFIX}/releases/{version}/headless-os-list.json"
        run_aws(
            ["s3", "cp", str(version_path), f"s3://{BUCKET}/{version_key}", "--no-progress"],
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
        if fetched_manifest.returncode or json.loads(fetched_manifest.stdout) != json.loads(version_path.read_text()):
            raise PublishError("Versioniertes Headless-Manifest kann nicht anonym gelesen oder stimmt nicht überein")
        stable_key = f"{PRODUCTION_PREFIX}/imager/headless/s3/os-list.json"
        run_aws(
            ["s3", "cp", str(stable_path), f"s3://{BUCKET}/{stable_key}", "--no-progress"],
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
        if fetched_stable.returncode or json.loads(fetched_stable.stdout) != json.loads(stable_path.read_text()):
            raise PublishError("Stabiles Headless-Manifest kann nicht anonym gelesen oder stimmt nicht überein")


def publish_production_package(
    package_dir: Path,
    profile: str,
    endpoint: str,
    region: str,
    public_base_url: str,
    *,
    dry_run: bool = False,
) -> None:
    """Komplettablauf (Image+Icon, dann beide Manifeste) für einen
    einzelnen, synchronen Aufruf -- z. B. über publish-s3.sh/die CLI
    weiter unten, wo kein GitHub-Draft-Schritt dazwischengeschoben werden
    muss. Der produktionsscharfe Release-Workflow (Etappe 4) ruft
    stattdessen publish_production_image() und
    publish_production_manifests() einzeln auf, mit dem GitHub-Draft-
    Schritt dazwischen (siehe deren Docstrings sowie AGENTS.md)."""
    metadata = publish_production_image(
        package_dir, profile, endpoint, region, public_base_url, dry_run=dry_run
    )
    if dry_run:
        return
    publish_production_manifests(
        package_dir, profile, endpoint, region, public_base_url, dry_run=dry_run
    )
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package_dir", type=Path, nargs="?")
    parser.add_argument("--read-only-check", action="store_true")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--public-base-url", default=DEFAULT_PUBLIC_BASE_URL)
    parser.add_argument("--dry-run", action="store_true")
    # Nur für Paketstatus production relevant: erlaubt dem aufrufenden
    # Release-Workflow (Etappe 4), den GitHub-Draft-Schritt zwischen
    # Image-Upload und Manifest-Upload einzuschieben (AGENTS.md-
    # Reihenfolge: Image -> GitHub-Draft -> S3-Manifeste -> GitHub-Release).
    # Ohne diese Option (Default) läuft weiterhin der komplette Ablauf in
    # einem Aufruf, wie für Gate-2/3-Testpakete (Status test) üblich.
    parser.add_argument(
        "--production-step",
        choices=["image", "manifests"],
        default=None,
        help="Nur den Image- oder den Manifest-Schritt des Produktions-Publish ausführen",
    )
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
        # Paketstatus entscheidet über den Zielpfad (test -> ros-pi-gen-test/,
        # production -> ros-pi-gen/); jeder Pfad validiert und prüft die
        # Freigabe-Env innerhalb seiner eigenen publish_*_package()-Funktion.
        try:
            raw_status = json.loads((args.package_dir / "package.json").read_text()).get("status")
        except (OSError, json.JSONDecodeError) as error:
            raise PublishError("package.json fehlt oder ist ungültig") from error
        if args.production_step is not None and raw_status != "production":
            raise PublishError("--production-step ist nur für Paketstatus production zulässig")
        if raw_status == "production":
            if args.production_step == "image":
                publish_production_image(
                    args.package_dir,
                    args.profile,
                    args.endpoint,
                    args.region,
                    args.public_base_url,
                    dry_run=args.dry_run,
                )
                if not args.dry_run:
                    print("Produktions-Image veröffentlicht und geprüft.")
                    return 0
            elif args.production_step == "manifests":
                publish_production_manifests(
                    args.package_dir,
                    args.profile,
                    args.endpoint,
                    args.region,
                    args.public_base_url,
                    dry_run=args.dry_run,
                )
                if not args.dry_run:
                    print("Produktions-Manifeste veröffentlicht und geprüft.")
                    return 0
            else:
                publish_production_package(
                    args.package_dir,
                    args.profile,
                    args.endpoint,
                    args.region,
                    args.public_base_url,
                    dry_run=args.dry_run,
                )
                if not args.dry_run:
                    print("Produktionspaket veröffentlicht und geprüft.")
                    return 0
        elif raw_status == "test":
            publish_test_package(
                args.package_dir,
                args.profile,
                args.endpoint,
                args.region,
                args.public_base_url,
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                print("Testpaket veröffentlicht und geprüft.")
                return 0
        else:
            raise PublishError(f"Unbekannter oder nicht veröffentlichbarer Paketstatus: {raw_status!r}")
    except (PublishError, package_image.PackageError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"S3-Veröffentlichung abgebrochen: {error}", file=sys.stderr)
        return 1
    print("Dry-Run abgeschlossen (keine Objekte verändert).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
