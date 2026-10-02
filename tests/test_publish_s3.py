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


def test_publisher_source_is_headless_only_and_never_touches_production():
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
    assert '"ros-pi-gen/"' not in source
    assert "ros-pi-gen/releases" not in source


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
