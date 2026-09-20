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
│   └── 06-variant/          # eigen (00-packages / 00-packages.desktop)
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
  "${STAGE_DIR}"/*`) sortiert alphanumerisch — `01-…` bis `06-…` im
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

## 2. AccessPopup-Ansible-Rolle – automatisches WLAN-/AccessPoint-Management

Roboter bleibt ohne konfiguriertes WLAN erreichbar: AccessPopup aktiviert
einen temporären AccessPoint, über den WLAN-Zugangsdaten gesetzt werden
können.

**Design-Entscheidung: Temporärer AccessPoint**

- **Zweck:** der AP dient ausschließlich zur WLAN-Konfiguration
- **Aktivierung:** nur, wenn kein WLAN konfiguriert ist
- **Sicherheit:** Standard-Passwörter und -SSIDs sind akzeptabel, da der AP
  nur bei fehlendem WLAN aktiviert wird
- **Wichtig:** bei längerem Einsatz (>10 Minuten) müssen Passwort und
  Firewall-Regeln angepasst werden

**Anforderungen**

- Raspberry Pi (oder andere Linux-Systeme mit NetworkManager)
- Unterstützte OS: PiOS Bookworm, Ubuntu 23.10, Arch Linux
- WLAN-Interface (wlan0 oder wlan1)
- Ansible 2.10+
- Internet-Zugang (zum Herunterladen des Skripts)

**Offene Fragen**

- [ ] Lagerort der Rolle: eigenes Robot-Ansible-Repo vs. hier in ros-pi-gen
- [ ] Provisioning-Pfad: build-time (eigene Stage) vs. runtime
      (ansible-pull/cloud-init; Ansible dank `05-docker-ansible` bereits im
      Image)
- [ ] Zusammenspiel NetworkManager ↔ cloud-init ↔ AccessPopup
      (Konfliktvermeidung bei Interface-Konfiguration)
- [ ] Interface-Policy: wlan0/wlan1 vs. predictable interface names
- [ ] Defaults für SSID/Passwort festlegen und dokumentieren
- [ ] Firewall-Hardening für >10-min-Einsatz (nftables/ufw-Regeln)
- [ ] Basis im Image: NetworkManager ist in `06-variant/00-packages`
      (headless) bereits enthalten ✓

---

## 3. Build-/CI-Härtung

- [ ] QEMU-Smoke-Test des gebauten Images (Headless-Boot in qemu-aarch64):
      Boot ohne Kernel-Panik, SSH-Port offen, cloud-init ok, Docker/Ansible
      installiert
- [ ] Reproduzierbare Builds: apt-Snapshots (snapshot.debian.org),
      docker-ce-Version pinnen, Image-Benennung mit Datum +
      pi-gen-Commit-Kürzel
- [ ] Größen-Budget: Build failt, wenn headless-Image über einer Schwelle
      (Wert noch festlegen, z. B. 2 GB unkomprimiert)
- [ ] Build-Metriken (Dauer, Image-Größe) pro Lauf sammeln für
      Regressionserkennung

---

## 4. Image-Inhalt / Architektur

- [ ] ROS 2 im Image: eigene Stage (`07-ros2`) vs. Runtime-Provisioning
      (Bezug Robotic-ROS2/`ugv_ws`); Größen-/Versionsfrage klären
- [ ] Ansible-Strategie: build-time (heute) vs. ansible-pull/cloud-init
      zur Laufzeit
- [ ] First-User/SSH-Defaults: `FIRST_USER_PASS` +
      `DISABLE_FIRST_BOOT_USER_RENAME=1` (+ `PUBKEY_SSH_FIRST_USER`) in der
      config setzen, damit `usermod -aG docker`
      (`05-docker-ansible/03-run.sh`) bereits im Build greift (siehe
      README, „Erster Benutzer")

---

## 5. Repo-Hygiene

- [ ] `.gitignore` in ros-pi-gen ergänzen: `work/`, `deploy/`, `build.log`
- [ ] `Fehlermeldungen.md` und `README von pi-gen.md` nach `docs/`
      verschieben (oder löschen; die pi-gen-README ist online)
- [ ] Branch-/Tag-Konvention festlegen (z. B. `main`, Tags je
      Image-Version)
