# Ansible im Build-Prozess – Experiment und Befund

**Stand:** 2026-09-21 · Commit `95355da` (`feature/ansible-buildtest`)

## 1. Kontext und Frage

Ansible wird in `stage2/05-docker-ansible` ins Image installiert — gedacht
für die **Laufzeit**-Provisionierung nach dem ersten Boot. Die offene
Frage (TODO Block 4, „Ansible-Strategie"): Lässt sich dasselbe Ansible
auch schon **im Build-Prozess** nutzen, also im Chroot, um anstelle (oder
als Ergänzung) von pi-gen-Shell-Skripten zu provisionieren? Wäre das
machbar, könnten dieselben Rollen build-time **und** nach dem Boot laufen
(Vorbild: `../rpi-robot-base/provisioning/ansible/roles/robot_codeserver`).

Bewusst als **minimaler Smoke-Test**: kein echtes Playbook, sondern ein
einzelnes Ad-hoc-Kommando mit dem Ping-Modul.

## 2. Experiment

Änderung in `stage2/06-variant/01-run.sh` (nach dem LightDM-Block):

```bash
on_chroot << EOF
ansible -i localhost, -m ping -c local localhost
EOF
```

- `-i localhost,` — Inline-Inventory (abschließendes Komma = Hostliste
  ohne Inventory-Datei), `-c local` — Local-Connection direkt im Chroot
- Läuft über `on_chroot`, d. h. arm64-binär im Zielsystem (qemu-aarch64
  im Build-Container)
- Die Zeile ist **nur ein Experiment** — sie wird beim Abschluss des
  Feature-Branch wieder entfernt und gehört nicht in den normalen Build

## 3. Durchführung: Dev-Build-Workflow (erstmals praktisch validiert)

Ziel war ein Lauf, der **nur `stage2/06-variant`** ausführt, ohne den
~94-minütigen Vollbuild. Der Workflow ist wiederverwendbar und sollte in
die spätere README-Doku einfließen (TODO Block 3):

### 3.1 Overlay-Transfer

Die Änderung liegt im ros-pi-gen-Repo und muss in den pi-gen-Clone
kopiert werden (dort macht `build-docker.sh` bei jedem Lauf ein
`docker build` mit `COPY . /pi-gen/` — der Overlay-Stand wird eingebacken):

```bash
cp -r ros-pi-gen/stage2/* pi-gen/stage2/
cp ros-pi-gen/config pi-gen/config
```

### 3.2 RootFS seeden (statt stage0/1 + stage2/01–05 neu zu bauen)

Es gab keinen erhaltenen Build-Container mehr, also wurde das RootFS aus
dem Testinfra-Cache geseedet — das entpackte RootFS des fertigen Images
vom 20.09. enthält bereits Ansible, Python 3.13 und aktuelle apt-Listen:

```bash
mkdir -p pi-gen/work/raspberrypi-trixie-custom/stage2/rootfs
rsync -aHAX \
  tests/.work/image_2026-09-20-raspberrypi-trixie-custom-lite.img.xz.*/rootfs/ \
  pi-gen/work/raspberrypi-trixie-custom/stage2/rootfs/
```

- Verzeichnisname ergibt sich aus `IMG_NAME` in der config
  (`raspberrypi-trixie-custom`)
- Vorbehalt: das ist das **fertige Image-RootFS** (post-Export) — für
  einen Smoke-Test ausreichend; ein periodischer Vollbuild bleibt der
  Verifizierungsschritt für die echte Pipeline-Reihenfolge

### 3.3 SKIP-Dateien

pi-gen unterstützt SKIP **pro Sub-Stage innerhalb eines Stages**
(`build.sh`, Sub-Stage-Schleife prüft `${SUB_STAGE_DIR}/SKIP`) — ein
eigenes `stage2a` ist dafür nicht nötig:

```bash
touch pi-gen/stage0/SKIP pi-gen/stage1/SKIP
touch pi-gen/stage2/{01-sys-tweaks,02-net-tweaks,03-accept-mathematica-eula, \
  03-set-timezone,04-cloud-init,05-docker-ansible,07-accesspopup}/SKIP
touch pi-gen/stage2/SKIP_IMAGES   # spart den ~16-minütigen Export
```

- `stage2/prerun.sh` sieht das vorhandene RootFS und überspringt
  `copy_previous`
- Alle SKIP-Dateien, `config`, `work/*` und `deploy/*` sind in pi-gens
  `.gitignore` enthalten — der Clone bleibt sauber
- **Wichtig:** SKIP-Dateien nach dem Test wieder entfernen, sonst
  überspringt ein späterer Vollbuild die Sub-Stages stillschweigend

### 3.4 Build-Lauf

```bash
cd pi-gen
PRESERVE_CONTAINER=1 \
PIGEN_DOCKER_OPTS="--volume $PWD/work:/pi-gen/work --volume $PWD/deploy:/pi-gen/deploy" \
  ./build-docker.sh
```

- `work/` und `deploy/` werden per Bind-Mount **dauerhaft auf den Host**
  gelegt — künftige Läufe (auch `CONTINUE=1`) können das RootFS direkt
  wiederverwenden, der Seed muss nie wiederholt werden
- `PRESERVE_CONTAINER=1` behält den Container `pigen_work` für
  Folge-Iterationen

### 3.5 Ergebnis-Verifikation

Log prüfen (wird nach `deploy/build.log` bzw. `deploy/build-docker.log`
geschrieben): nur `06-variant` darf gelaufen sein, danach die
Ansible-Ausgabe im `01-run.sh`-Zeitfenster.

**Caveat:** `build-docker.sh` überschreibt `deploy/build-docker.log` bei
jedem Lauf. Der ausführliche Vollbuild-Log vom 20.09. wurde dadurch
durch den 3-KB-Smoke-Log ersetzt — die Q0-Testinfra-Prüfungen
(Testinfra Block Q0) schlagen gegen das alte Image an, bis wieder ein
vollständiger Build-Log existiert. Das Image selbst bleibt unberührt.

## 4. Ergebnis

**Laufzeit gesamt: 1:44 min** (statt ~94 min Vollbuild).

Log-Auszug:

```
[12:23:44] Begin /pi-gen/stage2/06-variant/00-packages
[12:24:11] End /pi-gen/stage2/06-variant/00-packages        # 27 s, apt-No-op
[12:24:11] Begin /pi-gen/stage2/06-variant/01-run.sh
[WARNING]: Host 'localhost' is using the discovered Python interpreter
           at '/usr/bin/python3.13', but future installation of another
           Python interpreter could cause a different interpreter ...
localhost | SUCCESS => {
    "ansible_facts": {
        "discovered_interpreter_python": "/usr/bin/python3.13"
    },
    "changed": false,
    "ping": "pong"
}
[12:25:28] End /pi-gen/stage2/06-variant/01-run.sh          # 77 s
[12:25:28] Build finished
```

| Messung | Wert |
|---|---|
| `06-variant/00-packages` (apt) | 27 s (bereits installiert, No-op) |
| `06-variant/01-run.sh` (ansible ping) | ~77 s — überwiegend qemu + Interpreter-Discovery |
| Gesamter Lauf inkl. docker build | 1:44 min |

**Bestätigt:** Das im Image installierte Ansible (ansible-core 2.19,
Debian-Trixie-Paket aus `05-docker-ansible`) ist im Build-Chroot
funktionsfähig — Python 3.13 wird automatisch erkannt, der Ping läuft.

## 5. Interpretation und offene Punkte

- **Ansible ist im Build-Prozess nutzbar.** Build-time-Provisionierung
  mit echten Playbooks/Rollen ist machbar — die Strategiefrage
  (build-time vs. ansible-pull/cloud-init zur Laufzeit, TODO Block 4)
  ist damit auf der Build-Seite offen, aber nicht durch Technologie
  blockiert.
- **Interpreter pinnen:** Die Discovery-Warnung zeigt auf
  `python3.13`. In echten Playbooks sollte
  `ansible_python_interpreter=/usr/bin/python3` gesetzt werden, sonst
  breitet zukünftige Debian-Interpreter-Änderungen die Builds.
- **qemu-Overhead einkalkulieren:** Ein trivialer Ping kostet ~77 s im
  Chroot. Echte Playbooks (Dutzende Tasks) kosten im arm64-Emulations-
  Build entsprechend deutlich mehr — die Abwägung build-time- vs.
  runtime-Provisionierung sollte die Buildzeit als Kostenfaktor führen.
- **Grenze im Chroot:** Es läuft **kein systemd** und der erste
  Benutzer existiert nicht (First-User-Problem, TODO Block 4). Rollen
  wie `robot_codeserver` (systemd-User-Unit, Home-Verzeichnisse,
  `state=started`) sind zur Build-Zeit so nicht lauffähig — sie
  gehören zur Laufzeit bzw. brauchen eine chroot-sichere Teilmenge
  (Pakete, Dateien, `systemctl enable`).
- **Ping-Zeile entfernen:** Die Zeile war ein einmaliger Beleg; beim
  `git flow feature finish ansible-buildtest` vorher einen Cleanup-
  Commit machen, damit `develop` die Doku, aber keinen dauerhaften
  Smoke-Test im Vollbuild enthält (~77 s pro Build).

## 6. Manueller Chroot-Login (Debug-Rezept)

Bestätigt am 2026-09-21: Der Build-Chroot lässt sich auch **händisch**
betreten — auf dem Debug-Muster aus der pi-gen-README („Docker Build“:
`docker run -it --privileged --volumes-from=pigen_work pi-gen
/bin/bash`). Zwei Zutaten fehlen dem README-Muster:

1. **arm64-binfmt** — Probe + Fallback-Registrierung (Snippet aus
   `build-docker.sh`); ohne F-Flag-Eintrag scheitert der arm64-Aufruf
   im Container-/Chroot-Kontext mit „Exec format error“
2. **`on_chroot`** — ist keine Datei, sondern eine **Funktion** aus
   `scripts/common`; sie mountet `proc`/`dev`/`dev/pts`/`sys` ins
   RootFS, tmpfs für `/run`+`/tmp`, und führt
   `capsh --chroot=<ROOTFS>/ -- -e …` aus — laut capsh-Hilfe („remaining
   arguments are for /bin/bash“) also `bash -e`, dessen **stdin
   durchgereicht wird**: Heredoc = gepipete Befehlsfolge, TTY =
   interaktiver Prompt

### 6.1 Interaktiver Login (im eigenen Terminal, TTY vorausgesetzt)

```bash
cd pi-gen
docker run -it --privileged --volumes-from=pigen_work pi-gen /bin/bash
```

Im Container:

```bash
cd /pi-gen
export BASE_DIR=/pi-gen
export ROOTFS_DIR=/pi-gen/work/raspberrypi-trixie-custom/stage2/rootfs
export CAPSH_ARG="--drop=cap_setfcap"
export LOG_FILE=/tmp/manual-chroot.log
mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc || true
if ! arch-test -c "$(mktemp -d)" arm64; then
  # Fallback-Registrierung (Snippet aus build-docker.sh):
  echo ':qemu-aarch64-rpi:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:/usr/bin/qemu-aarch64:F' \
    > /proc/sys/fs/binfmt_misc/register
fi
. scripts/common
on_chroot        # → arm64-bash-Prompt im Chroot
```

Am Chroot-Prompt dann z. B.:

```bash
ansible -i localhost, -m ping -c local localhost
exit
```

Falls eigener binfmt-Eintrag registriert wurde, danach im Container
wieder entfernen (ist kernel-global!):

```bash
[ -e /proc/sys/fs/binfmt_misc/qemu-aarch64-rpi ] && \
  echo -1 > /proc/sys/fs/binfmt_misc/qemu-aarch64-rpi
```

### 6.2 Gepipete Variante (für Skripte/CI, ohne TTY — verifiziert)

Identischer Aufbau als Einzeiler-Session; das ist die Variante, mit der
der Befund unten erhoben wurde:

```bash
docker run --rm --privileged -i --volumes-from=pigen_work pi-gen /bin/bash <<'OUTER'
set -e
mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc 2>/dev/null || true
if ! arch-test -c "$(mktemp -d)" arm64; then
  echo ':qemu-aarch64-rpi:M::…:/usr/bin/qemu-aarch64:F' > /proc/sys/fs/binfmt_misc/register
fi
cd /pi-gen
export BASE_DIR=/pi-gen ROOTFS_DIR=/pi-gen/work/raspberrypi-trixie-custom/stage2/rootfs
export CAPSH_ARG="--drop=cap_setfcap" LOG_FILE=/tmp/manual-chroot.log
. scripts/common
on_chroot <<'CHEOF'
whoami; pwd; uname -m; which ansible
ansible -i localhost, -m ping -c local localhost
CHEOF
# binfmt-Aufräumen, falls eigener Eintrag registriert wurde:
[ -e /proc/sys/fs/binfmt_misc/qemu-aarch64-rpi ] && \
  echo -1 > /proc/sys/fs/binfmt_misc/qemu-aarch64-rpi || true
OUTER
```

### 6.3 Befund (2026-09-21)

```
== Chroot-Login-Beleg ==
root              # im Chroot als root
/                 # Rootfs-Wurzel
aarch64           # arm64-Kontext (qemu)
/usr/bin/ansible
ansible [core 2.19.11]
localhost | SUCCESS => {
    "discovered_interpreter_python": "/usr/bin/python3.13",
    "ping": "pong"
}
```

- **ansible ping im manuell betretenen Chroot: `SUCCESS`** — gleiches
  Ergebnis wie der build-integrierte Smoke-Test (§4); binfmt-Registrierung
  war diesmal nicht nötig, die Host-Registrierung bestand die Probe im
  Chroot-Kontext (`arm64: ok`); kein Überbleibsel
  (`qemu-aarch64-rpi`) in `/proc/sys/fs/binfmt_misc`
- `pigen_work` bleibt erhalten (nur der Temp-Container ist `--rm`);
  das RootFS unter `work/` liegt durch den Mount ohnehin auf dem Host
- Nutzen: Rollen-/Playbook-Teilmengen vor der Build-Integration
  interaktiv austesten; Systemzustand im Chroot direkt inspizieren
  (dpkg, services-Symlinks, NM-Profile …)

Verweise: [TODO.md](TODO.md) (Block 3 Dev-Build-Workflow, Block 4
Ansible-Strategie) ·
`../rpi-robot-base/provisioning/ansible/roles/robot_codeserver`
