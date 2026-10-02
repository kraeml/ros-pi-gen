from __future__ import annotations

import hashlib
import json
import lzma
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import github_release
import package_image


def make_production_package(directory: Path, version: str = "2026.09.9") -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    image_name = f"roboter-os-{version}-headless.img.xz"
    image_bytes = lzma.compress(b"synthetic github release test content")
    (directory / image_name).write_bytes(image_bytes)
    digest = hashlib.sha256(image_bytes).hexdigest()
    metadata = {
        "schema_version": 1,
        "status": "production",
        "version": version,
        "tag": f"image-{version}",
        "variant": "headless",
        "release_date": "2026-09-20",
        "image_file": image_name,
        "image_download_size": len(image_bytes),
        "image_download_sha256": digest,
        "extract_size": 4096,
        "extract_sha256": "a" * 64,
        "rpi_imager_commit": package_image.PIN["rpi_imager_commit"],
    }
    (directory / "package.json").write_text(json.dumps(metadata, indent=2))
    (directory / "SHA256SUMS").write_text(package_image.render_sha256sums({image_name: digest}))
    (directory / "roboter-os.svg").write_bytes((ROOT / "assets/roboter-os.svg").read_bytes())
    manifest = package_image.render_manifest(
        metadata, "https://hel1.your-objectstorage.com/ros-pi-gen-images/ros-pi-gen/releases/" + version + "/"
    )
    (directory / "os-list.json").write_text(json.dumps(manifest, indent=2))
    return metadata


def test_load_production_metadata_delegates_to_publish_s3_validation(tmp_path):
    package = tmp_path / "release"
    expected = make_production_package(package)
    metadata = github_release.load_production_metadata(package)
    assert metadata == expected


def test_load_production_metadata_rejects_test_status(tmp_path, monkeypatch):
    package = tmp_path / "release"
    metadata = make_production_package(package)
    metadata["status"] = "test"
    (package / "package.json").write_text(json.dumps(metadata))
    with pytest.raises(github_release.GithubReleaseError):
        github_release.load_production_metadata(package)


def test_github_asset_paths_renders_manifest_if_missing(tmp_path):
    package = tmp_path / "release"
    metadata = make_production_package(package)
    assert not (package / "headless-os-list.json").exists()
    paths = github_release.github_asset_paths(package, metadata)
    assert paths["manifest"].name == "headless-os-list.json"
    assert paths["manifest"].is_file()
    assert paths["image"].name == metadata["image_file"]
    assert paths["sums"].name == "SHA256SUMS"
    manifest = json.loads(paths["manifest"].read_text())
    entry = manifest["os_list"][0]
    assert entry["url"].startswith(f"https://github.com/{github_release.REPO}/releases/download/image-")


def test_github_asset_paths_reuses_existing_manifest(tmp_path):
    package = tmp_path / "release"
    metadata = make_production_package(package)
    manifest_path = package / "headless-os-list.json"
    manifest_path.write_text(json.dumps({"os_list": [{"sentinel": True}]}))
    paths = github_release.github_asset_paths(package, metadata)
    # Nicht überschrieben, da bereits vorhanden.
    assert json.loads(paths["manifest"].read_text())["os_list"][0].get("sentinel") is True


def test_github_asset_paths_requires_image_file(tmp_path):
    package = tmp_path / "release"
    metadata = make_production_package(package)
    (package / metadata["image_file"]).unlink()
    with pytest.raises(github_release.GithubReleaseError, match="Image fehlt"):
        github_release.github_asset_paths(package, metadata)


def test_check_asset_sizes_rejects_oversized_asset(tmp_path, monkeypatch):
    package = tmp_path / "release"
    metadata = make_production_package(package)
    paths = github_release.github_asset_paths(package, metadata)
    monkeypatch.setattr(github_release, "GITHUB_ASSET_SIZE_LIMIT", 10)
    with pytest.raises(github_release.GithubReleaseError, match="Assetgrößenlimit"):
        github_release.check_asset_sizes(paths)


def test_create_draft_release_rejects_test_suffix_version(tmp_path, monkeypatch):
    package = tmp_path / "release"
    metadata = make_production_package(package)
    metadata["version"] = "2026.09.9-test"
    with pytest.raises(github_release.GithubReleaseError, match="ohne -test-Suffix"):
        github_release.create_draft_release(package, metadata)


def test_create_draft_release_rejects_non_headless_variant(tmp_path):
    package = tmp_path / "release"
    metadata = make_production_package(package)
    metadata["variant"] = "desktop"
    with pytest.raises(github_release.GithubReleaseError, match="headless"):
        github_release.create_draft_release(package, metadata)


def test_create_draft_release_invokes_gh_with_expected_flags(tmp_path, monkeypatch):
    package = tmp_path / "release"
    metadata = make_production_package(package)
    captured = {}

    def fake_run_gh(args, *, capture=True):
        captured["args"] = args
        return github_release.subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(github_release, "run_gh", fake_run_gh)
    tag = github_release.create_draft_release(package, metadata)
    assert tag == metadata["tag"]
    args = captured["args"]
    assert args[0:3] == ["release", "create", metadata["tag"]]
    assert "--draft" in args
    assert "--verify-tag" in args
    assert "--latest=false" in args
    # Alle drei Assets werden übergeben.
    asset_args = [arg for arg in args if arg.endswith((".img.xz", "os-list.json", "SHA256SUMS"))]
    assert len(asset_args) == 3


def test_verify_draft_assets_rejects_non_draft(monkeypatch):
    def fake_run_gh(args, *, capture=True):
        payload = json.dumps({"isDraft": False, "assets": []})
        return github_release.subprocess.CompletedProcess(args, 0, payload, "")

    monkeypatch.setattr(github_release, "run_gh", fake_run_gh)
    with pytest.raises(github_release.GithubReleaseError, match="kein Draft mehr"):
        github_release.verify_draft_assets("image-2026.09.9", {"a"})


def test_verify_draft_assets_rejects_mismatched_names(monkeypatch):
    def fake_run_gh(args, *, capture=True):
        payload = json.dumps({"isDraft": True, "assets": [{"name": "unexpected.txt", "size": 10}]})
        return github_release.subprocess.CompletedProcess(args, 0, payload, "")

    monkeypatch.setattr(github_release, "run_gh", fake_run_gh)
    with pytest.raises(github_release.GithubReleaseError, match="stimmen nicht"):
        github_release.verify_draft_assets("image-2026.09.9", {"expected.txt"})


def test_verify_draft_assets_rejects_zero_size_asset(monkeypatch):
    def fake_run_gh(args, *, capture=True):
        payload = json.dumps({"isDraft": True, "assets": [{"name": "expected.txt", "size": 0}]})
        return github_release.subprocess.CompletedProcess(args, 0, payload, "")

    monkeypatch.setattr(github_release, "run_gh", fake_run_gh)
    with pytest.raises(github_release.GithubReleaseError, match="plausible Größe"):
        github_release.verify_draft_assets("image-2026.09.9", {"expected.txt"})


def test_verify_draft_assets_accepts_matching_assets(monkeypatch):
    def fake_run_gh(args, *, capture=True):
        payload = json.dumps({
            "isDraft": True,
            "assets": [
                {"name": "roboter-os-2026.09.9-headless.img.xz", "size": 1000},
                {"name": "headless-os-list.json", "size": 500},
                {"name": "SHA256SUMS", "size": 100},
            ],
        })
        return github_release.subprocess.CompletedProcess(args, 0, payload, "")

    monkeypatch.setattr(github_release, "run_gh", fake_run_gh)
    github_release.verify_draft_assets(
        "image-2026.09.9",
        {"roboter-os-2026.09.9-headless.img.xz", "headless-os-list.json", "SHA256SUMS"},
    )


def test_publish_release_invokes_gh_edit_with_latest_flag(monkeypatch):
    captured = {}

    def fake_run_gh(args, *, capture=True):
        captured["args"] = args
        return github_release.subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(github_release, "run_gh", fake_run_gh)
    github_release.publish_release("image-2026.09.9")
    args = captured["args"]
    assert args == ["release", "edit", "image-2026.09.9", "--draft=false", "--latest"]


def test_check_public_asset_uses_curl_with_redirect_follow(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return github_release.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(github_release.subprocess, "run", fake_run)
    github_release.check_public_asset("image-2026.09.9", "roboter-os-2026.09.9-headless.img.xz")
    command = captured["command"]
    assert "--location" in command
    assert command[-1] == (
        f"https://github.com/{github_release.REPO}/releases/download/"
        "image-2026.09.9/roboter-os-2026.09.9-headless.img.xz"
    )


def test_check_public_asset_raises_on_curl_failure(monkeypatch):
    def fake_run(command, **kwargs):
        return github_release.subprocess.CompletedProcess(command, 22, "", "404 Not Found")

    monkeypatch.setattr(github_release.subprocess, "run", fake_run)
    with pytest.raises(github_release.GithubReleaseError, match="nicht bestätigt"):
        github_release.check_public_asset("image-2026.09.9", "missing.img.xz")


def test_run_gh_raises_github_release_error_on_failure(monkeypatch):
    def fake_run(command, **kwargs):
        return github_release.subprocess.CompletedProcess(command, 1, "", "some gh error")

    monkeypatch.setattr(github_release.subprocess, "run", fake_run)
    with pytest.raises(github_release.GithubReleaseError, match="gh-Aufruf fehlgeschlagen"):
        github_release.run_gh(["release", "view", "image-2026.09.9"])
