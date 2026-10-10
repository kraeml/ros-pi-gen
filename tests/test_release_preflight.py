from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import package_image
import release_preflight


def test_suggest_next_tag_uses_next_patch_in_utc_month():
    tag = release_preflight.suggest_next_tag(
        now=dt.datetime(2026, 10, 31, 23, 30, tzinfo=dt.timezone(dt.timedelta(hours=-2))),
        local_tags=["image-2026.10.2", "image-2026.10.5-test", "image-2026.09.9"],
        remote_tags=["image-2026.10.4", "image-2026.10.10", "image-2026.11.1"],
    )
    assert tag == "image-2026.11.2"


def test_suggest_next_tag_starts_at_patch_one_when_month_is_unused():
    tag = release_preflight.suggest_next_tag(
        now=dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc),
        local_tags=["image-2026.09.9"],
        remote_tags=["image-2026.09.10"],
    )
    assert tag == "image-2026.10.1"


def test_suggest_next_tag_ignores_invalid_patch_zero():
    tag = release_preflight.suggest_next_tag(
        now=dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc),
        local_tags=["image-2026.10.0", "image-2026.10.2"],
        remote_tags=[],
    )
    assert tag == "image-2026.10.3"


def test_candidate_preflight_skips_checkout_tag_validation(monkeypatch):
    calls = []
    monkeypatch.setattr(
        release_preflight,
        "validate_tag",
        lambda *args: pytest.fail("Kandidat darf keinen bereits existierenden lokalen Tag verlangen"),
    )
    monkeypatch.setattr(release_preflight, "ensure_local_tag_not_pushed", lambda tag, remote: calls.append("remote"))
    monkeypatch.setattr(release_preflight, "ensure_github_release_absent", lambda tag: calls.append("github"))
    release_preflight.run_preflight("image-2026.10.4", mode="local", candidate=True)
    assert calls == ["remote", "github"]


def test_candidate_preflight_rejects_invalid_tag_components():
    with pytest.raises(release_preflight.PreflightError, match="Ungültiger vorgeschlagener"):
        release_preflight.validate_candidate("image-2026.13.0")


def test_validate_tag_uses_shared_annotated_tag_validator(monkeypatch):
    monkeypatch.setattr(package_image, "current_tag", lambda: ("image-2026.10.4", None, "image-2026.10.4"))
    release_preflight.validate_tag("image-2026.10.4")


def test_validate_tag_rejects_invalid_format_before_git(monkeypatch):
    monkeypatch.setattr(
        package_image,
        "current_tag",
        lambda: pytest.fail("Git-Tag-Prüfung darf bei ungültigem Format nicht starten"),
    )
    with pytest.raises(release_preflight.PreflightError, match="Ungültiger Produktionstag"):
        release_preflight.validate_tag("image-2026.10.0-test")


def test_validate_tag_rejects_tag_not_at_checkout(monkeypatch):
    monkeypatch.setattr(package_image, "current_tag", lambda: ("image-2026.10.3", None, "image-2026.10.3"))
    with pytest.raises(release_preflight.PreflightError, match="zeigt nicht exakt"):
        release_preflight.validate_tag("image-2026.10.4")


def test_validate_tag_checks_expected_commit(monkeypatch):
    monkeypatch.setattr(package_image, "current_tag", lambda: ("image-2026.10.4", None, "image-2026.10.4"))
    monkeypatch.setattr(
        release_preflight,
        "run_git",
        lambda args: subprocess.CompletedProcess(args, 0, "actual\n", ""),
    )
    with pytest.raises(release_preflight.PreflightError, match="stimmt nicht"):
        release_preflight.validate_tag("image-2026.10.4", "expected")


def test_remote_tag_check_rejects_existing_tag(monkeypatch):
    monkeypatch.setattr(
        release_preflight.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "abc\trefs/tags/image-2026.10.4\n", ""),
    )
    with pytest.raises(release_preflight.PreflightError, match="existiert bereits"):
        release_preflight.ensure_local_tag_not_pushed("image-2026.10.4", "origin")


def test_remote_tag_check_fails_closed_on_network_error(monkeypatch):
    monkeypatch.setattr(
        release_preflight.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 128, "", "network error"),
    )
    with pytest.raises(release_preflight.PreflightError, match="nicht sicher geprüft"):
        release_preflight.ensure_local_tag_not_pushed("image-2026.10.4", "origin")


def test_github_check_rejects_existing_draft(monkeypatch):
    payload = '[[{"tag_name":"image-2026.10.4","draft":true,"prerelease":false}]]'
    monkeypatch.setattr(
        release_preflight.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, payload, ""),
    )
    with pytest.raises(release_preflight.PreflightError, match="existiert bereits"):
        release_preflight.ensure_github_release_absent("image-2026.10.4")


@pytest.mark.parametrize("details", ["HTTP 401", "network timeout", "gh: authentication required"])
def test_github_check_fails_closed_on_unrecognized_errors(monkeypatch, details):
    monkeypatch.setattr(
        release_preflight.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", details),
    )
    with pytest.raises(release_preflight.PreflightError, match="nicht sicher geprüft"):
        release_preflight.ensure_github_release_absent("image-2026.10.4")


def test_github_check_accepts_empty_release_list(monkeypatch):
    monkeypatch.setattr(
        release_preflight.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "[[]]", ""),
    )
    release_preflight.ensure_github_release_absent("image-2026.10.4")


def test_local_preflight_checks_tag_and_github_only(monkeypatch):
    calls = []
    monkeypatch.setattr(release_preflight, "validate_tag", lambda tag, expected_commit: calls.append("tag"))
    monkeypatch.setattr(release_preflight, "ensure_local_tag_not_pushed", lambda tag, remote: calls.append("remote"))
    monkeypatch.setattr(release_preflight, "ensure_github_release_absent", lambda tag: calls.append("github"))
    release_preflight.run_preflight("image-2026.10.4", mode="local")
    assert calls == ["tag", "remote", "github"]


def test_ci_preflight_checks_tag_and_github_only(monkeypatch):
    calls = []
    monkeypatch.setattr(release_preflight, "validate_tag", lambda tag, expected_commit: calls.append("tag"))
    monkeypatch.setattr(release_preflight, "ensure_github_release_absent", lambda tag: calls.append("github"))
    release_preflight.run_preflight("image-2026.10.4", mode="ci")
    assert calls == ["tag", "github"]
