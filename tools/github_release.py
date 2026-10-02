#!/usr/bin/env python3
"""GitHub-Release-Adapter für Produktions-Images (Etappe 4, AGENTS.md).

Dünner Wrapper um die `gh`-CLI (nutzt lokal die vorhandene `gh auth`-Sitzung,
in CI das automatisch bereitgestellte `GITHUB_TOKEN`). Macht KEINE S3-Calls
und berührt KEINE lokalen Paketierungsschritte — erwartet ein fertiges
Headless-only-Produktionspaket (siehe tools/merge_test_packages.py,
Status production) als Eingabe.

Reihenfolge laut AGENTS.md (Etappe 4):
  1. Draft-Release mit allen Assets erstellen (create_draft_release).
     Draft-Assets werden NUR über die authentifizierte API geprüft
     (verify_draft_assets), NIEMALS anonym abgerufen.
  2. Außerhalb dieses Skripts: S3-Produktions-Upload durchführen und
     verifizieren (tools/publish_s3.py, publish_production_package()).
  3. Erst nach erfolgreichem S3-Update: Draft veröffentlichen
     (publish_release) — damit `latest` nicht vor dem maßgeblichen
     S3-Stand umspringt.
  4. Danach: anonyme GitHub-Asset-URL/Redirect-Prüfung (check_public_asset),
     erst jetzt ist das Release öffentlich.

Scheitert Schritt 3 oder 4, bleibt der Draft (bzw. das veröffentlichte,
aber noch nicht extern verifizierte Release) stehen — keine automatische
Rückziehung (AGENTS.md: "Release nicht automatisch zurückziehen").
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import package_image

# Aktuelles GitHub-Assetgrößenlimit (verifiziert 2026-10-02 gegen
# https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases:
# "Each file included in a release must be under 2 GiB."). Vor jeder
# Veröffentlichung erneut gegen die tatsächliche Dokumentation prüfen
# (AGENTS.md: "aktuelles GitHub-Assetgrößenlimit ... zum
# Umsetzungszeitpunkt verifizieren").
GITHUB_ASSET_SIZE_LIMIT = 2 * 1024 * 1024 * 1024

REPO = "kraeml/ros-pi-gen"
PRODUCTION_VERSION_PATTERN = re.compile(r"^(\d{4})\.(\d{2})\.(\d+)$")


class GithubReleaseError(RuntimeError):
    pass


def run_gh(args: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    command = ["gh", *args, "--repo", REPO]
    result = subprocess.run(command, capture_output=capture, text=True)
    if result.returncode:
        details = (result.stderr or result.stdout or "").strip()
        raise GithubReleaseError(f"gh-Aufruf fehlgeschlagen ({result.returncode}): {details}")
    return result


def load_production_metadata(package_dir: Path) -> dict:
    """Lädt und validiert die Paketdaten eines Headless-only-
    Produktionspakets (Status production, kein -test-Suffix). Nutzt
    dieselbe Validierung wie der S3-Produktionspfad (publish_s3.py), damit
    GitHub- und S3-Veröffentlichung garantiert vom selben, einmal geprüften
    Paket ausgehen (AGENTS.md: "Hashes und Größen werden einmal im Paket
    erzeugt")."""
    sys.path.insert(0, str(ROOT / "tools"))
    import publish_s3

    try:
        metadata = publish_s3.validate_production_package(package_dir)
    except publish_s3.PublishError as error:
        raise GithubReleaseError(f"Produktionspaket ist ungültig: {error}") from error
    return metadata


def github_asset_paths(package_dir: Path, metadata: dict) -> dict[str, Path]:
    """Liefert die für dieses Headless-only-Produktionsrelease
    erforderlichen GitHub-Release-Assets: Image, variantenspezifisches
    Manifest (headless-os-list.json), SHA256SUMS und das Imager-Icon
    (roboter-os.svg). Rendert das GitHub-Manifest frisch mit der
    versionierten Release-Asset-Basis-URL, falls es im Paketverzeichnis
    noch nicht vorliegt.

    Wird das Manifest neu gerendert, schreibt dies bewusst NICHT nach
    `package_dir`, sondern in ein eigenes temporäres Verzeichnis: Image,
    SHA256SUMS, Icon und os-list.json in `package_dir` müssen exakt dem
    Dateisatz entsprechen, den publish_s3.validate_production_package()
    erwartet (AGENTS.md-Reihenfolge: S3-Manifeste werden erst NACH dem
    GitHub-Draft-Schritt veröffentlicht, mit demselben, unveränderten
    Paketverzeichnis). Liegt das variantenspezifische Manifest bereits in
    `package_dir` (z. B. ein bewusst vorab platziertes Testartefakt),
    wird es unverändert von dort wiederverwendet statt neu gerendert.

    Das Icon wird bewusst als eigenständiges 4. GitHub-Asset mit
    hochgeladen (nicht nur auf S3): Das gepinnte Imager-V4-Schema verlangt
    pro Manifest-Eintrag ein Pflichtfeld 'icon' (HTTP(S)-URL,
    package_image.validate_manifest), und das GitHub-Release soll ein vom
    S3-Bucket unabhängiges, vollständig eigenständiges zweites
    Downloadziel sein -- ein auf die S3-Icon-URL verweisendes
    GitHub-Manifest würde diese Unabhängigkeit unterlaufen.
    package_image.write_github_manifest() rendert "icon" bereits relativ
    zur übergebenen Basis-URL (also als GitHub-Release-Asset-URL); als
    tatsächliches Icon-Asset wird dennoch die bereits im Paket
    vorhandene roboter-os.svg hochgeladen (identischer Inhalt wie die vom
    Renderer in sein eigenes Ausgabeverzeichnis kopierte Datei).
    """
    variant = metadata["variant"]
    version = metadata["version"]
    image_path = package_dir / metadata["image_file"]
    if not image_path.is_file():
        raise GithubReleaseError(f"Image fehlt im Paket: {image_path}")
    icon_path = package_dir / "roboter-os.svg"
    if not icon_path.is_file():
        raise GithubReleaseError(f"Imager-Icon fehlt im Paket: {icon_path}")
    manifest_name = package_image.github_manifest_name(variant)
    manifest_path = package_dir / manifest_name
    if not manifest_path.is_file():
        release_asset_base_url = (
            f"https://github.com/{REPO}/releases/download/image-{version}/"
        )
        manifest_output_dir = Path(tempfile.mkdtemp(prefix="ros-pi-gen-github-manifest-"))
        try:
            package_image.write_github_manifest(
                package_dir, release_asset_base_url, output_dir=manifest_output_dir
            )
        except package_image.PackageError as error:
            raise GithubReleaseError(f"GitHub-Manifest konnte nicht gerendert werden: {error}") from error
        manifest_path = manifest_output_dir / manifest_name
    sums_path = package_dir / "SHA256SUMS"
    if not sums_path.is_file():
        raise GithubReleaseError(f"SHA256SUMS fehlt im Paket: {sums_path}")
    return {
        "image": image_path,
        "manifest": manifest_path,
        "sums": sums_path,
        "icon": icon_path,
    }


def check_asset_sizes(paths: dict[str, Path]) -> None:
    """Bricht ab, falls ein Asset das aktuelle GitHub-Assetgrößenlimit
    überschreitet (AGENTS.md: "vor Veröffentlichung ... prüfen; bei
    Überschreitung stoppen und alternative Verteilung abstimmen")."""
    for label, path in paths.items():
        size = path.stat().st_size
        if size >= GITHUB_ASSET_SIZE_LIMIT:
            raise GithubReleaseError(
                f"Asset {label} ({path.name}) ist {size} Bytes groß und überschreitet "
                f"das GitHub-Assetgrößenlimit von {GITHUB_ASSET_SIZE_LIMIT} Bytes "
                "(2 GiB) -- Veröffentlichung gestoppt, alternative Verteilung nötig"
            )


def create_draft_release(package_dir: Path, metadata: dict) -> str:
    """Erstellt ein Draft-GitHub-Release für ein annotiertes
    Produktions-Tag (image-YYYY.MM.PATCH) mit allen Headless-only-Assets.
    Liefert den Tag-Namen zurück.

    Prereleases/Drafts dürfen `latest` nie verändern (`gh release create`
    markiert Drafts nie automatisch als latest) -- AGENTS.md: "Ihre
    Image-URLs müssen auf das jeweilige versionierte Release-Asset ...
    zeigen" und "latest darf nur auf ein vollständiges ... Produktions-
    release zeigen".
    """
    tag = metadata["tag"]
    version = metadata["version"]
    if not PRODUCTION_VERSION_PATTERN.fullmatch(version):
        raise GithubReleaseError(
            f"Produktions-Release verlangt eine Version ohne -test-Suffix, nicht {version!r}"
        )
    if metadata.get("variant") != "headless":
        raise GithubReleaseError(
            "Headless-only-Übergangsregelung: GitHub-Release akzeptiert ausschließlich "
            "die Variante headless, solange Desktop nicht bereitgestellt ist"
        )
    asset_paths = github_asset_paths(package_dir, metadata)
    check_asset_sizes(asset_paths)
    title = f"Roboter-OS {version} (Headless)"
    assets = [
        str(asset_paths["image"]),
        str(asset_paths["manifest"]),
        str(asset_paths["sums"]),
        str(asset_paths["icon"]),
    ]
    run_gh([
        "release", "create", tag,
        *assets,
        "--draft",
        "--verify-tag",
        "--latest=false",
        "--title", title,
        "--notes", f"Roboter-OS {version} — Headless-only-Produktionsrelease (Desktop folgt).",
    ])
    return tag


def verify_draft_assets(tag: str, expected_names: set[str]) -> None:
    """Prüft NUR über die authentifizierte GitHub-API Existenz und Größe
    der Draft-Assets -- niemals anonymer Abruf vor der Veröffentlichung
    (AGENTS.md: "Im Draft nur Existenz und Größe der Assets über die
    authentifizierte GitHub-API prüfen; Draft-Assets nicht anonym
    abrufen")."""
    result = run_gh(["release", "view", tag, "--json", "assets,isDraft"])
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise GithubReleaseError("gh release view lieferte ungültiges JSON") from error
    if not data.get("isDraft"):
        raise GithubReleaseError(f"Release {tag} ist kein Draft mehr -- Reihenfolge verletzt")
    actual_names = {asset["name"] for asset in data.get("assets", [])}
    if actual_names != expected_names:
        raise GithubReleaseError(
            f"Draft-Assets stimmen nicht mit den erwarteten Dateinamen überein: "
            f"erwartet {sorted(expected_names)}, vorhanden {sorted(actual_names)}"
        )
    for asset in data.get("assets", []):
        size = asset.get("size")
        if not isinstance(size, int) or size <= 0:
            raise GithubReleaseError(f"Draft-Asset {asset.get('name')} hat keine plausible Größe")
        if size >= GITHUB_ASSET_SIZE_LIMIT:
            raise GithubReleaseError(
                f"Draft-Asset {asset.get('name')} überschreitet das Assetgrößenlimit nach Upload"
            )


def publish_release(tag: str) -> None:
    """Veröffentlicht einen zuvor erstellten Draft und markiert ihn als
    latest. Darf laut AGENTS.md ausschließlich NACH erfolgreichem
    S3-Produktions-Update aufgerufen werden (Reihenfolge: S3 zuerst, dann
    GitHub) -- diese Reihenfolge wird vom aufrufenden Workflow
    sichergestellt, nicht von diesem Skript selbst."""
    run_gh(["release", "edit", tag, "--draft=false", "--latest"])


def check_public_asset(tag: str, asset_name: str) -> None:
    """Prüft nach der Veröffentlichung anonym (ohne gh-Auth) per curl, ob
    das Release-Asset per Redirect erreichbar ist (AGENTS.md: "Im ersten
    GitHub-Imager-Test Redirect-Verhalten der Asset-URL prüfen", "danach
    anonyme GitHub-Asset-URLs/Redirects ... prüfen")."""
    url = f"https://github.com/{REPO}/releases/download/{tag}/{asset_name}"
    probe = subprocess.run(
        ["curl", "--location", "--fail", "--silent", "--show-error", "--head", url],
        capture_output=True,
        text=True,
    )
    if probe.returncode:
        raise GithubReleaseError(
            f"Anonymer HTTPS-Zugriff auf veröffentlichtes Asset {asset_name} nicht bestätigt: "
            f"{probe.stderr.strip()}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser(
        "create-draft", help="Draft-Release mit Headless-only-Assets erstellen"
    )
    create_parser.add_argument("package_dir", type=Path)

    verify_parser = subparsers.add_parser(
        "verify-draft", help="Draft-Assets nur über die authentifizierte API prüfen"
    )
    verify_parser.add_argument("tag")
    verify_parser.add_argument("asset_names", nargs="+")

    publish_parser = subparsers.add_parser(
        "publish", help="Zuvor erstellten Draft veröffentlichen und als latest markieren"
    )
    publish_parser.add_argument("tag")

    check_parser = subparsers.add_parser(
        "check-public-asset", help="Anonymen HTTPS-Zugriff auf ein veröffentlichtes Asset prüfen"
    )
    check_parser.add_argument("tag")
    check_parser.add_argument("asset_name")

    args = parser.parse_args()
    try:
        if args.command == "create-draft":
            metadata = load_production_metadata(args.package_dir)
            tag = create_draft_release(args.package_dir, metadata)
            print(f"Draft-Release erstellt: {tag}")
        elif args.command == "verify-draft":
            verify_draft_assets(args.tag, set(args.asset_names))
            print(f"Draft-Assets geprüft: {args.tag}")
        elif args.command == "publish":
            publish_release(args.tag)
            print(f"Release veröffentlicht und als latest markiert: {args.tag}")
        elif args.command == "check-public-asset":
            check_public_asset(args.tag, args.asset_name)
            print(f"Anonymer Zugriff bestätigt: {args.tag}/{args.asset_name}")
        else:  # pragma: no cover - durch argparse choices abgedeckt
            raise GithubReleaseError(f"Unbekanntes Kommando: {args.command}")
    except (GithubReleaseError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"GitHub-Release-Schritt abgebrochen: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
