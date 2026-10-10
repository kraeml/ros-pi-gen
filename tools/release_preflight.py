#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import package_image


REPOSITORY = "kraeml/ros-pi-gen"
TAG_PATTERN = re.compile(r"^image-\d{4}\.\d{2}\.\d+$")


class PreflightError(RuntimeError):
    pass


def run_git(args: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise PreflightError(result.stderr.strip() or f"Git fehlgeschlagen: {args}")
    return result


def suggest_next_tag(
    *,
    now: dt.datetime | None = None,
    local_tags: list[str] | None = None,
    remote_tags: list[str] | None = None,
    remote: str = "origin",
) -> str:
    current = now or dt.datetime.now(dt.timezone.utc)
    current = current.astimezone(dt.timezone.utc)
    prefix = f"image-{current.year:04d}.{current.month:02d}."
    tag_sets = []
    if local_tags is None:
        tag_sets.append(run_git(["tag", "--list", f"{prefix}*"]).stdout.splitlines())
    else:
        tag_sets.append(local_tags)
    if remote_tags is None:
        remote_refs = run_git(["ls-remote", "--tags", "--refs", remote, f"refs/tags/{prefix}*"])
        tag_sets.append([line.split("refs/tags/", 1)[1] for line in remote_refs.stdout.splitlines() if "refs/tags/" in line])
    else:
        tag_sets.append(remote_tags)

    patches = []
    for tags in tag_sets:
        for tag in tags:
            match = re.fullmatch(rf"{re.escape(prefix)}(\d+)", tag.strip())
            if match:
                patches.append(int(match.group(1)))
    return f"{prefix}{max(patches, default=0) + 1}"


def validate_tag(tag: str, expected_commit: str | None = None) -> None:
    if not TAG_PATTERN.fullmatch(tag):
        raise PreflightError(f"Ungültiger Produktionstag: {tag!r}; erwartet image-YYYY.MM.PATCH")
    try:
        actual_tag, _, _ = package_image.current_tag()
    except (package_image.PackageError, subprocess.CalledProcessError) as error:
        raise PreflightError(str(error)) from error
    if actual_tag != tag:
        raise PreflightError(f"Erwarteter Tag {tag} zeigt nicht exakt auf den aktuellen Checkout (gefunden: {actual_tag!r})")
    if expected_commit:
        checkout = run_git(["rev-parse", "HEAD"]).stdout.strip()
        if checkout != expected_commit:
            raise PreflightError(
                f"Checkout {checkout} stimmt nicht mit erwartetem Commit {expected_commit} überein"
            )


def validate_candidate(tag: str) -> None:
    match = re.fullmatch(r"image-(\d{4})\.(\d{2})\.(\d+)", tag)
    if not match or not 1 <= int(match.group(2)) <= 12 or int(match.group(3)) < 1:
        raise PreflightError(f"Ungültiger vorgeschlagener Produktionstag: {tag!r}")


def ensure_local_tag_not_pushed(tag: str, remote: str) -> None:
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--refs", remote, f"refs/tags/{tag}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        raise PreflightError(f"Tag {tag} existiert bereits auf Remote {remote}")
    if result.returncode != 2:
        raise PreflightError(
            f"Remote-Tag {tag} konnte nicht sicher geprüft werden: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


def ensure_github_release_absent(tag: str) -> None:
    result = subprocess.run(
        ["gh", "api", "--paginate", "--slurp", f"repos/{REPOSITORY}/releases?per_page=100"],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        details = (result.stderr or result.stdout).strip()
        raise PreflightError(f"GitHub-Releases konnten nicht sicher geprüft werden: {details}")
    try:
        pages = json.loads(result.stdout)
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise TypeError("unerwartete Antwortstruktur")
        releases = [release for page in pages for release in page]
        if any(not isinstance(release, dict) for release in releases):
            raise TypeError("unerwarteter Release-Eintrag")
    except (json.JSONDecodeError, TypeError) as error:
        raise PreflightError("GitHub-API lieferte ungültiges JSON für den Release-Check") from error
    matches = [release for release in releases if release.get("tag_name") == tag]
    if matches:
        release = matches[0]
        raise PreflightError(
            f"GitHub-Release für {tag} existiert bereits "
            f"(draft={release.get('draft')}, prerelease={release.get('prerelease')})"
        )


def run_preflight(
    tag: str,
    *,
    mode: str,
    remote: str = "origin",
    expected_commit: str | None = None,
    candidate: bool = False,
) -> None:
    if candidate:
        validate_candidate(tag)
    else:
        validate_tag(tag, expected_commit)
    if mode == "local":
        ensure_local_tag_not_pushed(tag, remote)
    elif mode != "ci":
        raise PreflightError(f"Unbekannter Preflight-Modus: {mode}")
    ensure_github_release_absent(tag)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Werkzeuge für Produktions-Releases")
    parser.add_argument("--tag")
    parser.add_argument("--suggest-version", action="store_true")
    parser.add_argument("--candidate", action="store_true")
    parser.add_argument("--mode", choices=("local", "ci"), default="local")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--expected-commit")
    args = parser.parse_args()
    if args.suggest_version == bool(args.tag):
        parser.error("genau eines von --suggest-version oder --tag ist erforderlich")
    if args.candidate and (args.suggest_version or not args.tag):
        parser.error("--candidate erfordert einen konkreten --tag und ist nicht mit --suggest-version kombinierbar")
    try:
        if args.suggest_version:
            print(suggest_next_tag(remote=args.remote))
            return 0
        run_preflight(
            args.tag,
            mode=args.mode,
            remote=args.remote,
            expected_commit=args.expected_commit,
            candidate=args.candidate,
        )
    except (PreflightError, OSError, subprocess.CalledProcessError) as error:
        print(f"Release-Preflight abgebrochen: {error}", file=sys.stderr)
        return 1
    print(f"Release-Preflight erfolgreich: {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
