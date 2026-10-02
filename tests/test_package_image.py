from __future__ import annotations

import datetime as dt
import json
import lzma
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import package_image


def test_local_package_metadata_and_manifest(tmp_path, monkeypatch):
    source = tmp_path / "sample.img.xz"
    image_bytes = b"small test image"
    source.write_bytes(lzma.compress(image_bytes))
    output = tmp_path / "package"
    output.mkdir()
    metadata = {
        "status": "local-test",
        "version": None,
        "tag": None,
        "variant": "headless",
        "release_date": "2026-09-01",
        "image_file": "roboter-os-local-test-headless.img.xz",
        "image_download_size": source.stat().st_size,
        "image_download_sha256": package_image.sha256_file(source),
        "extract_size": len(image_bytes),
        "extract_sha256": "1" * 64,
        "rpi_imager_commit": package_image.PIN["rpi_imager_commit"],
    }
    monkeypatch.setattr(package_image, "pinned_sources", lambda: (tmp_path / "schema", tmp_path / "catalog"))
    monkeypatch.setattr(package_image, "validate_manifest", lambda *args: None)
    (output / "package.json").write_text(json.dumps(metadata))
    (output / metadata["image_file"]).write_bytes(source.read_bytes())
    (output / "SHA256SUMS").write_text(
        f"{metadata['image_download_sha256']}  {metadata['image_file']}\n"
    )
    result = package_image.write_manifest(output, "http://127.0.0.1:8000/")
    manifest = json.loads(result.read_text())
    entry = manifest["os_list"][0]
    assert entry["name"] == "Roboter-OS (Lokaler Test, nicht veröffentlichbar) (Headless)"
    assert entry["url"] == "http://127.0.0.1:8000/roboter-os-local-test-headless.img.xz"
    assert entry["devices"] == ["pi3-64bit", "pi4-64bit", "pi5-64bit"]
    assert "imager" not in manifest
    assert entry["icon"] == "http://127.0.0.1:8000/roboter-os.svg"
    assert (output / "roboter-os.svg").is_file()
    assert (output / "SHA256SUMS").read_text() == (
        f"{metadata['image_download_sha256']}  {metadata['image_file']}\n"
    )
    (output / metadata["image_file"]).write_bytes(b"altered")
    with pytest.raises(package_image.PackageError, match="stimmt nicht"):
        package_image.write_manifest(output, "http://127.0.0.1:8000/")


def test_render_sha256sums_formats_single_entry_like_existing_packages():
    content = package_image.render_sha256sums({"roboter-os-2026.09.1-headless.img.xz": "a" * 64})
    assert content == f"{'a' * 64}  roboter-os-2026.09.1-headless.img.xz\n"


def test_render_sha256sums_sorts_multiple_entries_by_filename():
    content = package_image.render_sha256sums({
        "roboter-os-2026.09.1-desktop.img.xz": "b" * 64,
        "roboter-os-2026.09.1-headless.img.xz": "a" * 64,
    })
    assert content == (
        f"{'b' * 64}  roboter-os-2026.09.1-desktop.img.xz\n"
        f"{'a' * 64}  roboter-os-2026.09.1-headless.img.xz\n"
    )


def test_render_sha256sums_rejects_invalid_hash_or_empty_input():
    with pytest.raises(package_image.PackageError):
        package_image.render_sha256sums({})
    with pytest.raises(package_image.PackageError):
        package_image.render_sha256sums({"image.img.xz": "not-a-hash"})


def test_write_manifest_accepts_custom_output_name_for_github_assets(tmp_path, monkeypatch):
    source = tmp_path / "sample.img.xz"
    image_bytes = b"small test image"
    source.write_bytes(lzma.compress(image_bytes))
    output = tmp_path / "package"
    output.mkdir()
    metadata = {
        "status": "production",
        "version": "2026.09.1",
        "tag": "image-2026.09.1",
        "variant": "headless",
        "release_date": "2026-09-01",
        "image_file": "roboter-os-2026.09.1-headless.img.xz",
        "image_download_size": source.stat().st_size,
        "image_download_sha256": package_image.sha256_file(source),
        "extract_size": len(image_bytes),
        "extract_sha256": "1" * 64,
        "rpi_imager_commit": package_image.PIN["rpi_imager_commit"],
    }
    monkeypatch.setattr(package_image, "pinned_sources", lambda: (tmp_path / "schema", tmp_path / "catalog"))
    monkeypatch.setattr(package_image, "validate_manifest", lambda *args: None)
    (output / "package.json").write_text(json.dumps(metadata))
    (output / metadata["image_file"]).write_bytes(source.read_bytes())
    (output / "SHA256SUMS").write_text(
        f"{metadata['image_download_sha256']}  {metadata['image_file']}\n"
    )
    result = package_image.write_manifest(
        output,
        "https://github.com/kraeml/ros-pi-gen/releases/download/image-2026.09.1/",
        output_name="headless-os-list.json",
    )
    assert result.name == "headless-os-list.json"
    assert not (output / "os-list.json").exists()
    manifest = json.loads(result.read_text())
    entry = manifest["os_list"][0]
    assert entry["url"] == (
        "https://github.com/kraeml/ros-pi-gen/releases/download/image-2026.09.1/"
        "roboter-os-2026.09.1-headless.img.xz"
    )


def test_github_manifest_name_is_variant_prefixed():
    assert package_image.github_manifest_name("headless") == "headless-os-list.json"
    assert package_image.github_manifest_name("desktop") == "desktop-os-list.json"
    with pytest.raises(package_image.PackageError):
        package_image.github_manifest_name("unknown")


def test_write_github_manifest_uses_variant_prefixed_filename(tmp_path, monkeypatch):
    source = tmp_path / "sample.img.xz"
    image_bytes = b"small test image"
    source.write_bytes(lzma.compress(image_bytes))
    output = tmp_path / "package"
    output.mkdir()
    metadata = {
        "status": "production",
        "version": "2026.09.1",
        "tag": "image-2026.09.1",
        "variant": "headless",
        "release_date": "2026-09-01",
        "image_file": "roboter-os-2026.09.1-headless.img.xz",
        "image_download_size": source.stat().st_size,
        "image_download_sha256": package_image.sha256_file(source),
        "extract_size": len(image_bytes),
        "extract_sha256": "1" * 64,
        "rpi_imager_commit": package_image.PIN["rpi_imager_commit"],
    }
    monkeypatch.setattr(package_image, "pinned_sources", lambda: (tmp_path / "schema", tmp_path / "catalog"))
    monkeypatch.setattr(package_image, "validate_manifest", lambda *args: None)
    (output / "package.json").write_text(json.dumps(metadata))
    (output / metadata["image_file"]).write_bytes(source.read_bytes())
    (output / "SHA256SUMS").write_text(
        f"{metadata['image_download_sha256']}  {metadata['image_file']}\n"
    )
    result = package_image.write_github_manifest(
        output,
        "https://github.com/kraeml/ros-pi-gen/releases/download/image-2026.09.1/",
    )
    assert result.name == "headless-os-list.json"


@pytest.mark.parametrize("base_url", ["", "ftp://example.org/", "http://localhost:80/?x=1", "http://localhost/#frag"])
def test_local_renderer_rejects_invalid_base_url(tmp_path, base_url):
    metadata = {
        "status": "local-test",
        "variant": "headless",
        "image_file": "image.img.xz",
        "version": None,
        "release_date": "2026-09-01",
    }
    with pytest.raises(package_image.PackageError):
        package_image.render_manifest(metadata, base_url)


@pytest.mark.parametrize(
    "tag,kind,timestamp,valid,expected",
    [
        ("image-2026.10.1", "tag", "2026-09-30T23:30:00-01:00", True, "2026-10-01"),
        ("image-2026.09.1", "commit", "2026-09-26T00:00:00+00:00", False, None),
        ("image-2026.13.1", "tag", "2026-09-26T00:00:00+00:00", False, None),
        ("image-2026.09.0", "tag", "2026-09-26T00:00:00+00:00", False, None),
        ("image-2026.10.1-test", "tag", "2026-09-30T23:30:00-01:00", True, "2026-10-01"),
    ],
)
def test_current_tag_validates_annotated_calver(monkeypatch, tag, kind, timestamp, valid, expected):
    outputs = iter([tag + "\n", kind + "\n", str(int(dt.datetime.fromisoformat(timestamp).timestamp())) + "\n"])

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, next(outputs), "")

    monkeypatch.setattr(package_image.subprocess, "run", fake_run)
    if valid:
        _, tag_date, version = package_image.current_tag()
        assert tag_date.isoformat() == expected
        assert version == tag
    else:
        with pytest.raises(package_image.PackageError):
            package_image.current_tag()


def test_build_info_rejects_ambiguous_artifacts(tmp_path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / "image_2026-09-26-raspberrypi-trixie-custom-lite.img.xz").touch()
    (deploy / "image_2026-09-27-raspberrypi-trixie-custom-lite.img.xz").touch()
    with pytest.raises(package_image.PackageError, match="genau ein"):
        package_image.build_info(next(deploy.glob("*.xz")), deploy, "headless")


def test_pinned_sources_match_declared_hashes():
    schema_path, catalog_path = package_image.pinned_sources()
    assert package_image.sha256_file(schema_path) == package_image.PIN["schema_sha256"]
    # Nur der stabile imager.devices-Teilblock ist gepinnt, nicht die
    # Gesamtdatei (die enthält eine täglich wechselnde OS-Liste).
    catalog = json.loads(catalog_path.read_text())
    devices_payload = json.dumps(catalog["imager"]["devices"], sort_keys=True, ensure_ascii=False).encode()
    import hashlib
    assert hashlib.sha256(devices_payload).hexdigest() == package_image.PIN["device_catalog_devices_sha256"]


def test_manifest_enforces_schema_and_device_tag_rules():
    schema_path, catalog_path = package_image.pinned_sources()
    valid = {
        "os_list": [{
            "name": "Roboter-OS 2026.09.1 (Headless)",
            "description": "Test",
            "icon": "http://127.0.0.1:8000/roboter-os.svg",
            "url": "http://127.0.0.1:8000/roboter-os-2026.09.1-headless.img.xz",
            "extract_size": 1,
            "extract_sha256": "0" * 64,
            "image_download_size": 1,
            "image_download_sha256": "0" * 64,
            "release_date": "2026-09-26",
            "devices": ["pi3-64bit", "pi4-64bit", "pi5-64bit"],
            "init_format": "cloudinit-rpi",
        }]
    }
    package_image.validate_manifest(valid, schema_path, catalog_path)
    invalid = json.loads(json.dumps(valid))
    invalid["os_list"][0]["devices"] = ["pi3", "pi4", "pi5"]
    with pytest.raises(package_image.PackageError, match="Gerätetags"):
        package_image.validate_manifest(invalid, schema_path, catalog_path)


def test_release_skip_stage_is_explicit():
    makefile = (ROOT / "Makefile").read_text()
    pigen_build = (ROOT / "pi-gen/build.sh").read_text()
    assert "touch $(STAGE_DIR)/04-user-data/SKIP" in makefile
    assert "RELEASE_BUILD" in makefile
    assert '[ ! -f "${SUB_STAGE_DIR}/SKIP" ]' in pigen_build
