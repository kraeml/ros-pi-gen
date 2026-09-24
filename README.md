# ros-pi-gen – eigene Raspberry-Pi-Images auf pi-gen-Basis

Eigenes arm64-Image für Raspberry Pi 3+/4/5 auf Basis von Debian Trixie mit
Docker CE und Ansible. Dieses Repo hält die pi-gen-Konfiguration (`config`)
und eigene Stages (`stage-custom/05-docker-ansible`, `stage-custom/06-variant-*`,
`stage-custom/07-accesspopup`); pi-gen selbst ist als
[git-Submodul](https://github.com/RPi-Distro/pi-gen) (arm64-Branch, gepinnter
Commit `74d08a3`) eingebunden und bleibt **unverändert** — gebaut wird mit
`STAGE_LIST="stage0 stage1 stage2 stage-custom"`, wobei pi-gens `stage2`
durchläuft (Sub-Stages 01–04) und `stage-custom` als zusätzliche Stage das
RootFS übernimmt (`copy_previous`) und daraus exportiert. Kopieren in den
pi-gen-Tree gibt es **nicht mehr** (Hintergrund: [TODO.md](TODO.md), Block 1,
Idee b).

**Schnellstart:**

```bash
git submodule update --init   # pi-gen + robotics-lab-vm @ gepinnten Commits holen
make setup && make build      # Docker-Build, headless (Default)
make test                     # Testinfra gegen deploy/
```

**Empfohlener Weg:** Build mit Docker — der `debian:trixie`-Container bringt
Keyring, debootstrap und qemu aktuell mit, auf dem Host ist nur Docker Engine
nötig; ältere Hosts (hier: Ubuntu 20.04 mit qemu 4.2.1) werden über das
binfmt Version-Gate bedient (temporärer Container-qemu-Entry, trap-gesichert
geräumt — Details: [TODO.md](TODO.md), Block 3). Auf modernen Hosts (≥ qemu 8)
greift das Gate nicht ein. Der native Build ist die Rückfallebene ohne Docker
(→ [Nativer Build](#nativer-build-ohne-docker)), als Build-Umgebung mit
moderner qemu ohne Kernel-Eingriff dient die [Vagrant-VM](#build-in-der-vm-robotics-lab-vm)
(Ubuntu 24.04). Als alternative, RPi-offizielle Build-Pipeline mit
deklarativer YAML-Konfiguration wird außerdem `rpi-image-gen` diskutiert (→
[Eigene-Raspberry-Pi-Images-rpi-image-gen.md](Eigene-Raspberry-Pi-Images-rpi-image-gen.md),
Einordnung in [TODO.md](TODO.md), Block 1). Einen geplanten CI-Lauf
(GitHub Actions: Build + Test + Imager-2.0-Repository-JSON, auch lokal
lauffähig, ruft genau diese Make-Targets auf) beschreibt
[GitHub-Image-Workflow.md](GitHub-Image-Workflow.md); einen Überblick über
pi-gen selbst (Stages, Config, Docker) liefert
[Pi-Gen-Tool.md](Pi-Gen-Tool.md).

## Voraussetzungen

- **Docker-Weg (empfohlen):** Docker Engine; `docker ps` muss ohne Fehler
  laufen.
- **Nativer Weg:** Debian-basiertes OS plus Paketliste (Details im
  [nativen Abschnitt](#nativer-build-ohne-docker)); Ubuntu ≤ 22.04 braucht
  zusätzlich ein neueres `debian-archive-keyring` (Trixie-Keys).
- **Beide Wege:** 20–40 GB Plattenplatz, Dauer 30 min bis mehrere Stunden;
  Pfad ohne Leerzeichen (debootstrap-Beschränkung).

## Build mit Make (empfohlener Weg)

Das Makefile im Repo-Root ist der Thin-Wrapper für Setup, Build und Test —
dieselben Targets nutzt der geplante CI-Lauf
([GitHub-Image-Workflow.md](GitHub-Image-Workflow.md), § 2). `make help`
listet alle Targets; die wichtigsten Variablen: `MODE`
(`stage-custom`, Default | `overlay`, Legacy), `VARIANT` (`headless`,
Default | `desktop`), `ENGINE` (`docker`, Default | `native`),
`CONTINUE`/`PRESERVE_CONTAINER`/`CLEAN` (pi-gen-Flags).

```bash
make venv      # venv + Testabhängigkeiten (Datei-Abhängigkeit zu tests/requirements.txt)
make lint      # shellcheck + Overlay-Tests (ohne Docker/Image)
make setup     # pi-gen @ Pin prüfen, SKIP_IMAGES setzen, Variante schalten
make build     # Docker-Build; deploy/ + build-docker.log landen in ros-pi-gen/deploy/
make test      # Testinfra (Gruppe Q) gegen das frisch gebaute Image
make ci        # alles nacheinander: venv lint setup build test
```

Was `make setup` (Default `MODE=stage-custom`) tut:

- prüft, dass das Submodul genau auf dem gepinnten Commit steht (wird nie
  automatisch geändert — Pin-Updates sind bewusste Commits)
- setzt `pi-gen/stage2/SKIP_IMAGES` (in pi-gens `.gitignore` enthalten → der
  Submodul-Status bleibt sauber): `stage2` läuft vollständig durch
  (01-sys-tweaks bis 04-cloud-init), exportiert aber **nicht**; exportiert
  wird aus `stage-custom` (dort liegt `EXPORT_IMAGE`)
- schaltet die Varianten-Sub-Stages per SKIP-Datei (siehe
  [Variante wählen](#variante-wählen-headless-vs-desktop))
- entfernt Overlay-Reste aus `pi-gen/stage2` (Rückstände eines
  `MODE=overlay`-Laufs würden sonst doppelt/falsch ausgeführt)

`make build` (Default `ENGINE=docker`) ruft `pi-gen/build-docker.sh` aus dem
Repo-Root auf und mountet `stage-custom` (read-only) und `work/` in den
Build-Container; `deploy/` wird vom Skript per `docker cp` ohnehin in das
Aufruf-Verzeichnis kopiert — alles liegt damit in ros-pi-gen, nicht im
Submodul. Nützliche pi-gen-Flags durchreichen:

- `make build CONTINUE=1` – nach Fehler im Container fortsetzen
- `make build PRESERVE_CONTAINER=1` – Container `pigen_work` behalten
  (z. B. zum Debuggen: `sudo docker run -it --privileged
  --volumes-from=pigen_work pi-gen /bin/bash`)
- `docker rm -v pigen_work` – alten Container aufräumen

Der Deploy-Dateiname folgt `image_<Datum>-<IMG_NAME><IMG_SUFFIX>`; das
`-lite` kommt aus `stage-custom/EXPORT_IMAGE` (aus pi-gens stage2
übernommen, `IMG_SUFFIX="-lite"`) — ein Env-`IMG_SUFFIX` wird beim Export
vom Stage überschrieben (build.sh:337 sourced die Stage-Datei). Flashen per
Raspberry Pi Imager (**Use custom**) oder `dd`/`balenaEtcher`.

### Entwicklung: schnelle Iteration

pi-gens SKIP-Mechanismus (README „Skipping stages to speed up development“)
funktioniert unverändert — SKIP-Dateien in bereits gebauten Stages/
Sub-Stages (in `pi-gen/stage2/` bzw. `stage-custom/`, gitignored), dann
`make build CONTINUE=1 PRESERVE_CONTAINER=1`; `SKIP_IMAGES` in
`stage-custom` spart den Image-Export während der Iteration. Rezept und
RootFS-Seeding: [Ansible-im-Build.md](Ansible-im-Build.md). Achtung:
SKIP-Dateien nach dem Test wieder entfernen (Vollbuild als periodischer
Verifizierungsschritt).

## Overlay einbringen (Legacy, `MODE=overlay`)

Der frühere Weg — Kopieren der Stages in den pi-gen-Tree — bleibt als
Fallback erhalten (`make setup MODE=overlay[VARIANT=…]`), falls ein Lauf
ohne Mount-Mechanik nötig ist. Er hat die bekannten Nachteile (gerichtete
cps, dirty Submodul-Tree) und rendert die config nach `pi-gen/config` um
(`STAGE_LIST` nur bis stage2 + `PIGEN_VARIANT`, wie früher):

```bash
# was make setup MODE=overlay macht (manuell):
git submodule update --init && git -C pi-gen checkout 74d08a3
cp -r stage-custom/05-docker-ansible stage-custom/07-accesspopup pi-gen/stage2/
cp -r stage-custom/06-variant-headless pi-gen/stage2/06-variant   # bzw. 06-variant-desktop
sed 's@^export STAGE_LIST=.*@export STAGE_LIST="${BASE_DIR}/stage0 ${BASE_DIR}/stage1 ${BASE_DIR}/stage2"@' config > pi-gen/config
echo "export PIGEN_VARIANT='headless'" >> pi-gen/config           # bzw. desktop
```

- **`config`:** pi-gen versioniert `config` nicht (git-ignored) — der
  Schritt **erzeugt** sie neu (bzw. überschreibt eine alte). Inhalt: `IMG_NAME`
  (→ Name des Work-Dir `work/<IMG_NAME>`), `RELEASE=trixie`, `ARCH=arm64`,
  `STAGE_LIST`, `ENABLE_SSH=1`, `LOCALE_DEFAULT=de_DE.UTF-8`,
  `TIMEZONE_DEFAULT=Europe/Berlin`, `WPA_COUNTRY` (Build-Fallback `DE`;
  zur Laufzeit setzt i. d. R. der Pi-Imager die Regulierungsdomäne).

**Achtung ab Imager 2.0:** Beim lokalen Custom-Image über **Use custom** wird
die OS-Customization (Hostname, Schul-WLAN, SSH …) **ausgelassen** – sie ist
erst wieder möglich, wenn das Image über ein Repository-JSON eingebunden wird
(`init_format`, Details und Wege: siehe
[Raspberry-Pi-Imager-2.0.md](Raspberry-Pi-Imager-2.0.md)). Der
Schul-WLAN-Workflow in der
[WLAN-Anleitung](WLAN-Anleitung.md#wlan-am-roboter-einrichten--anleitung-für-einsteiger)
setzt darauf auf. Imager 1.x ist untauglich (nimmt fälschlich
`init_format: systemd` an ⇒ Customization auf Trixie wirkungslos, Beleg:
`doc/os_customisation_formats.md` im rpi-imager-Repo) – bitte **Imager
≥ 2.0.6** verwenden. Das Image erfüllt die Customization-Voraussetzungen
(cloud-init + NoCloud auf bootfs + NetworkManager/Netplan, seit Build
2026-09-20 belegt; `ENABLE_CLOUD_INIT=1` ist in der `config` gepinnt).
Ausstehend: Repository-JSON für das Image (TODO Block 4).

## Nativer Build (ohne Docker)

Nur wählen, wenn Docker nicht zur Verfügung steht. pi-gen läuft nativ auf
Debian-basierten Systemen; für **Trixie-Ziele (2025)** sollte der Host selbst
aktuell sein — bei älteren Hosts (z. B. Ubuntu 22.04) können nach dem
Bootstrap weitere Inkompatibilitäten auftreten, die im Docker-Container
nicht existieren.

Benötigte Pakete (laut `depends` des pi-gen-Checkouts):

```bash
sudo apt install coreutils quilt parted debootstrap zerofree zip dosfstools \
  e2fsprogs libarchive-tools libcap2-bin grep rsync xz-utils file git curl \
  bc gpg pigz xxd arch-test bmap-tools kmod
```

Zusätzlich beachten:

- **Cross-Build von x86_64:** `qemu-user-static` statt `qemu-user-binfmt`
  installieren (Ubuntu-Binaries sind dynamisch gelinkt und scheitern im
  Chroot). Prüfung: `arch-test arm64` → `arm64: ok`.
- **Ubuntu ≤ 22.04 (jammy):** `debian-archive-keyring` (Version 2021.1.1)
  enthält die Debian-Trixie-Keys nicht — der Stage-0-Bootstrap bricht mit
  `E: Release signed by unknown key` ab. Neueres Paket von Debian
  installieren (Host-Setup, Schritt 2) oder auf den Docker-Weg ausweichen.

### Host-Setup Ubuntu 22.04 (jammy) – offene Schritte

Checkliste für den nativen Build (Befehle sind idempotent, ggf.
wiederholen):

```bash
# 1) pi-gen-Abhängigkeiten (qemu-user-static statt qemu-user-binfmt)
sudo apt install coreutils quilt parted qemu-user-static debootstrap \
  zerofree zip dosfstools e2fsprogs libarchive-tools libcap2-bin grep rsync \
  xz-utils file git curl bc gpg pigz xxd arch-test bmap-tools kmod

# 2) debian-archive-keyring aktualisieren (jammys 2021.1.1 kennt keine
#    Trixie-Keys → "Release signed by unknown key")
wget -O /tmp/debian-archive-keyring_2025.1_all.deb \
  http://deb.debian.org/debian/pool/main/d/debian-archive-keyring/debian-archive-keyring_2025.1_all.deb
sudo dpkg -i /tmp/debian-archive-keyring_2025.1_all.deb

# 3) Partielles Bootstrap-Verzeichnis eines abgebrochenen Laufs entfernen
#    (sonst überspringt stage0/prerun.sh den Bootstrap und der Build
#    scheitert später im unvollständigen rootfs)
sudo rm -rf work/<IMG_NAME>/stage0

# 4) Nativer Build starten (setzt STAGE_LIST/WORK_DIR/DEPLOY_DIR selbst)
make build ENGINE=native 2>&1 | tee build.log
```

Verifikation nach Schritt 2: `dpkg -l debian-archive-keyring` muss
`2025.1` (oder neuer) zeigen.

Das Image landet wie beim Docker-Weg in `ros-pi-gen/deploy/`. Technisch
setzt `make build ENGINE=native` `STAGE_LIST` (absolute Pfade auf
`pi-gen/stage0 stage1 stage2` + `stage-custom`), `WORK_DIR` und
`DEPLOY_DIR` als Env-Variablen und ruft `build.sh` aus dem Submodul auf —
der Aufruf-cwd `pi-gen/` ist nötig, damit pi-gen den Submodul-Commit
(`GIT_HASH`, landet in der `.info`-Datei) und nicht den ros-pi-gen-Commit
vermerkt; die Testinfra prüft genau diesen Pin (Q0b).

## Build in der VM (robotics-lab-vm)

Alternative Build-Umgebung: eine Ubuntu-24.04-VM ([robotics-lab-vm](https://codeberg.org/kraeml/robotics-lab-vm),
als git-Submodul unter `vm/robotics-lab-vm` eingebunden, gesteuert per
Vagrant/VirtualBox). Der Grund: der Build-Host hier ist Ubuntu 20.04 mit
qemu-user-static 4.2.1, dessen binfmt-Emulation OFD-Dateisperren nicht
unterstützt (Details: [TODO.md](TODO.md), Block 3) — `make build` umgeht
das per temporärem binfmt-Entry. In der VM (qemu-user-static ≥ 8) greift
das **Version-Gate** (`tools/binfmt.sh`): der Kernel bleibt **komplett
unangetastet**, kein Entry wird gesetzt. Plus CI-Parität — GitHub-Runner
fahren ebenfalls 24.04.

Die Box `ubuntu-2404-desktop` (26.09.11, lokal registriert — kein
Download) bringt Docker CE, qemu-user-static und binfmt-support bereits
mit; die `robot_pigen`-Rolle der Box bleibt bewusst **ungenutzt** (sie
implementiert das alte Overlay-Verfahren mit anderem pi-gen-Pin) — der
stage-custom-Workflow dieses Repos kommt per `vm-sync` mit.

```bash
make vm-up vm-bootstrap vm-sync   # VM starten, prüfen, Repo übertragen (~5 MB)
make vm-build                     # Setup + Docker-Build in der VM (~1 h)
make vm-test                      # Gruppe Q in der VM (Docker + binfmt dort)
make vm-artifacts                 # Image + Logs holen → deploy/vm/
# oder alles: make vm-ci
```

- **SSH:** `make vm-ssh` (passwortlos, `vagrant ssh`); code-server (Passwort
  `change_me`) und JupyterLab unter der Host-Only-IP der VM: Default
  `192.168.33.10`, hier `VM_IP=192.168.33.11` (die Default-IP ist durch
  die laufende pi-gen-Dev-VM belegt — Vagrantfile liest die ENV
  `VM_IP`, Submodul-Bump). Das Repo liegt in der VM unter
  `~/build/ros-pi-gen` — bewusst **nicht** im geteilten Ordner
  (vboxsf ist für Builds zu langsam).
- **VM-Name:** `VM_NAME=ros-pi-gen` (Default im Makefile) — die Box-VM
  fürs Unterrichtsmaterial heißt `robotics`; Parallelbetrieb kollidiert
  nicht mehr (Vagrantfile liest `VM_NAME` aus der Umgebung).
- **Disk:** `VM_DISK=80GB` (Default) einmalig beim ersten `vm-up` —
  Vagrant vergrößert die Box-Disk einmalig; später ändern heißt
  `make vm-destroy` + neu. Bedarf: Box ~18 GB + Build 20–40 GB +
  Testcache ~12 GB.
- **Varianten/Iteration:** `make vm-build VARIANT=desktop`,
  `make vm-build CONTINUE=1` — dieselben Variablen wie beim Host-Build,
  sie fließen durch.
- **Erste Docker-Nutzung in frischer SSH-Session:** falls `docker ps`
  mit „permission denied" antwortet, einmal neu einloggen (`exit` +
  `make vm-ssh`) oder `newgrp docker` — die Gruppenmitgliedschaft greift
  pro Login-Session.

## Variante wählen (headless vs. desktop)

Die Variante wird über die **Sub-Stage-Auswahl** in `stage-custom`
geschaltet — es gibt zwei parallele Sub-Stages, `make` entfernt per
SKIP-Datei (pi-gen-Konvention: Sub-Stages mit `SKIP` werden übersprungen)
immer genau eine:

| Variante | aktive Sub-Stage | `00-packages` | Image-Ergebnis |
|---|---|---|---|
| headless (Default) | `06-variant-headless` | openssh-server, network-manager | Headless-Image |
| desktop | `06-variant-desktop` | + xfce4, lightdm, xserver-xorg | XFCE-Desktop mit LightDM |

- Die Desktop-Sub-Stage aktiviert LightDM in `01-run.sh` **bedingtungslos** —
  die Existenz der Sub-Stage ist der Schalter (kein Varianten-Flag muss in
  den Build-Container gelangen).
- headless- und Desktop-Paketliste sind committet und koexistieren —
  **kein gerichteter `cp` mehr**, der die eine Liste durch die andere
  ersetzt.
- Die SKIP-Dateien sind gitignored; `make setup` setzt sie bei jedem Lauf
  konsistent zum `VARIANT`-Wert (Mismatch ist ausgeschlossen).

**headless (Default):** nichts weiter tun — `make setup` wählt sie.

**desktop:**

```bash
make build VARIANT=desktop     # (macht setup VARIANT=desktop inklusive)
```

**Rückweg zu headless:** `make setup` (Default).

## AccessPopup – WLAN-AP-Fallback mit Web-UI

Stage `07-accesspopup` installiert [AccessPopup](https://github.com/RaspberryConnect/AccessPopup)
(RaspberryConnect, gepinnter Commit `ba6eff1…`, Lizenz GPL-3.0, siehe
`stage-custom/07-accesspopup/files/VENDORED.md`) **unverändert** und ergänzt
projektspezifische Bausteine. AccessPopup bleibt für den AP↔WLAN-Wechsel
zuständig (NetworkManager-AP-Modus, Prüfzyklus alle 2 Minuten, kein hostapd).

**Verhalten:**

- Kein bekanntes WLAN erreichbar (oder keins konfiguriert) → temporärer AP
- Wieder ein bekanntes WLAN in Reichweite → Verbindung dorthin, AP schaltet ab
- Schul-/Heim-WLAN koexistieren als NM-Profile (Schul-WLAN kommt per
  Pi-Imager; Home-WLAN wird per Portal ergänzt)

**Defaults (vorbelegt):**

| Einstellung | Wert | Herkunft |
|---|---|---|
| AP-SSID | `<hostname>-AP` (z. B. `roboter-07-AP`), Fallback `Roboter-AP` | `hostname-ssid.service` leitet sie beim Boot aus dem Hostnamen ab (Hostname via Pi-Imager = Geräteidentität) |
| AP-Passwort | `Pi-WLAN-Setup-2026` | vorbelegt in `files/accesspopup.conf` (Kursmaterial) |
| AP-IP | `192.168.50.5` | `files/accesspopup.conf` |

**Konfiguration per Browser (ohne CLI):**

1. Mit der AP-SSID des eigenen Roboters verbinden
2. Bei üblichen Clients (iOS/Android/Windows) öffnet sich das Portal
   automatisch (DNS-Wildcard + Port-80-Redirect auf die Web-UI); sonst
   manuell `http://192.168.50.5:8052` aufrufen
3. „Add New WiFi Network" → WLAN wählen/SSID eingeben, Passwort setzen →
   Profil wird via NetworkManager gespeichert → Seite timeoutet absichtlich:
   **jetzt mit dem neuen WLAN verbinden**; der Pi wechselt im nächsten
   Prüfzyklus (≤ 2 min) und der AP verschwindet

**Web-UI nur im AP-Fenster:** die Web-Units (Port 8052) sind im Image
deaktiviert und werden vom NM-Dispatcher
(`/etc/NetworkManager/dispatcher.d/90-accesspopup-portal`) ausschließlich
gestartet, während der AP aktiv ist – im Schul-/Heim-LAN ist die
unauthentifizierte Oberfläche nicht erreichbar.

**AP-Clients sind isoliert:** während der AP aktiv ist, lädt der Dispatcher
eine nftables-Regelgruppe (Priorität vor NetworkManagers shared-NAT):
AP-Clients dürfen nur DHCP, DNS, Portal (80/8052) und mDNS — kein Internet,
kein SSH, kein Docker/ROS-Zugriff. Bei AP-Ende wird die Regelgruppe entfernt.

**Betreiber-/Admin-Hinweise:**

- Hostnamen ändern (z. B. über SSH): der NM-Dispatcher reagiert auf das
  `hostname`-Event und setzt die AP-SSID neu (`<neuer-hostname>-AP`)
- Dauer-AP erzwingen (z. B. um im laufenden WLAN ein weiteres Profil zu
  setzen): `sudo accesspopup -a`, zurück mit `sudo accesspopup`
- Passwort/SSID des AP ändern: `/etc/accesspopup.conf` (`ap_pw`/`ap_ssid`)
  und bestehendes Profil löschen: `sudo nmcli con del AccessPopup` — beim
  nächsten AP-Start wird das Profil mit den neuen Werten neu erzeugt
- Lange AP-Nutzung (>10 min): Passwort ändern, Zugriff auf die unauthenti-
  fizierte Web-UI bedenken

**Bekannte Grenzen:** der AP↔WLAN-Wechsel unterbricht laufende SSH/VNC-
Verbindungen; WLAN-Scan während aktivem AP ist je nach WLAN-Chip nicht
möglich — die Web-UI bietet dann die manuelle SSID-Eingabe.

## Testinfra (Gruppe Q automatisiert)

Unter `tests/` automatisiert eine pytest-Suite die Gruppe Q des
[Abnahmeprotokolls](Testprotokoll-AccessPopup.md) in drei Ebenen:

1. **Build-Log** (Q0): Commit gepinnt, alle Stages gelaufen (kein `Skip`),
   docker-ce/ansible-Installation belegbar.
2. **Image-Inhalt** (Datei-Manifest + Q1a, Q2–Q9): Dateien per debugfs direkt
   im Image, Container-Boot, Unit-States, conf/nft/visudo/Dispatcher.
3. **Hardware** (`tests/tools/pi-smoke.sh`): Gruppe Q final am echten Pi per
   SSH — Q6 (`nft -c`) am echten bcm-Kernel.

```bash
.venv/bin/python -m pytest tests     # oder: tests/run_tests.sh
ssh pi@<ip> 'bash -s' < tests/tools/pi-smoke.sh        # Hardware-Lauf
```

Details, Grenzen und die Begründung zum verworfenen QEMU-Kernel-Boot-Test:
[tests/README.md](tests/README.md). Nach jedem Rebuild ausführen; solange
das Image die Stage nicht enthält, schlagen Q2–Q9 mit Verweis auf den nötigen
Rebuild fehl (beabsichtigt).

```bash
make test                          # venv + pytest-Suite
PIGEN_TEST_IMAGE=/pfad/img.xz make test   # Image explizit wählen
```

Die Image-Suche deckt `deploy/` (Docker-Build) und `pi-gen/deploy/`
(nativ/manuell) ab; Q0f akzeptiert Varianten-Sub-Stages in
`stage-custom` wie auch alte `stage2/06-variant`-Logs.

## Troubleshooting

### `Container pigen_work already exists and you did not specify CONTINUE=1` (Docker-Weg)

Ein alter Build-Container liegt noch herum (pi-gen behält ihn nur bei
`PRESERVE_CONTAINER=1` oder nach Abbruch). Räumen:

```bash
make clean-container      # = docker rm -v pigen_work
```

Läuft der Container gerade, bricht pi-gen selbst ab (kein zweiter
paralleler Build). **Vorsicht mit `make build CONTINUE=1`:** der
Weiterbau hängt sich per `--volumes-from` an die Mounts des *alten*
Containers — das ist nur für Fortsetzen desselben Laufs (Abbruch mit
`PRESERVE_CONTAINER=1`) sinnvoll, nicht für einen frischen Build. Ein
exited/created-Container von früher blockiert `make build` ohnehin mit
einem klaren Hinweis (Guard im Makefile), statt der generischen
pi-gen-Meldung.

### `E: Release signed by unknown key (key id 762F67A0B2C39DE4)` (nur nativer Weg)

Der Stage-0-Bootstrap (`debootstrap`) prüft die Signatur der Debian-
Release-Datei gegen `/usr/share/keyrings/debian-archive-keyring.gpg` vom
**Host**. Auf Ubuntu 22.04 stammt die Datei aus `debian-archive-keyring`
2021.1.1 und enthält die Trixie-Schlüssel nicht – `debootstrap.log` listet
drei fehlende Keys (`4CB50190…E131`, `B8E5F131…F2265`, EDDSA
`41587F7D…39DE4`; alle drei sind im 2025.1-Keyring enthalten). Abhilfe:
Paket `debian-archive-keyring` 2025.1 von Debian installieren (Host-Setup,
Schritt 2) oder Docker-Weg nutzen (aktuelles Keyring im
`debian:trixie`-Container — dieser Fehler kann dort nicht auftreten). Die
Meldung `rmdir … konnte nicht entfernt werden: Das Verzeichnis ist nicht
leer` ist nur ein Symptom desselben Fehlers.

### `config: Zeile 12: BASE_DIR ist nicht gesetzt` (Docker-Weg, historisch)

`build-docker.sh` sourced `config` mit `set -u`, **bevor** `BASE_DIR`
existiert (nur `build.sh` setzt `BASE_DIR` selbst vor dem Sourcing). Da die
config `STAGE_LIST` über `${BASE_DIR}` aufbaut, führt das zur
unbound-variable-Warnung. **Fix ist eingebaut** — BASE_DIR-Fallback am
Anfang der config:

```bash
export BASE_DIR="${BASE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
```

Im Container setzt `build.sh` `BASE_DIR=/pi-gen` vor dem Sourcing, der
Fallback greift daher nur auf dem Host – die Stage-Pfade bleiben korrekt.

### Abgebrochener Bootstrap: `bootstrap failed: please check …/debootstrap.log` (nativ)

Ein abgebrochener Lauf hinterlässt ein partielles
`work/<IMG_NAME>/stage0/rootfs`. Der nächste Lauf überspringt den Bootstrap
(`stage0/prerun.sh` bootstrappt nur, wenn `ROOTFS_DIR` fehlt) und scheitert
später im unvollständigen rootfs. Vor dem Neustart `work/<IMG_NAME>/stage0`
löschen oder mit `make build ENGINE=native CLEAN=1` bauen – `CLEAN=1`
entfernt `ROOTFS_DIR` vor `prerun.sh` und erzwingt einen frischen Bootstrap.

### `Failed to take /etc/passwd lock: Invalid argument` (stage0-Bootstrap, Docker-Weg)

Die systemd-Postinst im stage0-Bootstrap scheitert, wenn der
binfmt-Interpreter ein **altes Host-qemu-user-static** ist (beobachtet:
qemu 4.2.1 auf Ubuntu 20.04 — dessen fcntl-Emulation unterstützt
OFD-Dateisperren (`F_OFD_SETLKW`) nicht und liefert EINVAL). `make build`
registriert deshalb automatisch einen **temporären binfmt-Entry**
(`qemu-aarch64-rpi`) auf das moderne qemu aus dem pi-gen-Container
(trixie: 10.x) und räumt ihn nach dem Lauf wieder ab (auch bei Fehler);
kein dauerhafter Host-Eingriff. Der Entry lässt sich händisch verwalten:
`make binfmt-setup` / `make binfmt-cleanup` (`tools/binfmt.sh`).
Alternativ (native Builds ohne Docker): `qemu-user-static` auf dem Host
aktualisieren (z. B. das trixie-Paket, analog zum Keyring-Rezept oben).
Zusatzbefund: pi-gens eigener Fallback-String in `build-docker.sh` ist
unwirksam (24-Byte-Magic gegen 20-Byte-Mask → EINVAL) — daher der eigene
Registrierungsweg; Details: [TODO.md](TODO.md), Block 3 (Build-Umgebung,
zwei Gleise — u. a. Ubuntu-Vagrant-VM 24.04 als künftige Build-Umgebung).

**Randfall nach `apt upgrade qemu-user-static`:** der Kernel hält bei
F-Flag-Entrys den Interpreter als **Inode-Referenz** offen — nach einem
Upgrade am selben Pfad läuft der Build trotzdem mit der **alten** Version
weiter, während `--version` am Pfad die neue zeigt. Symptom: passwd-lock-
Fehler trotz moderner Version am Pfad. Abhilfe: Entry löschen/neu
registrieren (`make binfmt-cleanup && make binfmt-setup` bzw. der
sudo-Einzeiler aus der binfmt-Meldung) oder rebooten — das Version-Gate
liest den Pfad und kann die Inode-Diskrepanz nicht erkennen.

### `arm64: not supported on this machine/kernel` (nativ)

Cross-Build von x86_64 braucht `binfmt_misc` + qemu: `modprobe binfmt_misc`
und `qemu-user-static` installieren; Prüfung mit `arch-test arm64`
(→ `arm64: ok`). Details in der pi-gen-README (Abschnitt `binfmt_misc`).
Der Docker-Build registriert qemu-aarch64 nötigenfalls selbst im Container.

## Struktur

| Datei | Zweck |
|---|---|
| `config` | pi-gen-Konfiguration (IMG_NAME, RELEASE=`trixie`, `STAGE_LIST`, `ENABLE_SSH`, Locale/Zeitzone) |
| `pi-gen/` | git-Submodul (arm64-Branch, gepinnt `74d08a3`) — unverändert pristine; Updates nur durch bewusste Pin-Änderung |
| `stage-custom/` | eigenes Stage-Dir, hängt per `STAGE_LIST` hinter pi-gens stage2; enthält `prerun.sh` (copy_previous) + `EXPORT_IMAGE` (Export aus diesem Stage) |
| `stage-custom/05-docker-ansible/` | Docker (offizielles docker.com-Repository, Suite `trixie`) + Ansible + Werkzeuge |
| `stage-custom/06-variant-headless/` | Headless-Pakete (openssh-server, network-manager); wird per SKIP-Datei aktiviert (Default) |
| `stage-custom/06-variant-desktop/` | Desktop-Pakete (xfce4, lightdm, xserver-xorg); `01-run.sh` aktiviert LightDM bedingungslos — Existenz der Sub-Stage = Schalter |
| `stage-custom/07-accesspopup/` | AccessPopup (AP-Fallback, gepinnt `ba6eff1…`, GPL-3.0) + Web-UI + Captive-Redirect + nftables-Isolation + hostname-SSID; Details im [AccessPopup-Abschnitt](#accesspopup--wlan-ap-fallback-mit-web-ui) |
| `Makefile` | Thin-Wrapper: `venv lint setup build test ci` (identisch lokal wie in CI, siehe [GitHub-Image-Workflow.md](GitHub-Image-Workflow.md), § 2) + VM-Targets (`vm-*`, siehe [Build in der VM](#build-in-der-vm-robotics-lab-vm)) |
| `tools/binfmt.sh` | qemu-Emulation-Entry: Version-Gate (Host-qemu ≥ 8 → kein Eingriff) + temporärer Container-qemu-Entry für ältere Hosts |
| `tools/build-docker.sh` | Build-Orchestrierung: binfmt-Entry setzen → build-docker.sh → cleanup immer (trap EXIT/INT/TERM, Ctrl+C inklusive) |
| `vm/robotics-lab-vm/` | git-Submodul ([robotics-lab-vm](https://codeberg.org/kraeml/robotics-lab-vm)) — Vagrant-VM Ubuntu 24.04 als Build-Umgebung (siehe [Build in der VM](#build-in-der-vm-robotics-lab-vm)) |
| `work/`, `deploy/` | Build-Erzeugnisse (gitignored): pi-gen-Arbeitsverzeichnis bzw. Image + `build-docker.log` |

## Konventionen

- **Nummerierung:** pi-gen liefert in `stage2/` bereits Sub-Stages `01-…`
  bis `04-…`; die eigenen laufen in `stage-custom/` danach als `05-`,
  `06-…` und `07-` (pi-gens Sub-Stage-Schleife sortiert je Stage-Dir
  alphanumerisch — die Aufteilung auf zwei Dirs ändert an der
  Ausführungsreihenfolge nichts).
- **Kein `VARIANT` als Variablenname:** console-setup (`setupcon`) nutzt
  `VARIANT` als Konfig-Suffix im Chroot — der Build bricht sonst an
  fehlenden `keyboard.headless`-Dateien. Die Variante steckt heute in der
  Sub-Stage-Auswahl (`06-variant-headless`/`06-variant-desktop`), nicht in
  einer Build-Variable; das heutige `PIGEN_VARIANT` entfällt daher.
- **`STAGE_LIST`:** `stage0 stage1 stage2 stage-custom` (Basis + eigene
  Stages, Export aus stage-custom; stage2 exportiert nicht — SKIP_IMAGES
  von `make setup`). Stage 3–5 des arm64-Branches bauen RPi-OS-Desktop-
  Varianten und exportieren eigene Images — für dieses Projekt nicht
  gewünscht.
- **`on_chroot`-Heredocs:** `NN-run.sh` läuft auf dem Build-Host; Chroot-
  Kommandos in `on_chroot << EOF … EOF`. `${RELEASE}`, `${ARCH}` und
  `${FIRST_USER_NAME}` expandieren build.sh-seitig.
- **`systemctl enable`** statt `start`: die Chroot hat kein laufendes
  systemd; aktiviert wird nur der Autostart für den ersten Boot.

## Erster Benutzer

pi-gen legt den ersten Benutzer (`FIRST_USER_NAME=pi`) standardmäßig erst
**beim ersten Boot** an (Setup-Assistent). Der `usermod -aG docker` in
`05-docker-ansible/03-run.sh` greift daher nur, wenn der Benutzer im Build
existiert (`FIRST_USER_PASS` + `DISABLE_FIRST_BOOT_USER_RENAME=1` in der
`config`) — ansonsten nach dem ersten Start manuell:
`sudo usermod -aG docker <benutzer>`.
