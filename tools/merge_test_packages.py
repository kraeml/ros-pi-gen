#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import package_image


# Wiederverwendung des in package_image.py gepinnten Versionsmusters, das
# das optionale "-test"-Suffix bereits kennt (Gruppe 4). So bleibt die
# Status/Suffix-Konsistenzprüfung hier identisch zu der in
# package_image.render_manifest()/write_manifest() verwendeten Logik.
VERSION_PATTERN = package_image.PACKAGE_VERSION_PATTERN
ACCEPTED_STATUSES = {"test", "production"}


class ReleasePackageError(RuntimeError):
    pass


def merge_headless_package(headless_dir: Path, output_dir: Path) -> None:
    """Fügt ein einzelnes Headless-Variantenpaket (Status test ODER
    production) zu einem vollständigen Headless-only-Release-Paket
    zusammen. Generisch für Gate-2/3-Testpakete (Status test, Version mit
    -test-Suffix) und für die Headless-only-Übergangsregelung bei
    Produktionsreleases (Status production, Version ohne -test-Suffix,
    siehe AGENTS.md). Die Variante bleibt bewusst auf headless beschränkt,
    solange Desktop nicht erfolgreich bereitgestellt ist; ein künftiger
    Desktop-Merge braucht eine eigene, separat zu prüfende Erweiterung.
    """
    source = headless_dir.resolve()
    output_dir = output_dir.resolve()
    if output_dir == source or output_dir in source.parents or source in output_dir.parents:
        raise ReleasePackageError("Zielverzeichnis darf Headless-Paket weder ersetzen noch enthalten")
    if not (source / "package.json").is_file():
        raise ReleasePackageError(f"Paketdaten fehlen: {source / 'package.json'}")
    try:
        source_metadata = json.loads((source / "package.json").read_text())
    except json.JSONDecodeError as error:
        raise ReleasePackageError("Ungültige Headless-Paketdaten") from error
    expected_files = {
        "package.json",
        "SHA256SUMS",
        "roboter-os.svg",
        "os-list.json",
        f"roboter-os-{source_metadata.get('version', '')}-headless.img.xz",
    }
    if output_dir.exists():
        if not output_dir.is_dir() or any(path.name not in expected_files or not path.is_file() for path in output_dir.iterdir()):
            raise ReleasePackageError(f"Zielverzeichnis enthält unerwartete Dateien: {output_dir}")
    metadata_path = source / "package.json"
    metadata = source_metadata
    validate_headless_package(source, metadata)
    if metadata.get("rpi_imager_commit") != package_image.PIN["rpi_imager_commit"]:
        raise ReleasePackageError("Paket verwendet nicht den gepinnten Raspberry-Pi-Imager-Commit")
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        image_name = metadata["image_file"]
        shutil.copyfile(source / image_name, output_dir / image_name)
        shutil.copyfile(source / "roboter-os.svg", output_dir / "roboter-os.svg")
        release_metadata = {
            key: metadata[key]
            for key in (
                "schema_version",
                "status",
                "version",
                "tag",
                "variant",
                "release_date",
                "image_file",
                "image_download_size",
                "image_download_sha256",
                "extract_size",
                "extract_sha256",
                "rpi_imager_commit",
            )
        }
        (output_dir / "package.json").write_text(json.dumps(release_metadata, indent=2) + "\n")
        shutil.copyfile(source / "SHA256SUMS", output_dir / "SHA256SUMS")
        shutil.copyfile(source / "os-list.json", output_dir / "os-list.json")
    except Exception:
        shutil.rmtree(output_dir)
        raise


def validate_headless_package(package_dir: Path, metadata: dict) -> None:
    status = metadata.get("status")
    if status not in ACCEPTED_STATUSES:
        raise ReleasePackageError(
            f"Headless-Release-Merge akzeptiert nur Status {sorted(ACCEPTED_STATUSES)}, nicht {status!r}"
        )
    version = metadata.get("version")
    version_match = VERSION_PATTERN.fullmatch(version) if isinstance(version, str) else None
    if not version_match:
        raise ReleasePackageError("Benötigt eine gültige YYYY.MM.PATCH[-test]-Paketversion")
    # Statuskonsistenz: test <-> -test-Suffix, production <-> kein Suffix
    # (identisch zur Logik in package_image.render_manifest()/write_manifest()).
    if (status == "test") != bool(version_match.group(4)):
        raise ReleasePackageError("Paketstatus und Versions-Suffix (-test) stimmen nicht zusammen")
    if metadata.get("tag") != f"image-{version}":
        raise ReleasePackageError("Annotierter Tag passt nicht zur Headless-Paketversion")
    if metadata.get("variant") != "headless":
        raise ReleasePackageError(
            "Headless-only-Übergangsregelung akzeptiert genau ein Paket mit Variante headless"
        )
    date = dt.date.fromisoformat(metadata.get("release_date", ""))
    if (date.year, date.month) != (int(version_match.group(1)), int(version_match.group(2))):
        raise ReleasePackageError("Tagmonat stimmt nicht mit release_date überein")
    if metadata.get("rpi_imager_commit") != package_image.PIN["rpi_imager_commit"]:
        raise ReleasePackageError("Headless-Paket hat einen unerwarteten Imager-Schema-Pin")
    image_name = f"roboter-os-{version}-headless.img.xz"
    if metadata.get("image_file") != image_name:
        raise ReleasePackageError("Kanonischer Headless-Image-Dateiname fehlt")
    image = package_dir / image_name
    if not image.is_file() or image.stat().st_size != metadata.get("image_download_size"):
        raise ReleasePackageError("Headless-Image fehlt oder seine Größe weicht ab")
    if package_image.sha256_file(image) != metadata.get("image_download_sha256"):
        raise ReleasePackageError("Headless-Image-Prüfsumme stimmt nicht")
    if not package_image.SHA256_PATTERN.fullmatch(metadata.get("extract_sha256", "")):
        raise ReleasePackageError("Ungültige entpackte Headless-Prüfsumme")
    if not isinstance(metadata.get("extract_size"), int) or metadata["extract_size"] <= 0:
        raise ReleasePackageError("Ungültige entpackte Headless-Imagegröße")
    expected_sums = f"{metadata['image_download_sha256']}  {image_name}\n"
    if not (package_dir / "SHA256SUMS").is_file() or (package_dir / "SHA256SUMS").read_text() != expected_sums:
        raise ReleasePackageError("SHA256SUMS ist ungültig")
    manifest_path = package_dir / "os-list.json"
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ReleasePackageError("Headless-Imager-Manifest fehlt oder ist ungültig") from error
    if "imager" in manifest or not isinstance(manifest.get("os_list"), list) or len(manifest["os_list"]) != 1:
        raise ReleasePackageError("Headless-Manifest muss genau einen Imager-Eintrag haben")
    schema_path, catalog_path = package_image.pinned_sources()
    try:
        package_image.validate_manifest(manifest, schema_path, catalog_path)
    except package_image.PackageError as error:
        raise ReleasePackageError(f"Headless-Manifest verletzt das gepinnte Schema: {error}") from error
    entry = manifest["os_list"][0]
    if entry.get("url", "").split("/")[-1] != image_name:
        raise ReleasePackageError("Headless-Manifest verweist nicht auf das kanonische Image")
    if entry.get("image_download_sha256") != metadata["image_download_sha256"]:
        raise ReleasePackageError("Manifest-Prüfsumme passt nicht zum Headless-Image")
    if entry.get("image_download_size") != metadata["image_download_size"]:
        raise ReleasePackageError("Manifest-Größe passt nicht zum Headless-Image")
    if entry.get("devices") != package_image.PIN["required_device_tags"]:
        raise ReleasePackageError("Manifest-Gerätetags für Headless sind inkonsistent")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("headless_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    try:
        merge_headless_package(args.headless_dir, args.output_dir)
    except (ReleasePackageError, package_image.PackageError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Headless-Release-Paket fehlgeschlagen: {error}", file=sys.stderr)
        return 1
    print(f"Headless-only-Release-Paket erstellt: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
