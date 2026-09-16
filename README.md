# ros-pi-gen – pi-gen-Overlay für eigene Raspberry-Pi-Images

Eigenes arm64-Image für Raspberry Pi 3+/4/5 auf Basis von Debian Trixie mit
Docker CE und Ansible. Dieses Repo enthält die pi-gen-Konfiguration (`config`)
und eigene Stages (`stage2/05-docker-ansible`, `stage2/06-variant`), die als
Overlay auf einen [pi-gen](https://github.com/RPi-Distro/pi-gen)-Checkout
(armlink aarch64/arm64-Branch) gelegt werden.

## Standalone-Nutzung (ohne Ansible)

```bash
# pi-gen klonen (arm64-Branch, konkreten Commit prüfen)
git clone https://github.com/RPi-Distro/pi-gen.git
cd pi-gen
git checkout arm64

# Overlay einbringen
cp -r /pfad/zum/ros-pi-gen/stage2/* stage2/
cp /pfad/zum/ros-pi-gen/config config

# Variante wählen: headless (Default) oder desktop
#   headless:  config und stage2/06-variant/00-packages bleiben wie sie sind
#   desktop:   PIGEN_VARIANT in config auf 'desktop' setzen und:
cp stage2/06-variant/00-packages.desktop stage2/06-variant/00-packages

# Build (als root; 30 min bis mehrere Stunden, 20–40 GB frei)
sudo ./build.sh 2>&1 | tee build.log
```

Das fertige Image liegt unter `deploy/`. Flashen per Raspberry Pi Imager
(**Use custom**) oder `dd`/`balenaEtcher`.

### Docker-basierter Build (CI/CD-Grundlage)

pi-gen liefert `build-docker.sh`, das den Build in einem Docker-Container
ausführt — geeignet für CI/CD-Pipelines:

```bash
sudo ./build-docker.sh
```

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
