#!/usr/bin/env python3

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable

import release_preflight


class ReleaseError(RuntimeError):
    pass


def run_git(args: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if result.returncode:
        details = result.stderr.strip() or result.stdout.strip()
        raise ReleaseError(f"git {' '.join(args)} fehlgeschlagen: {details}")
    return result


def ensure_release_branch() -> None:
    branch = run_git(["branch", "--show-current"]).stdout.strip()
    if branch != "develop":
        raise ReleaseError(f"Release muss auf develop gestartet werden, aktueller Branch ist {branch or '(detached HEAD)'}")


def ensure_clean_worktree() -> None:
    status = run_git(["status", "--porcelain", "--untracked-files=all"]).stdout
    if status:
        raise ReleaseError("Arbeitsverzeichnis ist nicht sauber; Änderungen zuerst committen oder entfernen")


def ensure_local_tag_absent(tag: str) -> None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        raise ReleaseError(f"Lokaler Tag {tag} existiert bereits")
    if result.returncode != 1:
        raise ReleaseError(result.stderr.strip() or f"Lokaler Tag {tag} konnte nicht sicher geprüft werden")


def run_release(
    tag: str | None,
    *,
    remote: str = "origin",
    confirm: Callable[[str], str] = input,
) -> str:
    ensure_release_branch()
    ensure_clean_worktree()
    initial_head = run_git(["rev-parse", "HEAD"]).stdout.strip()
    release_tag = tag or release_preflight.suggest_next_tag(remote=remote)
    release_preflight.validate_candidate(release_tag)
    ensure_local_tag_absent(release_tag)
    release_preflight.run_preflight(release_tag, mode="local", remote=remote, candidate=True)

    print(f"Vorgeschlagener Produktionstag: {release_tag}")
    confirmation = confirm(f"Gate 4 bestätigen: exakt 'PUBLISH {release_tag}' eingeben: ")
    if confirmation != f"PUBLISH {release_tag}":
        raise ReleaseError("Gate-4-Bestätigung stimmt nicht; Tag wurde nicht erstellt")

    ensure_clean_worktree()
    current_head = run_git(["rev-parse", "HEAD"]).stdout.strip()
    if current_head != initial_head:
        raise ReleaseError("HEAD hat sich während der Bestätigung geändert; Tag wurde nicht erstellt")

    version = release_tag.removeprefix("image-")
    run_git(["tag", "-a", release_tag, "-m", f"Roboter-OS {version}"])
    release_preflight.run_preflight(release_tag, mode="local", remote=remote)
    run_git(["push", remote, release_tag])
    return release_tag


def main() -> int:
    tag = os.environ.get("RELEASE_TAG") or None
    remote = os.environ.get("RELEASE_REMOTE", "origin")
    previous_ssh_command = os.environ.get("GIT_SSH_COMMAND")
    os.environ["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes"
    try:
        pushed_tag = run_release(tag, remote=remote)
    except (ReleaseError, release_preflight.PreflightError, OSError, subprocess.CalledProcessError) as error:
        print(f"Release abgebrochen: {error}", file=sys.stderr)
        return 1
    finally:
        if previous_ssh_command is None:
            os.environ.pop("GIT_SSH_COMMAND", None)
        else:
            os.environ["GIT_SSH_COMMAND"] = previous_ssh_command
    print(f"Tag gepusht: {pushed_tag}")
    print("Der Push startet den Produktionsworkflow mit Build und Veröffentlichung.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
