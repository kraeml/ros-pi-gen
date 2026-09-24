"""Gruppe Q – Image-Stand (Q0, Frische-Pruefung vor den eigentlichen Checks)."""

from __future__ import annotations

import re

import pytest

from helpers.imageio import ImagePack

PINNED_PI_GEN_COMMIT = "74d08a3"


@pytest.mark.usefixtures("pack")
def test_q0a_image_vorhanden(image_path):
    assert image_path.is_file(), f"Image fehlt: {image_path}"


def test_q0b_pigen_commit_gepinnt(pack):
    info = pack.source.parent / (
        pack.source.name.removeprefix("image_").rsplit(".img", 1)[0] + ".info"
    )
    assert info.is_file(), f".info-Datei fehlt: {info}"
    m = re.search(r"Generated using pi-gen, .*?, ([0-9a-f]{7,40}),", info.read_text())
    assert m, f"pi-gen-Commit in {info.name} nicht auffindbar"
    commit = m.group(1)
    assert commit.startswith(PINNED_PI_GEN_COMMIT), (
        f"pi-gen-Commit {commit[:7]} != gepinnt {PINNED_PI_GEN_COMMIT} "
        f"(siehe ros-pi-gen/README.md)"
    )


def test_q0c_bau_log_enthaelt_accesspopup_stage(build_log_text):
    skip_line = "Skip /pi-gen/stage-custom/07-accesspopup/01-run.sh (not executable)"
    assert skip_line not in build_log_text, (
        "07-accesspopup/01-run.sh wurde wegen fehlendem Exec-Bit uebersprungen "
        "-> AccessPopup ist NICHT im Image. Fix: chmod +x stage-custom/"
        "07-accesspopup/01-run.sh, dann Rebuild."
    )
    assert "Begin /pi-gen/stage-custom/07-accesspopup/01-run.sh" in build_log_text, (
        "Build-Log enthaelt keinen Lauf von 07-accesspopup/01-run.sh: das Image "
        "wurde vor der AccessPopup-Integration gebaut -> Rebuild noetig "
        "(siehe ros-pi-gen/README.md)."
    )
    assert "End /pi-gen/stage-custom/07-accesspopup/01-run.sh" in build_log_text, (
        "07-accesspopup/01-run.sh wurde nicht sauber abgeschlossen (Build abgebrochen?"
    )


def test_q0d_bau_log_vollstaendig(pack: ImagePack, build_log_path, build_log_text):
    assert "Begin /pi-gen" in build_log_text and "Build finished" in build_log_text, (
        f"Build-Log {build_log_path.name} ist unvollstaendig (kein 'Build finished') "
        "- Log evtl. von abgebrochenem Build."
    )
    assert "/pi-gen/export-image" in build_log_text, (
        "Build-Log enthaelt keinen export-image-Lauf (kein Image erzeugt?)."
    )
    m = re.search(r"/pi-gen/work/([a-zA-Z0-9_-]+)/", build_log_text)
    assert m, "Workdir-Name im Build-Log nicht auffindbar."
    image_core = pack.source.name.removeprefix("image_").split(".img")[0]
    # pi-gen haengt je nach Konfiguration Suffixe wie '-lite' an; der Workdir-Name
    # muss im Imagenamen enthalten sein (datei: <datum>-<workdir>[<suffix>]).
    assert m.group(1) in image_core, (
        f"Workdir '{m.group(1)}' passt nicht zum Imagenamen '{image_core}' "
        "- Log evtl. von anderem Build."
    )


def _log_events(build_log_text: str) -> list[tuple[str, str]]:
    events = []
    for line in build_log_text.splitlines():
        m = re.search(r"\b(Begin|End|Skip) (\S+)\s*$", line)
        if m:
            events.append((m.group(1), m.group(2)))
    return events


def test_q0e_bau_log_begin_end_paare(build_log_text):
    stack: list[str] = []
    problems: list[str] = []
    for kind, token in _log_events(build_log_text):
        if kind == "Begin":
            stack.append(token)
        elif kind == "End":
            if not stack:
                problems.append(f"End ohne Begin: {token}")
            elif stack[-1] != token:
                problems.append(f"End-Reihenfolge: {token}, erwartet {stack[-1]}")
                if token in stack:
                    while stack and stack[-1] != token:
                        stack.pop()
                    if stack:
                        stack.pop()
            else:
                stack.pop()
        elif kind == "Skip":
            problems.append(f"Skip: {token}")
    problems += [f"Begin ohne End: {t}" for t in stack]
    assert not problems, "Build-Log unvollstaendig:\n  " + "\n  ".join(problems[:15])


def test_q0e_bau_log_kein_skip(build_log_text):
    skips = [token for kind, token in _log_events(build_log_text) if kind == "Skip"]
    assert not skips, (
        f"Stages wurden geskippt (Klasse Exec-Bit/Datei-Fehler): {skips}. "
        "Fix im Overlay, dann Rebuild."
    )


REQUIRED_SUBSTAGES = [
    "/pi-gen/stage0/prerun.sh",
    "/pi-gen/stage1",
    "/pi-gen/stage2/01-sys-tweaks",
    "/pi-gen/stage2/02-net-tweaks",
    "/pi-gen/stage2/04-cloud-init",
    "/pi-gen/stage-custom/prerun.sh",
    "/pi-gen/stage-custom/05-docker-ansible/01-run.sh",
    "/pi-gen/stage-custom/05-docker-ansible/02-packages",
    "/pi-gen/stage-custom/05-docker-ansible/03-run.sh",
    "/pi-gen/stage-custom/07-accesspopup/00-packages",
    "/pi-gen/stage-custom/07-accesspopup/01-run.sh",
    "/pi-gen/export-image",
    "/pi-gen/export-image/05-finalise",
]

# Variante als Sub-Stage-Praefix (06-variant-headless/-desktop, je nach
# VARIANT-Auswahl beim Build); beide sind gueltig, genau eine muss gelaufen
# sein. Alte Logs (Pre-stage-custom) nutzen /pi-gen/stage2/06-variant.
VARIANT_SUBSTAGE_PATTERN = re.compile(
    r"^/pi-gen/(stage-custom|stage2)/06-variant(-[a-z]+)?$"
)


def test_q0f_bau_log_pflichtstufen(build_log_text):
    begins = {token for kind, token in _log_events(build_log_text) if kind == "Begin"}
    ends = {token for kind, token in _log_events(build_log_text) if kind == "End"}
    fehlt_begin = [t for t in REQUIRED_SUBSTAGES if t not in begins]
    fehlt_end = [t for t in REQUIRED_SUBSTAGES if t in begins and t not in ends]
    assert not fehlt_begin, f"Pflichtstufen nie gestartet: {fehlt_begin}"
    assert not fehlt_end, f"Pflichtstufen ohne End: {fehlt_end}"
    variant_stages = [t for t in begins if VARIANT_SUBSTAGE_PATTERN.match(t)]
    assert variant_stages, (
        "Keine Varianten-Sub-Stage (06-variant*) im Build-Log — "
        "Paketlisten-Stufe fehlt (make VARIANT=headless|desktop)."
    )


def test_q0g_bau_log_installationsnachweis(build_log_text):
    # Beleg akzeptiert beide apt-Stände: Erstinstallation ("Setting up …")
    # und Wiederholungslauf mit persistiertem work/ ("already the newest
    # version" — Paket ist dann bereits im RootFS installiert).
    for paket in ("docker-ce", "ansible"):
        m = re.search(
            rf"(Setting up {re.escape(paket)} \(|"
            rf"{re.escape(paket)} is already the newest version \()",
            build_log_text,
        )
        assert m, (
            f"Weder 'Setting up {paket}' noch '{paket} is already the newest "
            f"version' im Build-Log (Installation nicht belegbar)."
        )
    assert re.search(r"/etc/sudoers\.d/acpu: parsed OK", build_log_text), (
        "visudo-Pruefung fehlt im Build-Log (Q8-Beleg)."
    )
