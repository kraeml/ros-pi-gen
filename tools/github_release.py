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
  2. Draft veröffentlichen (publish_release), damit `latest` auf das neue
     GitHub-only-Produktionsrelease zeigt.
  3. Danach: anonyme GitHub-Asset-URL/Redirect-Prüfung (check_public_asset).

Scheitert Schritt 3 oder 4, bleibt der Draft (bzw. das veröffentlichte,
aber noch nicht extern verifizierte Release) stehen — keine automatische
Rückziehung (AGENTS.md: "Release nicht automatisch zurückziehen").
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
from urllib.parse import urlsplit
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
    """Validiert unabhängig von S3 das Headless-only-Produktionspaket."""
    package_dir = package_dir.resolve()
    metadata_path = package_dir / "package.json"
    if not package_dir.is_dir() or not metadata_path.is_file():
        raise GithubReleaseError("Release-Paketverzeichnis oder package.json fehlt")
    try:
        metadata = json.loads(metadata_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise GithubReleaseError("package.json fehlt oder ist ungültig") from error
    if not isinstance(metadata, dict):
        raise GithubReleaseError("package.json muss ein JSON-Objekt enthalten")

    version = metadata.get("version")
    match = PRODUCTION_VERSION_PATTERN.fullmatch(version) if isinstance(version, str) else None
    if not match or metadata.get("status") != "production":
        raise GithubReleaseError("GitHub-Publish verlangt eine gültige Produktionsversion ohne -test-Suffix")
    tag = f"image-{version}"
    if metadata.get("tag") != tag or metadata.get("variant") != "headless":
        raise GithubReleaseError("Paket-Tag oder Variante ist für das Headless-Produktionsrelease ungültig")
    try:
        release_date = dt.date.fromisoformat(metadata.get("release_date", ""))
    except (ValueError, TypeError) as error:
        raise GithubReleaseError("release_date ist kein ISO-Datum") from error
    if metadata.get("release_date") != release_date.isoformat():
        raise GithubReleaseError("release_date muss ein kanonisches ISO-Datum sein")
    if (release_date.year, release_date.month) != (int(match.group(1)), int(match.group(2))):
        raise GithubReleaseError("Paketversion passt nicht zu release_date")
    if metadata.get("rpi_imager_commit") != package_image.PIN["rpi_imager_commit"]:
        raise GithubReleaseError("Paket hat einen unerwarteten Imager-Schema-Pin")
    if metadata.get("schema_version") != 1:
        raise GithubReleaseError("Unbekannte Paketdatenversion")
    for key in ("image_download_size", "extract_size"):
        if not isinstance(metadata.get(key), int) or metadata[key] <= 0:
            raise GithubReleaseError(f"Paketdaten enthalten keine gültige Größe: {key}")
    for key in ("image_download_sha256", "extract_sha256"):
        if not isinstance(metadata.get(key), str) or not package_image.SHA256_PATTERN.fullmatch(metadata[key]):
            raise GithubReleaseError(f"Paketdaten enthalten keinen gültigen Hash: {key}")

    image_name = f"roboter-os-{version}-headless.img.xz"
    expected_files = {"package.json", "SHA256SUMS", "roboter-os.svg", "os-list.json", image_name}
    entries = list(package_dir.iterdir())
    if any(not path.is_file() for path in entries) or {path.name for path in entries} != expected_files:
        raise GithubReleaseError("Produktionspaket enthält fehlende oder unerwartete Dateien")
    if metadata.get("image_file") != image_name:
        raise GithubReleaseError("Paket enthält keinen kanonischen Headless-Dateinamen")
    if metadata.get("variant") != "headless":
        raise GithubReleaseError("Produktionspaket ist nicht headless")

    image_path = package_dir / image_name
    digest = package_image.sha256_file(image_path)
    if image_path.stat().st_size != metadata.get("image_download_size"):
        raise GithubReleaseError("Headless-Image-Größe stimmt nicht mit package.json überein")
    if digest != metadata.get("image_download_sha256"):
        raise GithubReleaseError("Headless-Image-Prüfsumme stimmt nicht mit package.json überein")
    if (package_dir / "SHA256SUMS").read_text() != package_image.render_sha256sums({image_name: digest}):
        raise GithubReleaseError("SHA256SUMS stimmt nicht mit dem Headless-Image überein")
    if package_image.sha256_file(package_dir / "roboter-os.svg") != package_image.sha256_file(ROOT / "assets/roboter-os.svg"):
        raise GithubReleaseError("Imager-Icon im Paket entspricht nicht dem Projekt-Icon")

    try:
        manifest = json.loads((package_dir / "os-list.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise GithubReleaseError("Headless-Manifest fehlt oder ist ungültig") from error
    if not isinstance(manifest, dict):
        raise GithubReleaseError("Headless-Manifest muss ein JSON-Objekt enthalten")
    if "imager" in manifest or not isinstance(manifest.get("os_list"), list) or len(manifest["os_list"]) != 1:
        raise GithubReleaseError("Headless-Manifest muss genau einen Eintrag enthalten")
    entry = manifest["os_list"][0]
    if not isinstance(entry, dict):
        raise GithubReleaseError("Headless-Manifest-Eintrag muss ein JSON-Objekt enthalten")
    for field, expected_asset in (("url", image_name), ("icon", "roboter-os.svg")):
        parsed_url = urlsplit(entry.get(field, ""))
        if (
            parsed_url.scheme != "https"
            or parsed_url.netloc != "github.com"
            or not parsed_url.path.startswith(f"/{REPO}/releases/download/{tag}/")
            or parsed_url.path.rsplit("/", 1)[-1] != expected_asset
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise GithubReleaseError(f"Headless-Manifest-{field} verweist nicht auf das versionierte GitHub-Asset")
    if entry.get("image_download_size") != image_path.stat().st_size or entry.get("image_download_sha256") != digest:
        raise GithubReleaseError("Größe oder Prüfsumme im Headless-Manifest stimmt nicht")
    if entry.get("devices") != package_image.PIN["required_device_tags"]:
        raise GithubReleaseError("Headless-Manifest-Gerätetags sind inkonsistent")
    try:
        schema_path, catalog_path = package_image.pinned_sources()
        package_image.validate_manifest(manifest, schema_path, catalog_path)
    except package_image.PackageError as error:
        raise GithubReleaseError(f"Headless-Manifest verletzt das gepinnte Schema: {error}") from error
    return metadata


def github_latest_manifest_url(variant: str) -> str:
    return f"https://github.com/{REPO}/releases/latest/download/{package_image.github_manifest_name(variant)}"


def github_asset_paths(package_dir: Path, metadata: dict) -> dict[str, Path]:
    """Liefert die für dieses Headless-only-Produktionsrelease
    erforderlichen GitHub-Release-Assets: Image, variantenspezifisches
    Manifest (headless-os-list.json), SHA256SUMS und das Imager-Icon
    (roboter-os.svg). Rendert das GitHub-Manifest mit der versionierten
    Release-Asset-Basis-URL in ein temporäres Verzeichnis, unabhängig davon,
    ob im Paket schon ein gleichnamiges Manifest liegt.

    Das Paketverzeichnis bleibt unverändert und separat validierbar.

    Das Icon wird als eigenes viertes GitHub-Asset hochgeladen, weil das
    gepinnte Imager-V4-Schema pro Manifest-Eintrag ein Pflichtfeld 'icon'
    verlangt und das Produktionsrelease vollständig auf GitHub liegt.
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
    """Veröffentlicht einen zuvor erstellten GitHub-only-Draft als latest."""
    run_gh(["release", "edit", tag, "--draft=false", "--latest"])


def check_public_url(url: str) -> None:
    """Prüft anonym per HTTPS-HEAD mit Redirect-Following eine veröffentlichte URL."""
    parsed_url = urlsplit(url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise GithubReleaseError("Öffentliche URL muss HTTPS verwenden")
    probe = subprocess.run(
        ["curl", "--location", "--fail", "--silent", "--show-error", "--head", url],
        capture_output=True,
        text=True,
    )
    if probe.returncode:
        raise GithubReleaseError(
            f"Anonymer HTTPS-Zugriff auf {url} nicht bestätigt: {probe.stderr.strip()}"
        )


def check_public_asset(tag: str, asset_name: str) -> None:
    """Prüft nach der Veröffentlichung anonym Redirect und Zugriff auf ein Release-Asset."""
    url = f"https://github.com/{REPO}/releases/download/{tag}/{asset_name}"
    check_public_url(url)


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

    check_url_parser = subparsers.add_parser(
        "check-public-url", help="Anonymen HTTPS-Zugriff auf eine URL prüfen"
    )
    check_url_parser.add_argument("url")

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
        elif args.command == "check-public-url":
            check_public_url(args.url)
            print(f"Anonymer Zugriff bestätigt: {args.url}")
        else:  # pragma: no cover - durch argparse choices abgedeckt
            raise GithubReleaseError(f"Unbekanntes Kommando: {args.command}")
    except (GithubReleaseError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"GitHub-Release-Schritt abgebrochen: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
