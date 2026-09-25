# GitHub-Image-Workflow: Planung (KI-Arbeitspapier)

> **Zweck dieses Dokuments:** Umsetzungsplan für einen automatisierten
> GitHub-Actions-Workflow, der das Roboter-Image baut, testet und als
> **Raspberry-Pi-Imager-2.0-Paket** (Image + Repository-JSON) bereitstellt.
> **Grundlage teils umgesetzt (Feature `stage-custom-build`):** das
> Thin-Wrapper-Makefile existiert (`venv lint setup build test ci`,
> siehe § 2) und der stage-custom-Modus ist gebaut (TODO Block 1, Idee b) —
> **offen** bleibt der eigentliche Workflow `.github/workflows/image-build.yml`
> sowie `make package`/Imager-JSON (§ 5). Der Lauf muss **identisch lokal**
> startbar sein (Thin-Wrapper-Prinzip, § 2).
>
> Geprüfter Stand: 22. September 2026. Remote:
> `github.com/kraeml/ros-pi-gen` (Branch `develop`), noch kein
> `.github/`-Verzeichnis (Lücke ist in [TODO.md](TODO.md), Block 3,
> dokumentiert).

---

## 1. Zweck und Zielprodukt

Der Workflow konsolidiert den bisher manuellen Ablauf (pi-gen-Clone
einrichten → Overlay-cp → `build-docker.sh` → Testinfra → Flashen) in einen
versionierten Lauf und erzeugt **alle Artefakte, die der
Imager-2.0-Schul-Workflow braucht** (dieser ist ohne Repository-JSON tot,
siehe [Raspberry-Pi-Imager-2.0.md](Raspberry-Pi-Imager-2.0.md), Kapitel
„Eigene Images einbinden"):

| Artefakt | Inhalt | Verbraucher |
|---|---|---|
| `image_<Datum>-raspberrypi-trixie-custom-lite.img.xz` | Headless-Image (~800 MB xz, 20.09-Beleg) | Imager-Flash, Release |
| `image.img.sha256` / `.bmap` | Prüfsumme; Blockmap (nur fastboot-/CM-Pfad, optional) | Integrität / schneller Flash |
| `imager-repository.json` | Repository JSON V4 mit `init_format` | Imager 2.x (Content Repository) |
| `build-docker.log` | Vollständiges Build-Log | Testinfra Q0, Nachvollziehbarkeit |
| Testbericht (JUnit-XML) | pytest-Ausgabe der Image-Tests | CI-Übersicht, Release-Gate |

**Nicht-Ziele:** ROS-2-Build (Block 4 separat), Auto-Deploy auf Hardware
(`pi-smoke.sh` bleibt bewusst manuell), Image-Modifikation im laufenden
Betrieb.

## 2. Thin-Wrapper-Prinzip (Voraussetzung für „läuft auch lokal")

Die gesamte Logik lebt in **versionierten Makefile-Targets/Skripten im
Repo**; der Workflow ruft ausschließlich diese auf. **Stand: Makefile im
Repo-Root umgesetzt** (Targets `venv`, `lint`, `setup`, `build`, `test`,
`ci`; `package` offen):

```text
GitHub-Runner                                   Lokal
─────────────                                   ─────
make venv    → .venv + requirements             make venv
make lint    → Overlay-/Shell-Checks            make lint
make setup   → pi-gen-Setup (2 Modi, s. u.)     make setup [MODE=…]
make build   → build-docker.sh (Docker/QEMU)    make build
make test    → tests/run_tests.sh               make test
make package → Imager-JSON + Prüfsummen + bmap  make package (offen)
make ci      → alles nacheinander               make ci
```

Damit ist „Workflow läuft lokal" kein Zusatzpfad, sondern dieselbe Kette —
der Workflow ist ein dünner Executor (Checkout, Disk-Cleanup, QEMU-Setup,
Make-Aufrufe, Upload). Optionale Paritätsprüfung mit
[`act`](https://github.com/nektos/act) — mit Einschränkungen (privileged
nötig für binfmt/Docker, Diskgröße, kein Release-Upload): nur für Stufe A/B
rausgefilterte Runs sinnvoll, nicht als Pfad.

**`make setup` — zwei Modi (Dual-Track, Beschluss 2026-09-22; beide
umgesetzt im Makefile):**

- **Phase 1 · `MODE=overlay` (Legacy-Fallback):** pi-gen-Clone @ gepinntem
  Commit `74d08a3` (arm64-Branch) + Overlay-cp — gleiche Mechanik wie
  TODO Block 1, Idee a (`setup.sh`). Die
  Ephemeralität der CI-Umgebung entschärft das dirty-Tree-Problem (der
  Clone wird pro Lauf frisch geklont), **nicht** aber die gerichteten
  cp-Fallen (`00-packages.desktop` überschreibt die headless-Liste,
  `PIGEN_VARIANT`-Kopplung — siehe README-Warnungen).
- **Phase 2 · `MODE=stage-custom` (Ziel — umgesetzt, Default):** pi-gen
  bleibt **pristine** (Submodul), ros-pi-gen hält ein eigenes Stage-Dir
  und die `config` zeigt per `STAGE_LIST` extern darauf — **kein
  Kopieren** (TODO Block 1, Idee b).
  Mechanik gegen pi-gen `74d08a3` verifiziert (2026-09-22, lokale Quelle):
  - `build.sh:330-331` `realpath`'t **jeden** `STAGE_LIST`-Eintrag
    unabhängig — externe Pfade (absolut oder relativ zum cwd des Aufrufs)
    sind nativ erlaubt; Default ist nur `${BASE_DIR}/stage*` (Zeile 320).
  - Die Stage-Kette ist ortsunabhängig: `STAGE` wird per `basename` des
    Stage-Dirs abgeleitet (build.sh:87), `ROOTFS_DIR`/`PREV_ROOTFS_DIR`
    setzt build.sh pro Stage (Zeilen 91-92, 121-123) → `copy_previous`
    (scripts/common:34) funktioniert im externen Dir.
  - `EXPORT_CONFIG_DIR` ist ebenfalls realpath't/überschreibbar
    (build.sh:323); das externe Stage braucht `prerun.sh` + `EXPORT_IMAGE`
    aus pi-gen stage2 (`EXPORT_IMAGE` = nur `IMG_SUFFIX="-lite"` +
    QEMU-Zusatz).
  - **Docker:** `build-docker.sh` reicht `PIGEN_DOCKER_OPTS` (Zeilen 58,
    102) in `docker run` durch → externes Stage per
    `--volume <repo>/stage-custom:/pi-gen/stage-custom` mounten (Pflicht:
    `Dockerfile` macht `COPY . /pi-gen/`, externe Pfade landen nicht im
    Build-Kontext). Die `config` wird ohnehin schon extern eingebunden
    (`--volume …:/config:ro` + `-c /config`-Rewrite, Zeilen 83, 103).
  - **Nativ:** `STAGE_LIST` als Env-Var überschreibt den config-Default
    (build.sh nutzt `${STAGE_LIST:-…}`). Stage-Grundlagen:
    [Pi-Gen-Tool.md](Pi-Gen-Tool.md).

Beide Modi teilen sich `build`/`test`/`package` — der Umschalter ist nur
`setup` (bei Phase 2 übergibt `build` zusätzlich die Volume-Mounts an
`PIGEN_DOCKER_OPTS`). **Umsetzungsabweichung zum Entwurf:** der
Varianten-Umschalter ist nicht mehr `PIGEN_VARIANT` in der config, sondern
die Sub-Stage-Auswahl in `stage-custom` (`06-variant-headless` vs.
`06-variant-desktop`, SKIP-Dateien gesetzt vom Makefile; `VARIANT=`-Input
des Workflows geht direkt an `make build/setup`).

## 3. Pipeline

**Trigger-Tabelle:**

| Ereignis | Stufen | Grund |
|---|---|---|
| `push` / PR auf `develop` | nur **A** (Lint/Overlay, ~Sekunden, ohne Docker) | günstiger Rückkanal; Vollbuild 1,5–3 h wäre unangemessen teuer |
| Tag `image-YYYY.MM.n` (Calver, analog zum `schule-os`-Schema im Imager-Artikel) | A → B → C → D → **E** (Release) | versioniertes Release-Artefakt |
| `workflow_dispatch` (Inputs: `init_format`, `dry_run`) | A → B → C → D (+ E nur mit `publish=true`) | Experimente/B1-Vorläufe, manuell |

**Stufen:**

- **A · Lint/Overlay** — `make lint` (= shellcheck über
  `stage-custom/` + Overlay-Tests `test_overlay_files`/
  `test_hostname_ssid`, laufen ohne Docker/Image, siehe
  [tests/README.md](tests/README.md)).
- **B · Build** — auf `ubuntu-latest`:
  1. Disk-Cleanup (**Pflicht**, Runner hat nur ~14 GB frei, Build braucht
     work 3,1 GB + root.img + xz + Docker-Schichten): bekannte Räum-Kandidaten
     `/usr/local/lib/android`, `/usr/share/dotnet`, `/opt/ghc`,
     `/usr/share/swift`, `/opt/hostedtoolcache/CodeQL` + `docker image prune`
     (freiräumt in der Praxis ~20 GB; **genaue Zahlen als anzupassender
     erster CI-Lauf sehen**).
  2. `docker/setup-qemu-action@v3` (arm64-binfmt; der pi-gen-Docker-Build
     registriert qemu-aarch64 teils selbst im Container — README —, aber
     explizit ist reproduzierbarer).
  3. `make setup && make build` (`IMG_DATE=<Tag-Datum>` via Env —
      `IMG_SUFFIX` **nicht** per Env: das `-lite` setzt
      `stage-custom/EXPORT_IMAGE` automatisch und überschreibt ein
      Env-IMG_SUFFIX beim Export, build.sh:337; siehe
      [Pi-Gen-Tool.md](Pi-Gen-Tool.md), Projekt-Anmerkung).
      **Umsetzung:** Phase 2 ist gebaut — CI läuft direkt mit dem Default
      `MODE=stage-custom` (pi-gen-Submodul bleibt pristine, keine
      gerichteten-cp-Fallen); `MODE=overlay` bleibt als Workflow-Input
      verfügbar (Fallback), Stufen C/D sind modus-unabhängig.
  4. Upload: `.img.xz`, `build-docker.log`, später JSON (Artefakt
     `image-artifacts`, Retention 7 Tage; bei Build-Fehler zusätzlich
     `work/`-Logzip, Retention 1 Tag — der 3,1-GB-work-Ordner ist zu groß
     für Daueraufbewahrung).
- **C · Testinfra** (`needs: build`) — Artefakt laden, `make test` mit
  `PIGEN_TEST_IMAGE=<pfad>`: Q0 (Log), Q1a (Container-Boot, braucht
  Docker+binfmt), Q2–Q9 + `test_extras_*` im arm64-Container;
  `tests/tools/pi-smoke.sh` **läuft bewusst nicht in CI** (Hardware);
  JUnit-Upload (`--junitxml`).
- **D · Imager-Paketierung** — Skript-Skizze `tools/imager-json.sh`:
  ```bash
  #!/usr/bin/env bash
  # usage: imager-json.sh <img.xz> <version>
  set -euo pipefail
  IMG=$1; VER=$2
  sha256sum "$IMG" > "$IMG.sha256"                 # image_download_sha256
  xz -dc "$IMG" | sha256sum > "$IMG.extract.sha256" # extract_sha256
  DL_SIZE=$(stat -c%s "$IMG")                       # image_download_size
  EX_SIZE=$(xz --robot --list "$IMG" | awk '$1=="totals"{print $5}') # ohne 2. Dekompression
  bmaptool create image.img -o image.img.xz.bmap      # optional (fastboot-Pfad),
                                                      # benötigt entpacktes Image:
                                                      # xz -dc "$IMG" > image.img
  # → schreibt imager-repository.json (Template unten)
  ```
- **E · Release** (`needs: [test, package]`, nur bei Tag bzw.
  `publish=true`) — `gh release create` mit Image + JSON + Prüfsummen
  (808 MB < 2-GB-Asset-Limit); `permissions: contents: write` (GITHUB_TOKEN).

## 4. YAML-Skizze (nicht angelegt, Ziel: `.github/workflows/image-build.yml`)

```yaml
name: image-build
on:
  push: { tags: ["image-*"] }
  workflow_dispatch:
    inputs:
      init_format: { default: "cloudinit-rpi", type: choice,
                     options: [cloudinit, cloudinit-rpi] }
      img_suffix:  { default: "-lite" }   # nur dokumentarisch: stage2/EXPORT_IMAGE
                                          # setzt -lite selbst und überschreibt Env
      publish:     { default: false, type: boolean }
permissions: { contents: write }
jobs:
  lint:            # Stufe A
    runs-on: ubuntu-latest
    steps: [checkout, "run: make venv && make lint"]
  build-image:     # Stufe B
    if: startsWith(github.ref, 'refs/tags/image-') || github.event_name == 'workflow_dispatch'
    needs: lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: sudo rm -rf /usr/local/lib/android /usr/share/dotnet /opt/ghc \
             /usr/share/swift /opt/hostedtoolcache/CodeQL
      - run: docker image prune -af || true
      - uses: docker/setup-qemu-action@v3
      - run: make setup && make build     # IMG_DATE/IMG_SUFFIX aus Inputs
      - uses: actions/upload-artifact@v4  # .img.xz + build-docker.log
  test-image:      # Stufe C
    needs: build-image
    runs-on: ubuntu-latest
    steps: [checkout, qemu, cleanup, artifact-download,
            "run: make test  # PIGEN_TEST_IMAGE=<download>"]
  package:         # Stufe D
    needs: build-image
    runs-on: ubuntu-latest
    steps: [checkout, artifact-download,
            "run: make package  # imager-repository.json + sha256 + bmap"]
  release:         # Stufe E
    if: startsWith(github.ref, 'refs/tags/image-') || inputs.publish
    needs: [test-image, package]
    runs-on: ubuntu-latest
    steps: [checkout, artifact-download,
            "run: gh release create ${{ github.ref_name }} …"]
```

(Länge ~60 Zeilen; Details — Speichervariablen, Pfadkonventionen — erst bei
Implementierung festzurren. Wichtig: **alle `run:`-Zeilen sind Make-Aufrufe**,
kein Build-Logik-Inline.)

## 5. Imager-2.0-Paketierung (Stufe D im Detail)

Generiertes `imager-repository.json` (V4-Sublist-Format, **ohne**
`imager`-Block — der gehört dem offiziellen Katalog; Referenz:
`doc/schema-notes.md` im rpi-imager-Repo):

```json
{
  "os_list": [
    {
      "name": "Roboter-OS 2026.09.1 (Headless)",
      "description": "ros-pi-gen Headless-Image: Docker CE + Ansible + AccessPopup",
      "icon": "https://raw.githubusercontent.com/kraeml/ros-pi-gen/main/assets/icon.png",
      "url": "https://github.com/kraeml/ros-pi-gen/releases/download/image-2026.09.1/image_2026-09-22-raspberrypi-trixie-custom-lite.img.xz",
      "release_date": "2026-09-22",
      "image_download_size": 807924492,
      "image_download_sha256": "<sha256 der .img.xz>",
      "extract_size": <extract_size in Bytes, via `xz --robot --list`>,
      "extract_sha256": "<sha256 des entpackten Images>",
      "devices": ["pi3", "pi4", "pi5"],
      "capabilities": ["rpi_connect"],
      "init_format": "cloudinit-rpi"
    }
  ]
}
```

- **`init_format: "cloudinit-rpi"` als Default** (Beschluss): entspricht dem
  offiziellen Trixie-OS-Pfad, unsere Basis hat `cc_raspberry_pi` +
  `raspi-config`; `cloudinit` bleibt per Workflow-Input-Fallback, bis B1/B2
  (Hardware) `cloudinit-rpi` bestätigt haben.
- **Lehrkraft-Nutzung:** Manifest-URL in Imager unter *App Options →
  Content Repository → EDIT → Custom URL* eintragen (oder
  `rpi-imager --repo <url>`) → Image erscheint gefiltert, Customization-Step
  greift (siehe [WLAN-Anleitung.md](WLAN-Anleitung.md), Lehrkraft-Hinweis).
  Für den **lokalen** Test: Datei-Pfad statt URL in einem lokalen Manifest
  (`create_local_json.py` aus dem rpi-imager-Repo hilft **nicht** — es
  matcht nur offizielle Image-Namen —, daher Teil des
  `imager-json.sh`-Skripts).
- **Versionierung:** Calver `YYYY.MM.n` im Tag (`image-2026.09.1`) und im
  JSON-`name`; `release_date` = Tag-Datum; pro Version beide Prüfsummen im
  Release-Text (Regeln im Imager-Artikel, Kapitel „Sicherheit und
  Versionierung": Integrität ≠ Authentizität).

## 6. Ressourcen und Laufzeiten (Erwartungswerte)

| Größe | Wert | Quelle |
|---|---|---|
| Vollbuild lokal (Docker) | ~94 min | TODO Block 3 (20.09-Log) |
| Image xz | ~808 MB | pi-gen/deploy 20.09 |
| work-Verzeichnis | ~3,1 GB | pi-gen-Clone |
| Testcache der Suite | ~12 GB | tests/.work (in CI abgebaut durch Ephemeralität) |
| Testlauf mit vorhandenem Image | ~1 min + Container-Boot (Timeout 900 s) | tests/README, conftest.py |
| GitHub-Hosted-Runner | ~14 GB Disk frei → **Cleanup-Schritt Pflicht**; Job-Limit 6 h; Release-Asset ≤ 2 GB | GitHub-Doku (Näherungswerte, im ersten Lauf verifizieren) |
| Kosten | Free-Plan-Minuten reichen (Linux 1×-Faktor); Vollbuild nur per Tag/manuell | Beschlossen |

## 7. Sicherheit

- **Keine Secrets nötig** (public repo, `GITHUB_TOKEN` reicht für Release).
- Prüfsummen decken Integrität, nicht Herkunft — Ausblick: Signatur der
  Release-Artefakte (GPG oder Sigstore/cosign, Schlüssel getrennt
  verteilt); Verantwortlichkeiten wie im Imager-Artikel (Kapitel
  „Ein Schul-Image bereitstellen") beschreiben.
- Keine WLAN-/Zugangsdaten in JSON oder Release (Regel aus dem Artikel).

## 8. Offene Punkte

- [x] `make`-Zielnamen und Skript-Lagerort final — **Makefile im Root**
      (Targets `venv lint setup build test ci`, `package` folgt mit der
      Imager-Paketierung); MODE-Interface umgesetzt (`MODE=stage-custom`
      Default, `MODE=overlay` Fallback) — Feature `stage-custom-build`,
      TODO Block 1 Idee b
- [ ] Exakte `devices`-Tags gegen das offizielle
      `os_list_imagingutility_v4.json` verifizieren (pi3+/pi4/pi5 —
      Tag-Syntax nicht aus Schema-Doku ableitbar)
- [ ] `.bmap`-Erzeugung: bmaptool-Abhängigkeit im Workflow vs. weglassen
      (nutzt heute niemand)
- [ ] Reproduzierbarkeit des Builds (apt-Snapshots, siehe TODO Block 3) —
      Workflow gibt Commit + Log vor, Paketstand bleibt bis dahin
      schwebend
- [ ] `act`-Parität probehalber testen (binfmt/privileged/Disk)
- [ ] Erster CI-Lauf als Kalibrierung (Disk-Freigabe, Laufzeit, Timeout)
- [ ] Nach Umsetzung: TODO Block 3 („CI-Pipeline fehlt") abhaken und auf
      dieses Dokument verweisen

---

## Prüfvermerk (kurz)

Verifiziert gegen Primärquellen (Stand 22.09.2026): Imager-2.0-Verhalten
bei Use custom/`init_format` (`doc/os_customisation_formats.md` +
`doc/schema-notes.md` im rpi-imager-Repo), `create_local_json.py`-Grenzen
(`doc/local_json/README.md` — matcht nur offizielle Image-Namen), pi-gen
74d08a3 (`build.sh`: `IMG_DATE`/`IMG_SUFFIX` per Env, `ENABLE_CLOUD_INIT`
Default 1; `build-docker.sh`-Varianten aus README), Testinfra-Aufteilung
([tests/README.md](tests/README.md), `conftest.py`:
`PIGEN_TEST_IMAGE`/Boot-Timeout 900 s), Deploy-Erzeugnisgrößen (808 MB xz /
3,1 GB work, lokal gemessen).

**Ergänzt (22.09.2026, Modus stage-custom / TODO Idee b):** pi-gen 74d08a3
akzeptiert externe `STAGE_LIST`-Pfade nativ — `build.sh:330-331` (realpath
je Eintrag, Default nur `${BASE_DIR}/stage*` Zeile 320), Stage-Kette
ortsunabhängig (`STAGE` per `basename` Zeile 87, `ROOTFS_DIR`/
`PREV_ROOTFS_DIR` build.sh-seitig Zeilen 91-92/121-123, `copy_previous`
scripts/common:34), `EXPORT_CONFIG_DIR` extern-fähig (Zeile 323),
`stage2/EXPORT_IMAGE` = nur `IMG_SUFFIX="-lite"` + QEMU-Zusatz;
`build-docker.sh` reicht `PIGEN_DOCKER_OPTS` durch (Zeilen 58, 102) und
bindet die config bereits extern ein (`--volume …:/config:ro`,
`-c /config`-Rewrite, Zeilen 83, 103); Mount-Pflicht folgt aus
`Dockerfile` (`COPY . /pi-gen/`).

**Umgesetzt (Feature `stage-custom-build`, 22.09.2026):** pi-gen als
Submodul @ `74d08a3` (in upstream arm64 exakt der HEAD); Verkettung als
**anhängende Stage** gewählt — `STAGE_LIST="stage0 stage1 stage2
stage-custom"`, pi-gens stage2 läuft vollständig (01–04), exportiert aber
nicht (`stage2/SKIP_IMAGES`, gitignored, von `make setup` gesetzt);
`stage-custom` hält `prerun.sh` (copy_previous) + `EXPORT_IMAGE` + die
eigenen Sub-Stages 05–07. Varianten als parallele Sub-Stages
(`06-variant-headless`/`06-variant-desktop`, SKIP-Toggle statt gerichteter
cp). Makefile im Root als Thin-Wrapper; Tests/Q0 auf die neuen Pfade
umgestellt (Q0f varianten-tolerant).

Offen/unverifiziert: exakte GitHub-Runner-Disk-Werte (Näherung aus
Allgemeinwissen, im ersten Lauf kalibrieren), `devices`-Tag-Syntax der
offiziellen V4-Manifest-URL, `act`-Verhalten unter binfmt, bmap-Pfad.

### Schlagworte

`github-actions` `ci` `pi-gen` `image-build` `raspberry-pi-imager-2` `repository-json` `cloud-init` `release` `calver`
