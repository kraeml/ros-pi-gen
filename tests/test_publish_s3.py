from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import merge_test_packages
import package_image
import publish_s3

TEST_VERSION = "2026.09.1-test"
TEST_TAG = f"image-{TEST_VERSION}"
RELEASE_DATE = "2026-09-26"


def make_variant_package(directory: Path, variant: str, version: str = TEST_VERSION, status: str = "test") -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    package_version = version.removeprefix("image-")
    image_name = f"roboter-os-{package_version}-{variant}.img.xz"
    image_content = f"image-content-{variant}".encode()
    image_path = directory / image_name
    image_path.write_bytes(image_content)
    image_hash = hashlib.sha256(image_content).hexdigest()
    icon = ROOT / "assets/roboter-os.svg"
    metadata = {
        "schema_version": 1,
        "status": status,
        "version": None if status == "local-test" else package_version,
        "tag": None if status == "local-test" else f"image-{package_version}",
        "variant": variant,
        "release_date": RELEASE_DATE,
        "source_artifact": "build.img.xz",
        "image_file": image_name,
        "image_download_size": len(image_content),
        "image_download_sha256": image_hash,
        "extract_size": 4096,
        "extract_sha256": "a" * 64,
        "rpi_imager_commit": package_image.PIN["rpi_imager_commit"],
    }
    (directory / "package.json").write_text(json.dumps(metadata))
    (directory / "SHA256SUMS").write_text(f"{image_hash}  {image_name}\n")
    (directory / "roboter-os.svg").write_bytes(icon.read_bytes())
    manifest = package_image.render_manifest(metadata, f"https://test.example/{variant}/")
    (directory / "os-list.json").write_text(json.dumps(manifest))
    return metadata


def write_headless_package_files(directory: Path, version: str, status: str) -> dict:
    """Schreibt ein Headless-Paket direkt auf Dateiebene, ohne den Weg über
    package_image.render_manifest() zu nehmen. Wird ausschließlich für
    Tests benötigt, die eine *inkonsistente* Status/Versions-Suffix-
    Kombination erzeugen wollen (render_manifest würde diese bereits vor
    merge_test_packages.validate_headless_package() zurückweisen)."""
    directory.mkdir(parents=True, exist_ok=True)
    image_name = f"roboter-os-{version}-headless.img.xz"
    image_content = b"image-content-headless"
    (directory / image_name).write_bytes(image_content)
    image_hash = hashlib.sha256(image_content).hexdigest()
    metadata = {
        "schema_version": 1,
        "status": status,
        "version": version,
        "tag": f"image-{version}",
        "variant": "headless",
        "release_date": RELEASE_DATE,
        "source_artifact": "build.img.xz",
        "image_file": image_name,
        "image_download_size": len(image_content),
        "image_download_sha256": image_hash,
        "extract_size": 4096,
        "extract_sha256": "a" * 64,
        "rpi_imager_commit": package_image.PIN["rpi_imager_commit"],
    }
    (directory / "package.json").write_text(json.dumps(metadata))
    (directory / "SHA256SUMS").write_text(f"{image_hash}  {image_name}\n")
    (directory / "roboter-os.svg").write_bytes((ROOT / "assets/roboter-os.svg").read_bytes())
    (directory / "os-list.json").write_text(json.dumps({"os_list": []}))
    return metadata


def make_headless_test_package(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    metadata = make_variant_package(directory, "headless")
    manifest = package_image.render_manifest(metadata, "https://test.example/headless/")
    (directory / "os-list.json").write_text(json.dumps(manifest))
    return metadata



def test_headless_merge_requires_only_headless_and_canonical_sums(tmp_path):
    headless = tmp_path / "headless"
    make_variant_package(headless, "headless")
    output = tmp_path / "release"
    merge_test_packages.merge_headless_package(headless, output)
    metadata = json.loads((output / "package.json").read_text())
    assert metadata["variant"] == "headless"
    assert metadata["status"] == "test"
    assert metadata["version"] == TEST_VERSION
    assert (output / "os-list.json").is_file()
    assert not (output / "desktop-os-list.json").exists()
    assert "variants" not in metadata
    assert len((output / "SHA256SUMS").read_text().splitlines()) == 1
    assert {path.name for path in output.iterdir()} == {
        "package.json",
        "SHA256SUMS",
        "roboter-os.svg",
        "os-list.json",
        f"roboter-os-{TEST_VERSION}-headless.img.xz",
    }


def test_headless_merge_rejects_desktop_variant(tmp_path):
    desktop = tmp_path / "desktop"
    make_variant_package(desktop, "desktop")
    with pytest.raises(merge_test_packages.ReleasePackageError):
        merge_test_packages.merge_headless_package(desktop, tmp_path / "release")


def test_headless_merge_accepts_production_status_without_test_suffix(tmp_path):
    production_version = "2026.09.1"
    headless = tmp_path / "headless"
    make_variant_package(headless, "headless", version=production_version, status="production")
    output = tmp_path / "release"
    merge_test_packages.merge_headless_package(headless, output)
    metadata = json.loads((output / "package.json").read_text())
    assert metadata["status"] == "production"
    assert metadata["version"] == production_version
    assert metadata["tag"] == f"image-{production_version}"


def test_headless_merge_rejects_production_status_with_test_suffix(tmp_path):
    headless = tmp_path / "headless"
    write_headless_package_files(headless, version=TEST_VERSION, status="production")
    with pytest.raises(merge_test_packages.ReleasePackageError, match="Suffix"):
        merge_test_packages.merge_headless_package(headless, tmp_path / "release")


def test_headless_merge_rejects_test_status_without_test_suffix(tmp_path):
    headless = tmp_path / "headless"
    write_headless_package_files(headless, version="2026.09.1", status="test")
    with pytest.raises(merge_test_packages.ReleasePackageError, match="Suffix"):
        merge_test_packages.merge_headless_package(headless, tmp_path / "release")


def test_headless_merge_rejects_unknown_status(tmp_path):
    headless = tmp_path / "headless"
    write_headless_package_files(headless, version="2026.09.1", status="local-test")
    with pytest.raises(merge_test_packages.ReleasePackageError, match="akzeptiert nur Status"):
        merge_test_packages.merge_headless_package(headless, tmp_path / "release")


def test_publisher_source_is_headless_only():
    """Verifiziert weiterhin, dass es keinen generischen Desktop-/
    Mehrvarianten-Pfad gibt (Headless-only-Übergangsregelung, AGENTS.md):
    jedes Vorkommen von 'desktop' im Quelltext muss Teil einer
    raise-PublishError-Schutzklausel sein, und es gibt keine Variantenschleife.

    Dieser Test prüfte früher zusätzlich per reiner Textsuche, dass der
    String '\"ros-pi-gen/\"' nirgends im Quelltext vorkommt — das war ein
    Platzhalter dafür, dass der Produktionspräfix (noch) nicht erreichbar
    war. Jetzt, wo publish_production_package() den Produktionspräfix
    bewusst und kontrolliert nutzt, übernehmen die spezifischeren
    Verhaltenstests unten (test_production_publish_is_hetzner_only,
    test_omv_profile_can_never_reach_production_prefix,
    test_production_write_requires_dedicated_approval_env) die eigentliche
    Sicherheitsgarantie: nicht *dass* der Präfix im Code vorkommt, sondern
    *dass* er nur über den vorgesehenen, abgesicherten Pfad erreichbar ist.
    """
    source = (ROOT / "tools/publish_s3.py").read_text()
    lines = source.splitlines()
    desktop_indices = [i for i, line in enumerate(lines) if "desktop" in line]
    assert desktop_indices, "erwartet eine explizite Schutzklausel gegen Desktop-Artefakte"
    for index in desktop_indices:
        window = "\n".join(lines[index:index + 2])
        assert "raise" in window and "PublishError" in window, (
            f"'desktop' darf nur in einer raise-PublishError-Schutzklausel vorkommen, nicht in Zeile {index + 1}"
        )
    assert "for variant in VARIANTS" not in source


def test_production_publish_is_hetzner_only(tmp_path, monkeypatch):
    """publish_production_package() darf ausschließlich mit dem Ziel
    'hetzner' aufgerufen werden; 'omv' muss strukturell abgelehnt werden,
    bevor überhaupt eine S3-Operation stattfinden könnte."""
    metadata = make_variant_package(
        tmp_path / "release", "headless", version="2026.09.1", status="production"
    )
    monkeypatch.setattr(publish_s3, "validate_production_package", lambda path: metadata)
    with pytest.raises(publish_s3.PublishError, match="ausschließlich.*hetzner|hetzner.*ausschließlich"):
        publish_s3.publish_production_package(
            tmp_path / "release",
            publish_s3.EXPECTED_TEST_PROFILE,
            publish_s3.EXPECTED_ENDPOINT,
            publish_s3.EXPECTED_REGION,
            "https://example.invalid/bucket",
        )


def test_omv_profile_can_never_reach_production_prefix(tmp_path, monkeypatch):
    """Selbst mit gesetzter Produktions-Freigabe-Env darf das OMV-Tripel
    niemals zum Produktionspräfix schreiben — resolve_target() liefert für
    das OMV-Tripel immer das Ziel 'omv', dessen eigener Freigabeschalter
    (ROS_PI_GEN_GATE2_WRITE_APPROVED) für den Produktionspfad irrelevant
    ist, und publish_production_package() erzwingt zusätzlich target=='hetzner'."""
    metadata = make_variant_package(
        tmp_path / "release", "headless", version="2026.09.1", status="production"
    )
    monkeypatch.setenv(publish_s3.PRODUCTION_WRITE_APPROVAL_ENV, "yes")
    monkeypatch.setattr(publish_s3, "validate_production_package", lambda path: metadata)
    with pytest.raises(publish_s3.PublishError, match="ausschließlich.*hetzner|hetzner.*ausschließlich"):
        publish_s3.publish_production_package(
            tmp_path / "release",
            publish_s3.EXPECTED_TEST_PROFILE,
            publish_s3.EXPECTED_ENDPOINT,
            publish_s3.EXPECTED_REGION,
            "https://example.invalid/bucket",
        )


def test_production_write_requires_dedicated_approval_env(tmp_path, monkeypatch):
    metadata = make_variant_package(
        tmp_path / "release", "headless", version="2026.09.1", status="production"
    )
    monkeypatch.delenv(publish_s3.PRODUCTION_WRITE_APPROVAL_ENV, raising=False)
    monkeypatch.setattr(publish_s3, "validate_production_package", lambda path: metadata)
    with pytest.raises(publish_s3.PublishError, match="nicht ausdrücklich freigegeben"):
        publish_s3.publish_production_package(
            tmp_path / "release",
            "hetzner-prod",
            "https://hel1.your-objectstorage.com",
            "hel1",
            "https://example.invalid/bucket",
        )


def test_hetzner_gate3_approval_does_not_authorize_production_write(tmp_path, monkeypatch):
    """Die bestehende Gate-3-Testfreigabe darf den neuen, separaten
    Produktions-Freigabeschalter nicht mit-aktivieren (AGENTS.md: eigenes
    Gate pro Freigabeumfang)."""
    metadata = make_variant_package(
        tmp_path / "release", "headless", version="2026.09.1", status="production"
    )
    monkeypatch.setenv("ROS_PI_GEN_GATE3_WRITE_APPROVED", "yes")
    monkeypatch.delenv(publish_s3.PRODUCTION_WRITE_APPROVAL_ENV, raising=False)
    monkeypatch.setattr(publish_s3, "validate_production_package", lambda path: metadata)
    with pytest.raises(publish_s3.PublishError, match="nicht ausdrücklich freigegeben"):
        publish_s3.publish_production_package(
            tmp_path / "release",
            "hetzner-prod",
            "https://hel1.your-objectstorage.com",
            "hel1",
            "https://example.invalid/bucket",
        )


def test_production_publish_dry_run_never_contacts_aws(tmp_path, monkeypatch):
    metadata = make_variant_package(
        tmp_path / "release", "headless", version="2026.09.1", status="production"
    )
    monkeypatch.setattr(publish_s3, "validate_production_package", lambda path: metadata)
    monkeypatch.setattr(publish_s3, "list_version_objects", lambda *args: pytest.fail("dry-run invoked S3"))
    monkeypatch.setattr(publish_s3.package_image, "pinned_sources", lambda: (tmp_path / "schema", tmp_path / "catalog"))
    monkeypatch.setattr(publish_s3.package_image, "validate_manifest", lambda *args: None)
    publish_s3.publish_production_package(
        tmp_path / "release",
        "hetzner-prod",
        "https://hel1.your-objectstorage.com",
        "hel1",
        "https://example.invalid/bucket",
        dry_run=True,
    )


def test_production_publish_fails_closed_when_existing_objects_exist(tmp_path, monkeypatch):
    metadata = make_variant_package(
        tmp_path / "release", "headless", version="2026.09.1", status="production"
    )
    monkeypatch.setenv(publish_s3.PRODUCTION_WRITE_APPROVAL_ENV, "yes")
    monkeypatch.setattr(publish_s3, "validate_production_package", lambda path: metadata)
    monkeypatch.setattr(publish_s3, "list_version_objects", lambda *args: ["ros-pi-gen/releases/old-object"])
    with pytest.raises(publish_s3.PublishError, match="bereits Objekte"):
        publish_s3.publish_production_package(
            tmp_path / "release",
            "hetzner-prod",
            "https://hel1.your-objectstorage.com",
            "hel1",
            "https://example.invalid/bucket",
        )


def test_publish_production_image_returns_metadata_without_touching_manifests(tmp_path, monkeypatch):
    """publish_production_image() lädt ausschließlich Image+Icon hoch und
    liefert die validierten Paketdaten zurück, damit ein Workflow dazwischen
    den GitHub-Draft-Schritt einfügen kann, bevor die Manifeste
    veröffentlicht werden (AGENTS.md-Reihenfolge, Etappe 4)."""
    metadata = make_variant_package(
        tmp_path / "release", "headless", version="2026.09.1", status="production"
    )
    monkeypatch.setenv(publish_s3.PRODUCTION_WRITE_APPROVAL_ENV, "yes")
    monkeypatch.setattr(publish_s3, "validate_production_package", lambda path: metadata)
    calls = []

    def fake_run_aws(args, *a, **k):
        calls.append(args)
        if args[:2] == ["s3api", "head-object"]:
            return publish_s3.subprocess.CompletedProcess(
                args, 0, json.dumps({"ContentLength": metadata["image_download_size"], "ETag": '"etag"'}), ""
            )
        return publish_s3.subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(publish_s3, "run_aws", fake_run_aws)
    monkeypatch.setattr(publish_s3, "list_version_objects", lambda *args: [])
    monkeypatch.setattr(publish_s3.package_image, "sha256_file", lambda path: metadata["image_download_sha256"])
    monkeypatch.setattr(
        publish_s3.subprocess,
        "run",
        lambda command, **kwargs: publish_s3.subprocess.CompletedProcess(command, 0, "", ""),
    )
    result = publish_s3.publish_production_image(
        tmp_path / "release",
        "hetzner-prod",
        "https://hel1.your-objectstorage.com",
        "hel1",
        "https://example.invalid/bucket",
    )
    assert result == metadata
    assert [args[:2] for args in calls] == [
        ["s3", "cp"],
        ["s3api", "head-object"],
        ["s3", "cp"],
        ["s3", "cp"],
    ]
    assert calls[0][2] == str(tmp_path / "release" / metadata["image_file"])
    assert calls[1][calls[1].index("--key") + 1] == calls[0][3].removeprefix("s3://ros-pi-gen-images/")
    assert calls[2][2] == calls[0][3]
    # Keine Manifest-Objekte (os-list.json/headless-os-list.json) werden
    # von diesem Schritt hochgeladen -- nur Image und Icon.
    uploaded_sources = [args[2] for args in calls if args[:2] == ["s3", "cp"]]
    assert not any(str(path).endswith("os-list.json") for path in uploaded_sources)


def test_production_image_hash_mismatch_is_distinct_from_missing_object(tmp_path, monkeypatch):
    metadata = make_variant_package(
        tmp_path / "release", "headless", version="2026.09.1", status="production"
    )
    monkeypatch.setenv(publish_s3.PRODUCTION_WRITE_APPROVAL_ENV, "yes")
    monkeypatch.setattr(publish_s3, "validate_production_package", lambda path: metadata)
    monkeypatch.setattr(publish_s3, "list_version_objects", lambda *args: [])
    calls = []

    def fake_run_aws(args, *a, **k):
        calls.append(args)
        if args[:2] == ["s3api", "head-object"]:
            return publish_s3.subprocess.CompletedProcess(
                args, 0, json.dumps({"ContentLength": metadata["image_download_size"], "ETag": '"etag"'}), ""
            )
        return publish_s3.subprocess.CompletedProcess(args, 0, "", "")

    def fake_download(key, destination, *args, **kwargs):
        destination.write_bytes(b"downloaded-but-different")

    monkeypatch.setattr(publish_s3, "run_aws", fake_run_aws)
    monkeypatch.setattr(publish_s3, "download_for_verification", fake_download)
    monkeypatch.setattr(publish_s3.package_image, "sha256_file", lambda path: "b" * 64)
    with pytest.raises(publish_s3.PublishError, match="Hash weicht ab"):
        publish_s3.publish_production_image(
            tmp_path / "release",
            "hetzner-prod",
            "https://hel1.your-objectstorage.com",
            "hel1",
            "https://example.invalid/bucket",
        )
    assert [args[:2] for args in calls] == [["s3", "cp"], ["s3api", "head-object"]]


def test_publish_production_manifests_requires_prior_image_publish(tmp_path, monkeypatch):
    """publish_production_manifests() bricht ab, wenn noch keine Objekte
    unter der Version liegen -- publish_production_image() muss laut
    AGENTS.md-Reihenfolge zuerst erfolgreich gelaufen sein."""
    metadata = make_variant_package(
        tmp_path / "release", "headless", version="2026.09.1", status="production"
    )
    monkeypatch.setenv(publish_s3.PRODUCTION_WRITE_APPROVAL_ENV, "yes")
    monkeypatch.setattr(publish_s3, "validate_production_package", lambda path: metadata)
    monkeypatch.setattr(publish_s3.package_image, "pinned_sources", lambda: (tmp_path / "schema", tmp_path / "catalog"))
    monkeypatch.setattr(publish_s3.package_image, "validate_manifest", lambda *args: None)
    monkeypatch.setattr(publish_s3, "list_version_objects", lambda *args: [])
    with pytest.raises(publish_s3.PublishError, match="noch keine Objekte"):
        publish_s3.publish_production_manifests(
            tmp_path / "release",
            "hetzner-prod",
            "https://hel1.your-objectstorage.com",
            "hel1",
            "https://example.invalid/bucket",
        )


def test_publish_production_manifests_dry_run_never_contacts_aws(tmp_path, monkeypatch):
    metadata = make_variant_package(
        tmp_path / "release", "headless", version="2026.09.1", status="production"
    )
    monkeypatch.setattr(publish_s3, "validate_production_package", lambda path: metadata)
    monkeypatch.setattr(publish_s3, "list_version_objects", lambda *args: pytest.fail("dry-run invoked S3"))
    monkeypatch.setattr(publish_s3.package_image, "pinned_sources", lambda: (tmp_path / "schema", tmp_path / "catalog"))
    monkeypatch.setattr(publish_s3.package_image, "validate_manifest", lambda *args: None)
    publish_s3.publish_production_manifests(
        tmp_path / "release",
        "hetzner-prod",
        "https://hel1.your-objectstorage.com",
        "hel1",
        "https://example.invalid/bucket",
        dry_run=True,
    )


def test_publish_production_manifests_is_hetzner_only(tmp_path, monkeypatch):
    metadata = make_variant_package(
        tmp_path / "release", "headless", version="2026.09.1", status="production"
    )
    monkeypatch.setattr(publish_s3, "validate_production_package", lambda path: metadata)
    with pytest.raises(publish_s3.PublishError, match="ausschließlich.*hetzner|hetzner.*ausschließlich"):
        publish_s3.publish_production_manifests(
            tmp_path / "release",
            publish_s3.EXPECTED_TEST_PROFILE,
            publish_s3.EXPECTED_ENDPOINT,
            publish_s3.EXPECTED_REGION,
            "https://example.invalid/bucket",
        )


def test_version_scan_rejects_bare_production_root_prefix():
    """Der bloße Produktionspräfix 'ros-pi-gen/' ohne konkrete
    Versions-Unterebene ist nie erlaubt — keine bucketweite
    Produktionslistung, nur die gezielte Wiederverwendungsprüfung einer
    einzelnen Version (AGENTS.md)."""
    with pytest.raises(publish_s3.PublishError, match="Versionsprüfung"):
        publish_s3.list_version_objects(
            "hetzner-prod", "https://hel1.your-objectstorage.com", "hel1", "ros-pi-gen/"
        )


def test_version_scan_accepts_production_release_subprefix(monkeypatch):
    """Die konkrete Produktions-Versions-Unterebene
    ('ros-pi-gen/releases/<version>/') ist für die Wiederverwendungs-
    prüfung zulässig (analog zur bestehenden Test-Versions-Unterebene)."""
    def fake_run(command, **kwargs):
        return publish_s3.subprocess.CompletedProcess(command, 0, '{"KeyCount": 0}', "")

    monkeypatch.setattr(publish_s3.subprocess, "run", fake_run)
    result = publish_s3.list_version_objects(
        "hetzner-prod", "https://hel1.your-objectstorage.com", "hel1", "ros-pi-gen/releases/2026.09.1/"
    )
    assert result == []


def test_validate_production_package_rejects_test_suffix_version(tmp_path):
    package = tmp_path / "release"
    write_headless_package_files(package, version=TEST_VERSION, status="production")
    with pytest.raises(publish_s3.PublishError, match="Produktions-Publish"):
        publish_s3.validate_production_package(package)


def test_validate_package_rejects_production_status(tmp_path):
    package = tmp_path / "release"
    write_headless_package_files(package, version=TEST_VERSION, status="production")
    with pytest.raises(publish_s3.PublishError, match="Nur Paketstatus test"):
        publish_s3.validate_package(package)


def test_publish_package_rejects_local_status_and_partial_variants(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "package.json").write_text(json.dumps({"status": "local-test", "version": None}))
    with pytest.raises(publish_s3.PublishError):
        publish_s3.validate_package(package)


def test_publish_package_validates_headless_hash(tmp_path):
    package = tmp_path / "release"
    metadata = make_headless_test_package(package)
    assert publish_s3.validate_package(package) == metadata
    target = package / metadata["image_file"]
    target.write_bytes(b"modified")
    with pytest.raises(publish_s3.PublishError, match="Größe|Prüfsumme"):
        publish_s3.validate_package(package)


def test_publish_package_rejects_desktop_image_and_unsafe_names(tmp_path):
    package = tmp_path / "release"
    make_headless_test_package(package)
    (package / "roboter-os-2026.09.1-test-desktop.img.xz").write_text("desktop")
    with pytest.raises(publish_s3.PublishError, match="Desktop-Images"):
        publish_s3.validate_package(package)
    (package / "roboter-os-2026.09.1-test-desktop.img.xz").unlink()
    (package / "unexpected.txt").write_text("x")
    with pytest.raises(publish_s3.PublishError, match="fehlende oder nicht erwartete"):
        publish_s3.validate_package(package)


def test_publisher_has_no_bucket_admin_or_delete_operations():
    source = (ROOT / "tools/publish_s3.py").read_text()
    for forbidden in ("head-bucket", "create-bucket", "put-bucket-policy", "delete-object", '"s3:ListBucket"'):
        assert forbidden not in source


def test_version_scan_only_accepts_test_release_subprefixes():
    with pytest.raises(publish_s3.PublishError, match="Versionsprüfung"):
        publish_s3.list_version_objects("s3-intern-admin", publish_s3.EXPECTED_ENDPOINT, "eu-central-1", "ros-pi-gen/")


def test_aws_cli_uses_minio_checksum_compatibility_settings(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return publish_s3.subprocess.CompletedProcess(command, 0, "{}", "")

    monkeypatch.setattr(publish_s3.subprocess, "run", fake_run)
    publish_s3.run_aws(["s3", "ls"], "s3-intern-admin", publish_s3.EXPECTED_ENDPOINT, "eu-central-1")
    assert captured["env"]["AWS_REQUEST_CHECKSUM_CALCULATION"] == "when_required"
    assert captured["env"]["AWS_RESPONSE_CHECKSUM_VALIDATION"] == "when_required"


@pytest.mark.parametrize(
    ("exit_code", "stdout", "stderr", "expected"),
    [
        (1, "An error occurred (404) when calling HeadObject: NoSuchKey", "", ("not_found", 404, "aws_object_or_bucket_not_found")),
        (1, "An error occurred (403) when calling PutObject: AccessDenied", "", ("access_denied", 403, "aws_access_denied")),
        (1, "Provider text says (404), but no AWS error wrapper", "", ("unknown", None, "unclassified")),
        (1, "NoSuchBucket", "", ("not_found", None, "aws_object_or_bucket_not_found")),
        (1, "NoSuchKey", "", ("not_found", None, "aws_object_or_bucket_not_found")),
        (1, "Profile not found", "", ("unknown", None, "unclassified")),
        (1, "command not found", "", ("unknown", None, "unclassified")),
        (1, "", "ReadTimeout: request timed out", ("timeout", None, "network_timeout")),
        (1, "", "EndpointConnectionError: Could not connect", ("connect", None, "network_connection_failed")),
        (1, "opaque provider detail", "", ("unknown", None, "unclassified")),
        (1, "", "Could not read source file", ("unknown", None, "source_file_unreadable")),
        (1, "", "Unable to open file", ("unknown", None, "source_file_unreadable")),
        (1, "", "OSError: [Errno 28] No space left on device", ("unknown", None, "local_storage_full")),
        (1, "", "OSError: [Errno 281] simulated failure", ("unknown", None, "unclassified")),
        (1, "", "Invalid checksum header", ("unknown", None, "unclassified")),
        (1, "", "x-amz-checksum-algorithm rejected", ("unknown", None, "checksum_compatibility_error")),
        (1, "", "CompleteMultipartUpload failed", ("unknown", None, "multipart_upload_error")),
        (1, "", "Part 3 of multipart upload timed out", ("timeout", None, "network_timeout")),
        (1, "", "Traceback (most recent call last): checksum multipart failure", ("unknown", None, "cli_runtime_exception")),
        (1, "", "fatal error: generic failure", ("unknown", None, "cli_fatal_error")),
        (1, "fatal error: An error occurred (404): NoSuchKey", "", ("not_found", 404, "aws_object_or_bucket_not_found")),
    ],
)
def test_classify_aws_failure(exit_code, stdout, stderr, expected):
    assert publish_s3.classify_aws_failure(exit_code, stdout, stderr) == expected


def test_access_denied_classification_precedes_not_found():
    assert publish_s3.classify_aws_failure(
        1, "An error occurred (404): AccessDenied NoSuchKey", ""
    ) == ("access_denied", 404, "aws_access_denied")


def test_traceback_hint_precedes_checksum_and_multipart_markers():
    assert publish_s3.classify_aws_failure(
        1, "", "Traceback (most recent call last): checksum multipart failure"
    ) == ("unknown", None, "cli_runtime_exception")


@pytest.mark.parametrize("exit_code", [0, 1])
def test_aws_cli_never_logs_fake_credentials_from_output_or_exception(monkeypatch, capsys, exit_code):
    credential = "synthetic-credential-never-log-72f0a9"

    def fake_run(command, **kwargs):
        return publish_s3.subprocess.CompletedProcess(
            command,
            exit_code,
            f"stdout {credential}",
            f"stderr {credential} An error occurred (403) AccessDenied" if exit_code else f"stderr {credential}",
        )

    monkeypatch.setattr(publish_s3.subprocess, "run", fake_run)
    error_text = ""
    if exit_code:
        with pytest.raises(publish_s3.AwsCliError) as error:
            publish_s3.run_aws(["s3", "cp", "source", "destination"], "hetzner-prod", "https://example.invalid", "hel1")
        error_text = str(error.value)
    else:
        publish_s3.run_aws(["s3", "cp", "source", "destination"], "hetzner-prod", "https://example.invalid", "hel1")
    captured = capsys.readouterr()
    assert credential not in captured.out + captured.err + error_text


def test_aws_cli_unknown_failure_logs_only_output_lengths(monkeypatch, capsys):
    def fake_run(command, **kwargs):
        return publish_s3.subprocess.CompletedProcess(command, 1, "opaque", "unknown detail")

    monkeypatch.setattr(publish_s3.subprocess, "run", fake_run)
    with pytest.raises(publish_s3.AwsCliError) as error:
        publish_s3.run_aws(["s3", "cp", "source", "destination"], "hetzner-prod", "https://example.invalid", "hel1")
    output = capsys.readouterr().out
    assert "error_class=unknown" in output
    assert "failure_hint=unclassified" in output
    assert "stdout_length=6" in output
    assert "stderr_length=14" in output
    assert "stderr_lines=1" in output
    assert "stderr_upload_failed_prefix=false" in output
    assert "opaque" not in output
    assert "unknown detail" not in output
    assert "opaque" not in str(error.value)
    assert "unknown detail" not in str(error.value)


@pytest.mark.parametrize("marker", ["NoSuchBucket", "NoSuchKey"])
def test_not_found_markers_without_http_wrapper_are_classified(marker):
    assert publish_s3.classify_aws_failure(1, marker, "") == (
        "not_found",
        None,
        "aws_object_or_bucket_not_found",
    )


def test_list_version_objects_maps_nosuchbucket_to_bucket_error(monkeypatch):
    monkeypatch.setattr(
        publish_s3,
        "run_aws",
        lambda *args, **kwargs: publish_s3.subprocess.CompletedProcess(
            args, 1, "NoSuchBucket", ""
        ),
    )
    with pytest.raises(publish_s3.PublishError, match="Bucket ros-pi-gen-images fehlt"):
        publish_s3.list_version_objects(
            "hetzner-prod",
            "https://hel1.your-objectstorage.com",
            "hel1",
            "ros-pi-gen/releases/2026.09.1/",
        )


def test_head_object_verification_reports_missing_object_separately(monkeypatch, capsys):
    def fake_run_aws(args, *a, **k):
        raise publish_s3.AwsCliError(
            "s3api head-object", 1, "not_found", 404, 0, 0, 0, False, "aws_object_or_bucket_not_found"
        )

    monkeypatch.setattr(publish_s3, "run_aws", fake_run_aws)
    with pytest.raises(publish_s3.PublishError, match="Objekt nicht vorhanden"):
        publish_s3.verify_uploaded_object(
            "ros-pi-gen/releases/2026.09.1/roboter-os-2026.09.1-headless.img.xz",
            12,
            "hetzner-prod",
            "https://hel1.your-objectstorage.com",
            "hel1",
        )
    assert "Existenzprüfung" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("stderr", "failure_hint"),
    [
        ("Could not read source file", "source_file_unreadable"),
        ("OSError: [Errno 28] No space left on device", "local_storage_full"),
        ("x-amz-checksum-algorithm rejected", "checksum_compatibility_error"),
        ("CompleteMultipartUpload failed", "multipart_upload_error"),
    ],
)
def test_head_object_unexpected_failures_use_safe_hint(monkeypatch, capsys, stderr, failure_hint):
    def fake_run(command, **kwargs):
        return publish_s3.subprocess.CompletedProcess(command, 1, "", stderr)

    monkeypatch.setattr(publish_s3.subprocess, "run", fake_run)
    with pytest.raises(publish_s3.PublishError, match=f"failure_hint={failure_hint}") as error:
        publish_s3.verify_uploaded_object(
            "ros-pi-gen/releases/2026.09.1/roboter-os-2026.09.1-headless.img.xz",
            12,
            "hetzner-prod",
            "https://hel1.your-objectstorage.com",
            "hel1",
        )
    output = capsys.readouterr().out + str(error.value)
    assert "Objekt nicht vorhanden" not in output
    assert "command not found" not in output
    assert f"failure_hint={failure_hint}" in output
    assert stderr not in output
    assert "stderr_lines=1" in output
    assert "stderr_upload_failed_prefix=false" in output


def test_head_object_verification_checks_size(monkeypatch):
    def fake_run_aws(args, *a, **k):
        return publish_s3.subprocess.CompletedProcess(args, 0, '{"ContentLength": 11, "ETag": "etag"}', "")

    monkeypatch.setattr(publish_s3, "run_aws", fake_run_aws)
    with pytest.raises(publish_s3.PublishError, match="Objektgröße weicht ab"):
        publish_s3.verify_uploaded_object(
            "ros-pi-gen/releases/2026.09.1/roboter-os-2026.09.1-headless.img.xz",
            12,
            "hetzner-prod",
            "https://hel1.your-objectstorage.com",
            "hel1",
        )


def test_head_object_logs_only_allowlisted_metadata(monkeypatch, capsys):
    secret_field = "synthetic-private-header-credential"

    def fake_run_aws(args, *a, **k):
        return publish_s3.subprocess.CompletedProcess(
            args,
            0,
            json.dumps({
                "ContentLength": 12,
                "ETag": '"safe-etag"',
                "LastModified": "2026-09-26T00:00:00Z",
                "Sensitive": secret_field,
            }),
            "",
        )

    monkeypatch.setattr(publish_s3, "run_aws", fake_run_aws)
    publish_s3.verify_uploaded_object(
        "ros-pi-gen/releases/2026.09.1/roboter-os-2026.09.1-headless.img.xz",
        12,
        "hetzner-prod",
        "https://hel1.your-objectstorage.com",
        "hel1",
    )
    output = capsys.readouterr().out
    assert secret_field not in output
    assert "ContentLength=12" in output
    assert 'ETag="safe-etag"' in output
    assert "LastModified=2026-09-26T00:00:00Z" in output


def test_production_image_dry_run_logs_without_upload(tmp_path, monkeypatch, capsys):
    metadata = make_variant_package(
        tmp_path / "release", "headless", version="2026.09.1", status="production"
    )
    monkeypatch.setattr(publish_s3, "validate_production_package", lambda path: metadata)
    monkeypatch.setattr(publish_s3, "list_version_objects", lambda *args: pytest.fail("dry-run queried S3"))
    publish_s3.publish_production_image(
        tmp_path / "release",
        "hetzner-prod",
        "https://hel1.your-objectstorage.com",
        "hel1",
        "https://example.invalid/bucket",
        dry_run=True,
    )
    output = capsys.readouterr().out
    assert "dry_run=true" in output
    assert "kein Upload ausgeführt" in output


def test_version_scan_fails_closed_on_permission_error(monkeypatch):
    def fail(*args, **kwargs):
        return publish_s3.subprocess.CompletedProcess(args[0], 1, "", "AccessDenied")

    monkeypatch.setattr(publish_s3.subprocess, "run", fail)
    with pytest.raises(publish_s3.PublishError, match="Wiederverwendung"):
        publish_s3.list_version_objects("s3-intern-admin", publish_s3.EXPECTED_ENDPOINT, "eu-central-1", "ros-pi-gen-test/releases/2026.09.1-test/")


def test_publish_write_requires_explicit_gate_approval(tmp_path, monkeypatch):
    monkeypatch.delenv("ROS_PI_GEN_GATE2_WRITE_APPROVED", raising=False)
    with pytest.raises(publish_s3.PublishError, match="nicht ausdrücklich freigegeben"):
        publish_s3.publish_test_package(
            tmp_path,
            "s3-intern-admin",
            publish_s3.EXPECTED_ENDPOINT,
            "eu-central-1",
            "https://example.invalid/bucket",
        )


def test_publish_dry_run_never_contacts_aws(tmp_path, monkeypatch):
    metadata = make_headless_test_package(tmp_path / "release")
    monkeypatch.setattr(publish_s3, "validate_package", lambda path: metadata)
    monkeypatch.setattr(publish_s3, "list_version_objects", lambda *args: pytest.fail("dry-run invoked S3"))
    monkeypatch.setattr(publish_s3.package_image, "pinned_sources", lambda: (tmp_path / "schema", tmp_path / "catalog"))
    monkeypatch.setattr(publish_s3.package_image, "validate_manifest", lambda *args: None)
    publish_s3.publish_test_package(
        tmp_path / "release",
        "s3-intern-admin",
        publish_s3.EXPECTED_ENDPOINT,
        "eu-central-1",
        "https://example.invalid/bucket",
        dry_run=True,
    )


def test_publish_fails_closed_when_existing_objects_exist(tmp_path, monkeypatch):
    metadata = make_headless_test_package(tmp_path / "release")
    monkeypatch.setenv("ROS_PI_GEN_GATE2_WRITE_APPROVED", "yes")
    monkeypatch.setattr(publish_s3, "validate_package", lambda path: metadata)
    monkeypatch.setattr(publish_s3, "list_version_objects", lambda *args: ["ros-pi-gen-test/releases/old-object"])
    with pytest.raises(publish_s3.PublishError, match="bereits Objekte"):
        publish_s3.publish_test_package(
            tmp_path / "release",
            "s3-intern-admin",
            publish_s3.EXPECTED_ENDPOINT,
            "eu-central-1",
            "https://example.invalid/bucket",
        )


def test_target_url_rejects_http_and_ambiguous_url():
    with pytest.raises(publish_s3.PublishError):
        publish_s3.destination_url("http://example.invalid/bucket", "key")
    with pytest.raises(publish_s3.PublishError):
        publish_s3.destination_url("https://example.invalid/bucket?public=1", "key")


def test_resolve_target_accepts_known_tripels():
    omv = publish_s3.resolve_target("s3-intern-admin", publish_s3.EXPECTED_ENDPOINT, "eu-central-1")
    assert omv["name"] == "omv"
    assert omv["write_approval_env"] == "ROS_PI_GEN_GATE2_WRITE_APPROVED"
    hetzner = publish_s3.resolve_target("hetzner-prod", "https://hel1.your-objectstorage.com", "hel1")
    assert hetzner["name"] == "hetzner"
    assert hetzner["write_approval_env"] == "ROS_PI_GEN_GATE3_WRITE_APPROVED"


def test_resolve_target_rejects_mixed_combinations():
    with pytest.raises(publish_s3.PublishError, match="passen zu keinem bekannten Ziel"):
        publish_s3.resolve_target("s3-intern-admin", "https://hel1.your-objectstorage.com", "hel1")
    with pytest.raises(publish_s3.PublishError, match="passen zu keinem bekannten Ziel"):
        publish_s3.resolve_target("hetzner-prod", publish_s3.EXPECTED_ENDPOINT, "eu-central-1")
    with pytest.raises(publish_s3.PublishError, match="passen zu keinem bekannten Ziel"):
        publish_s3.resolve_target("unknown-profile", "https://unknown.invalid", "nowhere")


def test_publish_write_requires_explicit_hetzner_gate_approval(tmp_path, monkeypatch):
    metadata = make_headless_test_package(tmp_path / "release")
    monkeypatch.delenv("ROS_PI_GEN_GATE3_WRITE_APPROVED", raising=False)
    monkeypatch.setattr(publish_s3, "validate_package", lambda path: metadata)
    with pytest.raises(publish_s3.PublishError, match="nicht ausdrücklich freigegeben"):
        publish_s3.publish_test_package(
            tmp_path / "release",
            "hetzner-prod",
            "https://hel1.your-objectstorage.com",
            "hel1",
            "https://example.invalid/bucket",
        )


def test_publish_hetzner_dry_run_never_contacts_aws(tmp_path, monkeypatch):
    metadata = make_headless_test_package(tmp_path / "release")
    monkeypatch.setattr(publish_s3, "validate_package", lambda path: metadata)
    monkeypatch.setattr(publish_s3, "list_version_objects", lambda *args: pytest.fail("dry-run invoked S3"))
    monkeypatch.setattr(publish_s3.package_image, "pinned_sources", lambda: (tmp_path / "schema", tmp_path / "catalog"))
    monkeypatch.setattr(publish_s3.package_image, "validate_manifest", lambda *args: None)
    publish_s3.publish_test_package(
        tmp_path / "release",
        "hetzner-prod",
        "https://hel1.your-objectstorage.com",
        "hel1",
        "https://example.invalid/bucket",
        dry_run=True,
    )


def test_omv_gate2_approval_does_not_authorize_hetzner_write(tmp_path, monkeypatch):
    metadata = make_headless_test_package(tmp_path / "release")
    monkeypatch.setenv("ROS_PI_GEN_GATE2_WRITE_APPROVED", "yes")
    monkeypatch.delenv("ROS_PI_GEN_GATE3_WRITE_APPROVED", raising=False)
    monkeypatch.setattr(publish_s3, "validate_package", lambda path: metadata)
    with pytest.raises(publish_s3.PublishError, match="nicht ausdrücklich freigegeben"):
        publish_s3.publish_test_package(
            tmp_path / "release",
            "hetzner-prod",
            "https://hel1.your-objectstorage.com",
            "hel1",
            "https://example.invalid/bucket",
        )


def test_package_metadata_tag_must_match_version(tmp_path):
    package = tmp_path / "headless"
    make_variant_package(package, "headless")
    metadata_path = package / "package.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["tag"] = "image-2026.09.2-test"
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(package_image.PackageError, match="Tag"):
        package_image.write_manifest(package, "https://test.example/headless/")


def test_download_for_verification_retries_on_transient_failure(tmp_path, monkeypatch):
    """Regressionstest für den realen Gate-4-Produktionslauf
    (image-2026.10.1): ein einzelner 'IncompleteRead'-Verbindungsabbruch
    beim Nach-Upload-Download darf nicht sofort den gesamten Publish-Lauf
    abbrechen -- der Download muss mit begrenzten Wiederholungen erneut
    versucht werden."""
    calls = []

    def fake_run_aws(args, profile, endpoint, region, **kwargs):
        calls.append(args)
        if len(calls) < 3:
            raise publish_s3.PublishError(
                "AWS CLI fehlgeschlagen (1): download failed: ... IncompleteRead(...)"
            )
        Path(args[3]).write_bytes(b"ok")
        return publish_s3.subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(publish_s3, "run_aws", fake_run_aws)
    monkeypatch.setattr(publish_s3.time, "sleep", lambda seconds: None)
    destination = tmp_path / "download.img.xz"
    publish_s3.download_for_verification(
        "ros-pi-gen/releases/2026.10.1/roboter-os-2026.10.1-headless.img.xz",
        destination,
        "hetzner-prod",
        "https://hel1.your-objectstorage.com",
        "hel1",
        error_prefix="Produktions",
    )
    assert len(calls) == 3
    assert destination.read_bytes() == b"ok"
    # Jeder Versuch nutzt erhöhte CLI-Timeouts, nicht die Default-Werte.
    assert "--cli-read-timeout" in calls[0]
    assert "--cli-connect-timeout" in calls[0]


def test_download_for_verification_gives_up_after_max_attempts(tmp_path, monkeypatch):
    def fake_run_aws(args, profile, endpoint, region, **kwargs):
        # Partiellen Download simulieren, der vor dem nächsten Versuch
        # entfernt werden muss (kein angebrochener Rest darf als
        # vollständig geprüft werden).
        Path(args[3]).write_bytes(b"partial")
        raise publish_s3.PublishError("IncompleteRead")

    monkeypatch.setattr(publish_s3, "run_aws", fake_run_aws)
    monkeypatch.setattr(publish_s3.time, "sleep", lambda seconds: None)
    destination = tmp_path / "download.img.xz"
    with pytest.raises(publish_s3.PublishError, match="Downloadverifikation nach 3 Versuchen"):
        publish_s3.download_for_verification(
            "ros-pi-gen/releases/2026.10.1/roboter-os-2026.10.1-headless.img.xz",
            destination,
            "hetzner-prod",
            "https://hel1.your-objectstorage.com",
            "hel1",
            error_prefix="Produktions",
        )
    # Kein liegengebliebenes Partial-Objekt nach endgültigem Scheitern.
    assert not destination.exists()


def test_download_for_verification_removes_stale_partial_before_retry(tmp_path, monkeypatch):
    destination = tmp_path / "download.img.xz"
    destination.write_bytes(b"stale-leftover-from-previous-attempt")
    calls = []

    def fake_run_aws(args, profile, endpoint, region, **kwargs):
        calls.append(args)
        # Beim ersten Aufruf darf das alte Partial nicht mehr da sein.
        assert not Path(args[3]).exists()
        Path(args[3]).write_bytes(b"complete")
        return publish_s3.subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(publish_s3, "run_aws", fake_run_aws)
    publish_s3.download_for_verification(
        "ros-pi-gen/releases/2026.10.1/roboter-os-2026.10.1-headless.img.xz",
        destination,
        "hetzner-prod",
        "https://hel1.your-objectstorage.com",
        "hel1",
        error_prefix="Produktions",
    )
    assert len(calls) == 1
    assert destination.read_bytes() == b"complete"
