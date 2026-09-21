# TODO – ros-pi-gen Arbeitsliste

Blöcke: **1** Overlay ersetzen · **2** AccessPopup · **3** Build-/CI-Härtung ·
**4** Image-Inhalt/Architektur · **5** Repo-Hygiene

---

## 1. Overlay-Kopieren durch versioniertes Verfahren ersetzen

### Ausgangslage

Stand heute: ros-pi-gen ist ein Overlay-Repo. Für jeden Build muss manuell
in den pi-gen-Clone kopiert werden (siehe README,
[Overlay einbringen](README.md#overlay-einbringen-beide-wege)):

```bash
cp -r /pfad/zum/ros-pi-gen/stage2/* stage2/
cp /pfad/zum/ros-pi-gen/config config
```

Probleme:

- **manuell & fehleranfällig:** Reihenfolge (Overlay vor Varianten-cp),
  gerichtete cps (`00-packages.desktop` → `00-packages` überschreibt die
  headless-Liste), vergessene `PIGEN_VARIANT`-Kopplung
- **nicht versioniert:** der Overlay-Stand im Clone ist nicht
  reproduzierbar; der gepinnte pi-gen-Commit (`74d08a3`) muss separat
  geprüft werden
- **pi-gen-Tree wird dirty:** Submodul-/Commit-Status des Clones ist nach
  dem Kopieren nicht mehr sauber erkennbar

Ziel: **ein Befehl** für Setup + Build, pi-gen-Version versioniert, Overlay
ohne gerichtete-cp-Fallen.

### Idee a) pi-gen als git-Submodul + Setup-Skript (pragmatischer Zwischenschritt)

pi-gen wird Submodule von ros-pi-gen; ein Skript (`setup.sh`) oder
`Makefile` automatisiert: Submodule @ gepinntem Commit initialisieren →
Overlay-cp → Build-Aufruf (docker/native, Varianten-Flag).

- **Pro:** pi-gen-Commit versioniert; ein Befehl statt manueller cps;
  weniger Tippfehler
- **Con:** Submodul-Tree bleibt nach dem Kopieren "dirty" (Kopien sind nicht
  committbar); Kopier-Mechanik bleibt, nur automatisiert
- **Skizze:**
  ```bash
  git submodule add --branch arm64 https://github.com/RPi-Distro/pi-gen.git pi-gen
  git -C pi-gen checkout 74d08a3
  # setup.sh:
  #   git submodule update --init --recursive
  #   cp -r stage2/* pi-gen/stage2/ ; cp config pi-gen/config
  #   [ $variant = desktop ] && cp …00-packages.desktop …00-packages
  #   build.sh/build-docker.sh Aufruf, Flags durchreichen
  ```

### Idee b) `STAGE_LIST` mit externem Stage + `stage-custom/` (Ziel — kein Kopieren mehr)

pi-gen akzeptiert in `STAGE_LIST` Pfade **außerhalb** des pi-gen-Verzeichnisses
(build.sh realpath't jede Stage unabhängig, cwd des Aufrufs ist maßgeblich).
ros-pi-gen hält dann sein eigenes Stage-Dir und pi-gen bleibt **pristine**:

```
ros-pi-gen/
├── pi-gen/                  # git-Submodul, unverändert, keine Kopien
├── stage-custom/            # eigenes Stage-Dir für den Build
│   ├── prerun.sh            # copy_previous (aus pi-gen stage2 übernehmen)
│   ├── EXPORT_IMAGE         # aus pi-gen stage2 übernehmen (Export aus diesem Stage)
│   ├── 01-…04-…/            # Sub-Stages aus pi-gen stage2 (an gepinnten Commit gebunden)
│   ├── 05-docker-ansible/   # eigen
│   ├── 06-variant/          # eigen (00-packages / 00-packages.desktop)
│   └── 07-accesspopup/      # eigen (AccessPopup AP-Fallback + Web-UI)
└── config                   # STAGE_LIST zeigt auf stage-custom
```

- **Nativ:** `STAGE_LIST="<clone>/stage0 <clone>/stage1 <ros-pi-gen>/stage-custom"`
  (Wrapper setzt `STAGE_LIST` als Env-Var — build.sh nutzt
  `${STAGE_LIST:-…}`, Env überschreibt den config-Default; so kann dieselbe
  config nativ wie im Container dienen)
- **Docker:** build-docker.sh baut das pi-gen-Image aus dem pristine Clone
  und mountet beim Lauf `PIGEN_DOCKER_OPTS="--volume <ros-pi-gen>/stage-custom:/pi-gen/stage-custom"`;
  Wrapper setzt `STAGE_LIST=/pi-gen/stage0 /pi-gen/stage1 /pi-gen/stage-custom`
  und übergibt die config via `-c <ros-pi-gen>/config` (wird zu `/config`
  gemountet)
- **Pro:** null Kopieren in pi-gen; Submodul-Status bleibt sauber;
  Overlay vollständig versioniert in ros-pi-gen; native + Docker aus
  derselben Quelle
- **Con:** pi-gens Sub-Stages `01-…`/`04-…` leben dupliziert in
  ros-pi-gen und sind an den gepinnten pi-gen-Commit gebunden →
  **Sync-Prüfung** nötig (Checksum-/git-diff-Vergleich gegen den Commit,
  ggf. CI); `stage-custom` braucht `prerun.sh` + `EXPORT_IMAGE` aus pi-gen
- **Randnotiz:** Sub-Stage-Erkennung (`for SUB_STAGE_DIR in
  "${STAGE_DIR}"/*`) sortiert alphanumerisch — `01-…` bis `07-…` im
  gemeinsamen Dir ist äquivalent zum heutigen Zustand nach dem cp

### Idee c) git subtree (Vendoring)

pi-gen direkt in ros-pi-gen vendor'en (`git subtree add/pull`).

- **Pro:** ein Repo, kein Submodul-Handling, Overlay committbar
- **Con:** pi-gen-Historie bläht ros-pi-gen auf; Updates via subtree-pull
  erzeugen Merge-Konflikte in den überlagerten Dateien (stage2, Dockerfile);
  Update-Workflow unübersichtlich

### Idee d) pi-gen-Fork mit Merge-Branch

Overlay als eigene Commits auf dem arm64-Branch im eigenen pi-gen-Fork;
Updates via `git fetch upstream && git merge arm64`.

- **Pro:** ein Repo, Overlay committbar, kein dirty Tree, kein Kopieren;
  CI kann direkt aus dem Fork bauen; Varianten-Dateien
  (`00-packages` / `00-packages.desktop`) koexistieren committbar
- **Con:** Merge-Konflikte bei Upstream-Änderungen an überlagerten Dateien
  (stage2, Dockerfile, build.sh); Fork-Divergenz pflegen; Overlay-Lagerort
  wandert in den Fork (Projekttrennung ros-pi-gen ↔ Fork beachten)

### Idee e) Bestehendes Image modifyzieren (Pimod-Ansatz)

Statt Neubau: fertiges Raspberry-Pi-OS-Lite-arm64-Image (Trixie) per
Docker-basiertem Modifikationswerkzeug (pimod-Stil, PiFile-artiges Skript)
anpassen — Locale, SSH, Docker-Repo, Ansible, eigene Pakete.

- **Pro:** Iteration in Minuten statt Stunden; kein Bootstrap; keine
  Host-Keyring-Problematik
- **Con:** Basis-Image extern gepflegt (Reproduzierbarkeit eingeschränkt);
  `STAGE_LIST`-/Varianten-Konzept entfällt → Umbau der Stages in
  Modifikationsschritte; Debian-Feintuning (Locale/Zeitzone) nacherledigt
- **Bewertung:** gut für schnelle Experimente; kein Ersatz für die
  versionierte Pipeline

### Bewertung / Empfehlung

1. **Idee a** als schneller Zwischenschritt (Submodul + `setup.sh`):
   sofortige Verbesserung der Bedienbarkeit, geringes Risiko.
2. **Idee b** als Endziel: eliminiert das Kopieren vollständig; Aufwand
   mittler (stage-custom + Wrapper + Sync-Check). Wenn b steht, entfällt
   der Overlay-cp aus a.
3. **Idee d** als Alternative zu b prüfen, wenn Fork-Pflege lieber ist als
   stage-custom-Sync (beide eliminieren das Kopieren; b hält ros-pi-gen
   als einziges Overlay-Repo, d lebt im Fork).
4. **Idee c** nur bei Ablehnung von Submodulen (nachteilige Interaktion mit
   bestehenden CI-Systemen o. ä.).
5. **Idee e** nur als Experiment-Pfad parallel zur Pipeline.

### Offene Fragen (Overlay)

- [ ] Update-Politik für den pi-gen-Submodul-Commit (manuell anlassen vs.
      regelmäßiges Pin-Update; Trixie-ABI-Änderungen beachten)
- [ ] Sync-Check `01-…04-…` ↔ gepinnter Commit: lokales Skript (shasum)
      und/oder CI-Job?
- [ ] Wrapper-Interface: Flags (`CLEAN`, `CONTINUE`, `PRESERVE_CONTAINER`,
      Variante headless/desktop) durchreichen; Default = Docker?
- [ ] `WORK_DIR`/`DEPLOY_DIR` außerhalb des Submoduls legen (z. B.
      `ros-pi-gen/work`, `ros-pi-gen/deploy`) und `.gitignore` in
      ros-pi-gen ergänzen?
- [ ] Desktop-Variante im Wrapper als Flag (`--variant desktop`) statt
      gerichtetem cp lösen (Wrapper erzeugt `00-packages` aus der
      Master-Vorlage)?
- [ ] CI/CD-Anbindung (GitLab-Runner mit Docker): Artefakt-Upload aus
      `deploy/`, Image-Benennung inkl. pi-gen-Commit-Kürzel

---

## 2. AccessPopup – automatisches WLAN-/AccessPoint-Management

Status: **Umsetzungsplan v2.1 beschlossen** (Details, Architektur, Tests:
[AccessPopup.md](AccessPopup.md), §8). Umsetzung: `stage2/07-accesspopup/`.

**Umgesetzt:** temporärer AP, wenn kein bekanntes WLAN erreichbar; Konfiguration
per AccessPopup-Web-UI (Port 8052, Dispatcher-gated – nur im AP-Fenster aktiv);
Captive-Portal-Erkennung via DNS-Wildcard + nft-Redirect 80→8052; AP-Clients
per nft isoliert (kein Internet/SSH/Docker/ROS); SSID `<hostname>-AP` (Hostname
via Pi-Imager = Geräteidentität – keine Etiketten, MAC nicht ablesbar;
Fallback `Roboter-AP`); einheitliches AP-Passwort `Pi-WLAN-Setup-2026`;
`WPA_COUNTRY="${WPA_COUNTRY:-DE}"` in der config (Imager bleibt maßgeblich).
AccessPopup unverändert (kein Fork), vendor't + gepinnt: `ba6eff1…`
(`stage2/07-accesspopup/files/VENDORED.md`).

**Design-Entscheidung: Temporärer AccessPoint**

- **Zweck:** der AP dient ausschließlich zur WLAN-Konfiguration
- **Aktivierung:** nur, wenn kein bekanntes WLAN erreichbar ist
- **Sicherheit:** einheitliches, bekanntes Passwort akzeptabel, da der AP nur
  bei fehlendem WLAN aktiviert und per nft isoliert ist
- **Wichtig:** bei längerem Einsatz (>10 Minuten) Passwort ändern und
  Web-UI-Zugriff bedenken

**Anforderungen**

- Raspberry Pi (oder andere Linux-Systeme mit NetworkManager)
- Unterstützte OS: PiOS Bookworm, Ubuntu 23.10, Arch Linux
- WLAN-Interface (wlan0 oder wlan1)
- Internet-Zugang (zum Herunterladen des Skripts)

**Offene Fragen**

- [x] Zusammenspiel NetworkManager ↔ cloud-init ↔ AccessPopup
      (cloud-init ohne Imager-Files schlafend; NM verwaltet Profile exklusiv,
      AccessPopup schaltet nur per nmcli → kein Konflikt)
- [x] Interface-Policy: `wlan0` (RPi-OS-Konvention), überschreibbar via
      `/etc/accesspopup.conf` (`wdev0`)
- [x] Defaults: SSID `<hostname>-AP`, Passwort `Pi-WLAN-Setup-2026`,
      IP `192.168.50.5` (vorbelegt in `07-accesspopup/files/accesspopup.conf`)
- [x] Basis im Image: NetworkManager ist in `06-variant/00-packages`
      (headless) bereits enthalten ✓
- [x] AccessPoint per Browser einstellbar: AccessPopup-Web-UI + Captive-
      Detection (Auto-Öffnen üblicher Clients; Fallback
      `http://192.168.50.5:8052`)
- [x] QEMU-Smoke-Test erweitert, Strategie in drei Ebenen umgesetzt:
      **Build-Log-Prüfung** (Q0: Stages vollständig, kein `Skip`,
      docker-ce/ansible-Beleg), **Image-Inhalt** (Datei-Manifest per debugfs,
      Q1a Container-Boot, Q2–Q9 im arm64-Container) und **reale Hardware**
      (`tests/tools/pi-smoke.sh`, Gruppe Q final am Pi inkl. Q6 am bcm-Kernel).
      Ein echter QEMU-Kernel-Boot-Test (raspi3b, qemu 6.2) wurde nach
      tragfähiger Diagnose **abgebrochen** — Befunde (BT-serdev vs.
      `/dev/console`, `bcm2835_powermgt`-Reset, qemu-user-Spawn-Limits):
      [tests/README.md](tests/README.md), Abschnitt „Warum kein QEMU“.
      Erste Läufe deckten echte Defekte auf: fehlendes Exec-Bit an
      `07-accesspopup/01-run.sh` (pi-gen skippte die Stage still) und ein
      daran hängender veralteter Image-Stand im deploy.
- [ ] Hardware-Tests Gruppe A/B/C (Grundfunktion, Schul-/Heim-Wechsel,
      Fehlerfälle) inkl. 2-Pi-Mehrgerätetest und Web-UI-Gating-Check
      (AccessPopup.md §8.6); Beobachtungs-Helfer:
      `tests/tools/pi-smoke.sh` (mit Pass/Fail) und `tools/pi-state.sh`

---

## 3. Build-/CI-Härtung

- [x] QEMU-Smoke-Test des gebauten Images: umgesetzt als Container-Boot
      (Q1a, systemd im arm64-RootFS) + Build-Log-/Manifest-Prüfungen
      (Q0e–g, `test_image_files`); cloud-init- und Docker/Ansible-Checks in
      `test_extras_*`. Der echte Kernel-Boot-Check läuft an der Hardware
      (`pi-smoke.sh`, Q1) — QEMU-Vollsystem unter qemu 6.2 war nicht
      tragfähig (siehe [tests/README.md](tests/README.md), „Warum kein QEMU“).
      Details Block 2 ([Testprotokoll](Testprotokoll-AccessPopup.md),
      Gruppe Q).
- [ ] Reproduzierbare Builds: apt-Snapshots (snapshot.debian.org),
      docker-ce-Version pinnen, Image-Benennung mit Datum +
      pi-gen-Commit-Kürzel
- [ ] Größen-Budget: Build failt, wenn headless-Image über einer Schwelle
      (Wert noch festlegen, z. B. 2 GB unkomprimiert)
- [ ] Build-Metriken (Dauer, Image-Größe) pro Lauf sammeln für
      Regressionserkennung
- [ ] `tests/requirements.txt` pinnen (aktuell nur `pytest>=7.0`, kein
      Upper-Bound) — Testläufe sind sonst nicht reproduzierbar, wenn pytest
      ein Breaking-Release bringt; ggf. `pip-compile`/Lock-Datei einführen
- [ ] CI-Pipeline für ros-pi-gen selbst fehlt (kein `.gitlab-ci.yml`, kein
      `.github/workflows/`) — mind. Lint/Overlay-Checks (`test_overlay_*`,
      `test_hostname_ssid`) laufen ohne Docker/Image und wären günstig in
      CI abbildbar; Docker-/Image-Tests (Q1a, Q2–Q9, `test_extras_*`)
      brauchen einen Runner mit Docker + arm64-binfmt
- [ ] Dev-Build-Workflow dokumentieren: schnelle Iteration über pi-gens
      eigenen Mechanismus (pi-gen-README „Skipping stages to speed up
      development") statt Vollbuild — `SKIP`-Dateien in bereits gebauten
      Stages/Sub-Stages (liegen im pi-gen-Clone, gehören nicht ins
      Overlay-Repo), dann `PRESERVE_CONTAINER=1 CONTINUE=1
      ./build-docker.sh` (nativ: einfach ohne `CLEAN=1`); `SKIP_IMAGES`
      spart den Image-Export während der Iteration.
      **Korrektur zur Ursprungsidee:** Ansible wird in
      `stage2/05-docker-ansible` installiert, nicht in „stage5" —
      `stage5` gibt es nur im upstream-pi-gen (LibreOffice/Extras) und
      wird von ros-pi-gen nicht gebaut (`STAGE_LIST` nur bis stage2).
      Timing-Beleg aus dem Build-Log vom 20.09. (`build-docker.log`):
      `05-docker-ansible` ≈ 23,5 min von ~94 min Gesamt — wer nur an
      `06-variant`/`07-accesspopup` iteriert, spart so rund 2/3 der
      Bauzeit. Vollbuild bleibt als periodischer Verifizierungsschritt
      nötig (Drift-Erkennung), danach Testinfra-Lauf.
      **Validiert 2026-09-21:** Nur-06-variant-Lauf in ~1:44 min statt
      ~94 min — SKIP-Dateien (im pi-gen-Clone gitignored), RootFS-Seed
      aus `tests/.work` (3,1 GB, enthält ansible + aktuelle apt-Listen),
      `PRESERVE_CONTAINER=1` + `PIGEN_DOCKER_OPTS`-Mounts für `work/`/
      `deploy/` (dauerhaft auf dem Host). Rezept:
      [Ansible-im-Build.md](Ansible-im-Build.md). Achtung:
      `build-docker.sh` überschreibt `deploy/build-docker.log` bei jedem
      Lauf — der Vollbuild-Log vom 20.09. wurde dadurch ersetzt

---

## 4. Image-Inhalt / Architektur

- [ ] ROS 2 im Image: eigene Stage (`07-ros2`) vs. Runtime-Provisioning
      (Bezug Robotic-ROS2/`ugv_ws`); Größen-/Versionsfrage klären
- [ ] Ansible-Strategie: build-time (heute) vs. ansible-pull/cloud-init
      zur Laufzeit. Konkretes Beispiel aus rpi-robot-base prüfen: die
      fertige Rolle `robot_codeserver`
      (`../rpi-robot-base/provisioning/ansible/roles/robot_codeserver` —
      code-server-Download (.deb), systemd-User-Unit, Config-Template,
      deutsches Sprachpaket) nutzt das im Image vorhandene Ansible
      (`05-docker-ansible`) zur Nach-Boot-Provisionierung — damit lassen
      sich solche Zusätze nach dem Image-Build installieren, ohne eine
      eigene Build-Stage. Achtung: die Rolle braucht einen existierenden
      Benutzer (Home-Dir, systemd --user) — hängt am First-User-Problem
      (Punkt „First-User/SSH-Defaults" oben); im Chroot zur Build-Zeit
      gibt es den Benutzer nicht. **Experiment bestätigt (2026-09-21):**
      ansible-Smoke-Test im Build-Chroot liefert `ping: pong`
      (ansible-core 2.19, python3.13 auto-erkannt, Schritt ~77 s unter
      qemu); Details, Rezept und Grenzen:
      [Ansible-im-Build.md](Ansible-im-Build.md)
- [ ] First-User/SSH-Defaults: `FIRST_USER_PASS` +
      `DISABLE_FIRST_BOOT_USER_RENAME=1` (+ `PUBKEY_SSH_FIRST_USER`) in der
      config setzen, damit `usermod -aG docker`
      (`05-docker-ansible/03-run.sh`) bereits im Build greift (siehe
      README, „Erster Benutzer")
- [ ] `config`-Kommentar zur Ansible-Rolle `robot_pigen` klären: verweist
      auf `roles/robot_pigen/templates/config.j2`, die Rolle existiert
      aber (Stand heute) in `rpi-robot-base` nicht und ist dort auch nicht
      als Ticket/Idee verankert (Backlog geprüft, kein Treffer). Entweder
      Integration mit rpi-robot-base konkret planen und dort ein Ticket
      anlegen, oder Kommentar in `config` präzisieren, damit er nicht wie
      eine bereits existierende Automatisierung wirkt

---

## 5. Repo-Hygiene

- [x] `.gitignore` in ros-pi-gen ergänzt: `tests/.work/`, `__pycache__/`,
      `.pytest_cache/`. Der vorgesehene Teil `work/`, `deploy/`, `build.log`
      entfällt — solche Dateien entstehen im ros-pi-gen-Repo nicht (Builds
      laufen im pi-gen-Clone, dessen `.gitignore` das abdeckt).
- [x] `Fehlermeldungen.md` und `README von pi-gen.md` — entfällt: die Dateien
      existieren nicht mehr im Repo (die pi-gen-README ist online).
- [ ] Branch-/Tag-Konvention festlegen (z. B. `main`, Tags je
      Image-Version)
- [x] `.venv` für die Testinfra: eigenständiges venv im Repo-Root
      (`ros-pi-gen/.venv`, `python3 -m venv .venv` + `pip install -r
      tests/requirements.txt`) statt Abhängigkeit vom Workspace-Root-venv;
      `tests/run_tests.sh` sucht jetzt standardmäßig dort
      (`PIGEN_TEST_VENV` überschreibt weiterhin), `.gitignore` ergänzt.
- [ ] Einstiegs-Tooling auf Root-Ebene fehlt noch (kein `Makefile`, kein
      `setup.sh`): venv-Anlage ist aktuell ein manueller Schritt
      (`python3 -m venv .venv && .venv/bin/pip install -r
      tests/requirements.txt`). Ein `make venv`/`make test`-Pattern nach
      Vorbild `rpi-robot-base/Makefile` (Variable `VENV`, `guard-venv`,
      `venv`-Target mit Datei-Abhängigkeit) würde Setup + Overlay-cp +
      Build-Aufruf konsolidieren (siehe auch Block 1, Idee a)
- [ ] `tests/.work/`-Cache wächst unkontrolliert (aktuell ~12 GB: entpackte
      Images, RootFS-Staging) und wird nur manuell per
      `PIGEN_TEST_CLEAN=1`/`--clean-cache` geleert. Automatischen Cleanup
      ergänzen (z. B. Anzahl-/Alterslimit für alte
      `image_*`-Cache-Verzeichnisse beim Testlauf)
