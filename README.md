# ros-pi-gen – pi-gen-Overlay für eigene Raspberry-Pi-Images

Eigenes arm64-Image für Raspberry Pi 3+/4/5 auf Basis von Debian Trixie mit
Docker CE und Ansible. Dieses Repo enthält die pi-gen-Konfiguration (`config`)
und eigene Stages (`stage2/05-docker-ansible`, `stage2/06-variant`), die als
Overlay auf einen [pi-gen](https://github.com/RPi-Distro/pi-gen)-Checkout
(arm64-Branch) gelegt werden.

**Empfohlener Weg:** Build mit Docker — der `debian:trixie`-Container bringt
Keyring, debootstrap und qemu aktuell mit, auf dem Host ist nur Docker Engine
nötig. Der native Build ist die Rückfallebene ohne Docker (→
[Nativer Build](#nativer-build-ohne-docker)). Damit das Overlay-Kopieren
mittelfristig entfällt: siehe [TODO.md](TODO.md).

## Voraussetzungen

- **Docker-Weg (empfohlen):** Docker Engine; `docker ps` muss ohne Fehler
  laufen.
- **Nativer Weg:** Debian-basiertes OS plus Paketliste (Details im
  [nativen Abschnitt](#nativer-build-ohne-docker)); Ubuntu ≤ 22.04 braucht
  zusätzlich ein neueres `debian-archive-keyring` (Trixie-Keys).
- **Beide Wege:** 20–40 GB Plattenplatz, Dauer 30 min bis mehrere Stunden;
  Pfad ohne Leerzeichen (debootstrap-Beschränkung).

## Overlay einbringen (beide Wege)

```bash
# pi-gen klonen (arm64-Branch) und auf gepinnten Commit halten
git clone --branch arm64 https://github.com/RPi-Distro/pi-gen.git
cd pi-gen
git checkout 74d08a3   # aktuell gepinnter Commit (Stand: 2026-09)

# Overlay einbringen — Reihenfolge beachten: erst Overlay, dann Varianten-cp
cp -r /pfad/zum/ros-pi-gen/stage2/* stage2/
cp /pfad/zum/ros-pi-gen/config config
```

Was die beiden `cp`-Befehle bewirken:

- **`stage2/*`:** legt die eigenen Sub-Stages in pi-gens `stage2/` ab —
  `05-docker-ansible/` (Docker CE + Ansible) und `06-variant/` (Paketlisten
  headless/desktop). Der Overlay-cp muss vor jeder Varianten-Änderung laufen,
  da er `06-variant/00-packages` neu anlegt (headless-Liste).
- **`config`:** pi-gen versioniert `config` nicht (git-ignored) — der Befehl
  **erzeugt** sie neu (bzw. überschreibt eine alte). Inhalt: `IMG_NAME` (→
  Name des Work-Dir `work/<IMG_NAME>`), `RELEASE=trixie`, `ARCH=arm64`,
  `STAGE_LIST` (nur Stage 0–2, Export aus Stage 2), `ENABLE_SSH=1`,
  `LOCALE_DEFAULT=de_DE.UTF-8`, `TIMEZONE_DEFAULT=Europe/Berlin` und
  `PIGEN_VARIANT='headless'` (Default-Variante, siehe
  [Variante wählen](#variante-wählen-headless-vs-desktop)).
- **`stage2/06-variant/00-packages.desktop`** ist eine **inerte
  Master-Vorlage**: pi-gen liest ausschließlich Dateien namens `NN-packages`
  und installiert die `.desktop`-Datei niemals von selbst.

## Build mit Docker (empfohlener Weg)

`build-docker.sh` baut ein pi-gen-Image auf Basis `debian:trixie` (das
`Dockerfile` übernimmt per `COPY . /pi-gen/` Overlay und config in den
Container) und führt den Build darin aus. Dadurch sind auf dem Host **keine
weiteren Abhängigkeiten** nötig: Keyring, debootstrap und qemu-aarch64 sind
im Container aktuell; das Host-Problem mit dem jammy-Keyring (siehe
[Troubleshooting](#troubleshooting)) tritt hier gar nicht erst auf.

```bash
./build-docker.sh
```

Nützliche Varianten (dokumentiert in der pi-gen-README):

- `CONTINUE=1 ./build-docker.sh` – nach Fehler im Container fortsetzen
- `PRESERVE_CONTAINER=1 ./build-docker.sh` – Container `pigen_work`
  behalten (z. B. zum Debuggen: `sudo docker run -it --privileged
  --volumes-from=pigen_work pi-gen /bin/bash`)
- `docker rm -v pigen_work` – alten Container aufräumen

Das fertige Image samt `build-docker.log` landet in `deploy/`. Flashen per
Raspberry Pi Imager (**Use custom**) oder `dd`/`balenaEtcher`.

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
sudo rm -rf <pi-gen-clone>/work/<IMG_NAME>/stage0

# 4) Nativer Build starten
sudo ./build.sh 2>&1 | tee build.log
```

Verifikation nach Schritt 2: `dpkg -l debian-archive-keyring` muss
`2025.1` (oder neuer) zeigen.

Das Image landet auch hier in `deploy/`.

## Variante wählen (headless vs. desktop)

Die Variante besteht aus **zwei zusammengehörigen Einstellungen**, die
übereinstimmen müssen:

| Variante | `PIGEN_VARIANT` in `config` | `stage2/06-variant/00-packages` | Image-Ergebnis |
|---|---|---|---|
| headless (Default) | `'headless'` | openssh-server, network-manager | Headless-Image |
| desktop | `'desktop'` | + xfce4, lightdm, xserver-xorg | XFCE-Desktop mit LightDM |

- `06-variant/01-run.sh` aktiviert LightDM **nur** bei
  `PIGEN_VARIANT=desktop`.
- Der Desktop-`cp` ersetzt die headless-Liste und ist **gerichtet** (die
  headless-Inhalte sind danach im Clone weg).

**headless (Default):** nichts weiter tun — Overlay-cp bringt
`00-packages` (headless) und `config` (`PIGEN_VARIANT='headless'`) bereits
konsistent mit.

**desktop:** genau zwei Schritte, nachdem das Overlay eingebracht ist:

```bash
# 1) Variante in der kopierten config umschalten
#    (in pi-gen/config: export PIGEN_VARIANT='desktop')
#    alternativ: ros-pi-gen/config ändern und cp erneut ausführen

# 2) Desktop-Paketliste aktivieren
cp stage2/06-variant/00-packages.desktop stage2/06-variant/00-packages
```

**Nicht konsistent mischen** — die Folgen bei Mismatch:

- `PIGEN_VARIANT='desktop'` **ohne** den cp: `systemctl enable lightdm`
  scheitert in `01-run.sh` (Unit fehlt) → **Build bricht ab**.
- cp **ohne** `PIGEN_VARIANT='desktop'`: xfce4/lightdm werden installiert,
  aber lightdm **nicht aktiviert** → Image wird groß, bleibt aber ohne
  Desktop-Autostart.

**Rückweg zu headless** (headless-Liste wiederherstellen):

```bash
cp /pfad/zum/ros-pi-gen/stage2/06-variant/00-packages stage2/06-variant/00-packages
# und in pi-gen/config: export PIGEN_VARIANT='headless'
```

## Troubleshooting

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
löschen oder mit `sudo CLEAN=1 ./build.sh` bauen – `CLEAN=1` entfernt
`ROOTFS_DIR` vor `prerun.sh` und erzwingt einen frischen Bootstrap.

### `arm64: not supported on this machine/kernel` (nativ)

Cross-Build von x86_64 braucht `binfmt_misc` + qemu: `modprobe binfmt_misc`
und `qemu-user-static` installieren; Prüfung mit `arch-test arm64`
(→ `arm64: ok`). Details in der pi-gen-README (Abschnitt `binfmt_misc`).
Der Docker-Build registriert qemu-aarch64 nötigenfalls selbst im Container.

## Struktur

| Datei | Zweck |
|---|---|
| `config` | pi-gen-Konfiguration (IMG_NAME, RELEASE=`trixie`, `PIGEN_VARIANT`, `STAGE_LIST`, `ENABLE_SSH`, Locale/Zeitzone) |
| `stage2/05-docker-ansible/` | Docker (offizielles docker.com-Repository, Suite `trixie`) + Ansible + Werkzeuge |
| `stage2/06-variant/` | Headless- (`00-packages`) vs. Desktop-Pakete (`00-packages.desktop`); `01-run.sh` aktiviert LightDM nur bei Desktop |

## Konventionen

- **Nummerierung:** pi-gen liefert in `stage2/` bereits Sub-Stages `01-…`
  bis `04-…`; die eigenen laufen danach als `05-` und `06-`.
- **`PIGEN_VARIANT` statt `VARIANT`:** console-setup (`setupcon`) nutzt
  `VARIANT` als Konfig-Suffix im Chroot — der Build bricht sonst an
  fehlenden `keyboard.headless`-Dateien. `PIGEN_VARIANT` wird von `config`
  exportiert und von `01-run.sh` geprüft.
- **`STAGE_LIST`:** Stage 0–2 (Basis + Custom-Stages, Export aus Stage 2).
  Stage 3–5 des arm64-Branches bauen RPi-OS-Desktop-Varianten und
  exportieren eigene Images — für dieses Projekt nicht gewünscht.
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
