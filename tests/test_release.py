from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import release
import release_preflight


def test_release_requires_clean_worktree(monkeypatch):
    monkeypatch.setattr(release, "run_git", lambda args: subprocess.CompletedProcess(args, 0, " M tracked\n", ""))
    with pytest.raises(release.ReleaseError, match="nicht sauber"):
        release.ensure_clean_worktree()


def test_release_cancelled_confirmation_does_not_create_tag(monkeypatch):
    calls = []
    monkeypatch.setattr(release, "ensure_release_branch", lambda: calls.append("branch"))
    monkeypatch.setattr(release, "ensure_clean_worktree", lambda: calls.append("clean"))
    monkeypatch.setattr(release, "run_git", lambda args: subprocess.CompletedProcess(args, 0, "head", ""))
    monkeypatch.setattr(release_preflight, "validate_candidate", lambda tag: calls.append("validate-candidate"))
    monkeypatch.setattr(release, "ensure_local_tag_absent", lambda tag: calls.append("local-tag-check"))
    monkeypatch.setattr(
        release_preflight,
        "run_preflight",
        lambda *args, **kwargs: calls.append("preflight"),
    )
    with pytest.raises(release.ReleaseError, match="Bestätigung stimmt nicht"):
        release.run_release(
            "image-2026.10.4",
            confirm=lambda prompt: "no",
        )
    assert calls == ["branch", "clean", "validate-candidate", "local-tag-check", "preflight"]


def test_release_creates_annotated_tag_rechecks_and_pushes_only_that_tag(monkeypatch):
    calls = []
    monkeypatch.setattr(release, "ensure_release_branch", lambda: calls.append("branch"))
    monkeypatch.setattr(release, "ensure_clean_worktree", lambda: calls.append("clean"))
    monkeypatch.setattr(release_preflight, "validate_candidate", lambda tag: calls.append(("candidate", tag)))
    monkeypatch.setattr(release, "ensure_local_tag_absent", lambda tag: calls.append(("local-tag", tag)))
    monkeypatch.setattr(
        release_preflight,
        "run_preflight",
        lambda tag, **kwargs: calls.append(("preflight", tag, kwargs.get("candidate", False))),
    )
    git_calls = []

    def fake_run_git(args):
        git_calls.append(args)
        return subprocess.CompletedProcess(args, 0, "same-head" if args == ["rev-parse", "HEAD"] else "", "")

    monkeypatch.setattr(release, "run_git", fake_run_git)

    tag = release.run_release(
        "image-2026.10.4",
        remote="origin",
        confirm=lambda prompt: "PUBLISH image-2026.10.4",
    )

    assert tag == "image-2026.10.4"
    assert calls == [
        "branch",
        "clean",
        ("candidate", tag),
        ("local-tag", tag),
        ("preflight", tag, True),
        "clean",
        ("preflight", tag, False),
    ]
    assert git_calls == [
        ["rev-parse", "HEAD"],
        ["rev-parse", "HEAD"],
        ["tag", "-a", tag, "-m", "Roboter-OS 2026.10.4"],
        ["push", "origin", tag],
    ]


def test_release_suggests_tag_when_not_provided(monkeypatch):
    calls = []
    monkeypatch.setattr(release, "ensure_release_branch", lambda: None)
    monkeypatch.setattr(release, "ensure_clean_worktree", lambda: None)
    monkeypatch.setattr(release_preflight, "suggest_next_tag", lambda remote: "image-2026.10.4")
    monkeypatch.setattr(release_preflight, "validate_candidate", lambda tag: calls.append(tag))
    monkeypatch.setattr(release, "ensure_local_tag_absent", lambda tag: None)
    monkeypatch.setattr(release_preflight, "run_preflight", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        release,
        "run_git",
        lambda args: subprocess.CompletedProcess(args, 0, "", ""),
    )

    result = release.run_release(None, confirm=lambda prompt: "PUBLISH image-2026.10.4")

    assert result == "image-2026.10.4"
    assert calls == ["image-2026.10.4"]
