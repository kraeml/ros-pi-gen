# pi-gen: Raspberry-Pi-OS-Images wiederholbar bauen

Du willst mehrere Raspberry Pis mit derselben Software ausliefern? Dann ist ein manuell eingerichtetes System eine schlechte Vorlage. Beim zweiten Gerät fehlt garantiert etwas – beim fünften weiß niemand mehr, was eigentlich geändert wurde.

**pi-gen** baut Raspberry-Pi-OS-Images aus Debian-Dateisystemen, Skripten und sogenannten Stages (Bauphasen). Das Ergebnis ist konfigurierbar und wiederholbar. Bit-identische Images entstehen dadurch allerdings nicht automatisch: Paketstände, Zeitstempel, Bootloader, Firmware und Build-Umgebung können sich ändern.

Die folgenden Angaben beziehen sich auf den am **22. September 2026** geprüften Stand des offiziellen pi-gen-Repositories. Für eigene Release-Builds solltest du zusätzlich immer einen konkreten Commit dokumentieren. ([github.com](https://github.com/RPi-Distro/pi-gen))

> **Projekt-Kontext (ros-pi-gen):** Dieses Repo ist ein pi-gen-Overlay —
> gepinnter arm64-Commit `74d08a3`, eigene Sub-Stages `05-docker-ansible`,
> `06-variant`, `07-accesspopup` (siehe
> [README](README.md#overlay-einbringen-beide-wege), Strategie in
> [TODO.md](TODO.md), Block 1). Abweichend vom Allgemeinteil unten: Der
> x86_64-Cross-Build braucht hier `qemu-user-static` statt
> `qemu-user-binfmt` und (Ubuntu ≤ 22.04) einen neuen Trixie-Keyring
> ([README](README.md#nativer-build-ohne-docker), „Voraussetzungen"). Das
> `-lite` im Deploy-Dateinamen kommt **automatisch** aus pi-gens
> `stage2/EXPORT_IMAGE` (`IMG_SUFFIX="-lite"`; ein Env-`IMG_SUFFIX` wird vom
> Stage überschrieben). Geplanter CI-Lauf:
> [GitHub-Image-Workflow.md](GitHub-Image-Workflow.md).

---

### **32 oder 64 Bit**

Der verwendete Branch beschreibt die **Zielarchitektur des erzeugten Images**, nicht die Architektur des Build-Rechners:

- `master` erzeugt 32-Bit-Images.
- `arm64` erzeugt 64-Bit-Images.

Ein x86-64-Rechner kann also ein ARM-Image bauen. Dafür ist bei einem emulierten Build QEMU erforderlich. Ein nativer Build auf passender ARM-Hardware ist meist einfacher und vermeidet diese Fehlerquelle. ([github.com](https://github.com/RPi-Distro/pi-gen))

32-Bit-Image:

```bash
git clone --branch master https://github.com/RPi-Distro/pi-gen.git
cd pi-gen
git checkout <pi-gen-commit>
```

64-Bit-Image:

```bash
git clone --branch arm64 https://github.com/RPi-Distro/pi-gen.git
cd pi-gen
git checkout <pi-gen-commit>
```

Der Commit muss zum gewünschten Branch gehören. Prüfe und dokumentiere den tatsächlichen Stand:

```bash
git status
git rev-parse HEAD
```

`git status` zeigt außerdem, ob lokale Änderungen vorhanden sind. Ein flacher Clone mit `--depth 1` ist für einen einmaligen Build möglich, aber für Entwicklung und Nachvollziehbarkeit weniger geeignet.

---

### **Zielhardware prüfen**

Ein Image ist nicht automatisch für jede Raspberry-Pi-Generation geeignet. Prüfe:

- welche Pi-Modelle der gewählte pi-gen-Branch unterstützt,
- ob Kernel, Bootloader und Firmware zur Hardware passen,
- ob 32- oder 64-Bit-Unterstützung erforderlich ist,
- ob das Image auf jeder relevanten Gerätegeneration bootet.

Teste ein Release-Image auf echter Zielhardware. Ein erfolgreicher Build beweist nur, dass der Build erfolgreich war. Das ist ein niedriger Maßstab, aber immerhin einer.

---

### **Voraussetzungen**

Die maßgebliche Paketliste steht in `depends` des ausgecheckten pi-gen-Commits. Der aktuelle offizielle Stand nennt unter anderem `qemu-user-binfmt`; auf Systemen mit dynamisch gelinkten QEMU-Binaries kann stattdessen `qemu-user-static` erforderlich sein. ([github.com](https://github.com/RPi-Distro/pi-gen))

Für einen Debian-basierten Host:

```bash
sudo apt update
sudo apt install $(cat depends)
```

Plane außerdem ein:

- ausreichend freien Speicherplatz,
- ein echtes Linux-Dateisystem,
- stabile Netzwerkverbindung,
- funktionierende APT-Quellen,
- einen Pfad ohne Leerzeichen.

`WORK_DIR` enthält umfangreiche Zwischenstände. Die APT-Quellen werden während des Builds tatsächlich verwendet; ohne Netzwerkzugriff oder erreichbare Paketquellen scheitert der Build typischerweise.

---

### **Native Builds und QEMU**

Ein nativer Build benötigt keine Emulation. Bauste du ARM-Software dagegen auf einem x86-64-System, müssen die ARM-Programme innerhalb des Build-Prozesses ausgeführt werden können.

Außerhalb von Docker müssen dazu `binfmt_misc` und die passenden QEMU-Interpreter funktionieren. Typische Fehler sehen so aus:

```text
Exec format error
```

oder:

```text
armhf: not supported on this machine/kernel
```

Prüfe beispielsweise:

```bash
ls /proc/sys/fs/binfmt_misc
```

Für 32-Bit-ARM sollte dort typischerweise `qemu-arm` auftauchen; für 64-Bit-ARM wird ein passender AArch64-Interpreter benötigt. Docker erleichtert die Einrichtung, beseitigt die Kernel- und Loop-Device-Anforderungen aber nicht vollständig. ([github.com](https://github.com/RPi-Distro/pi-gen))

---

### **Stages: der eigentliche Bauplan**

pi-gen verarbeitet Stage-Verzeichnisse und deren Unterverzeichnisse in einer definierten Reihenfolge:

```text
Stage 0 → Stage 1 → Stage 2 → Stage 3 → Stage 4 → Stage 5
 Basis      bootfähig    Lite       Desktop    Standard    Full
```

Überblick:

- **Stage 0** erzeugt ein minimales Debian-Dateisystem.
- **Stage 1** macht es bootfähig.
- **Stage 2** bildet die Grundlage für Raspberry Pi OS Lite.
- **Stage 3** ergänzt die grafische Oberfläche.
- **Stage 4** erzeugt das normale Desktop-Image.
- **Stage 5** ergänzt weitere Anwendungen.

Die Stages haben Abhängigkeiten. Du kannst sie überspringen, eigene Stages einfügen und mit `STAGE_LIST` eine alternative Reihenfolge festlegen. Beliebiges Umsortieren ist trotzdem keine gute Idee.

```bash
STAGE_LIST="stage0 stage1 stage2 mystage"
```

Die Anführungszeichen sind erforderlich. Relative und absolute Pfade sind möglich:

```bash
STAGE_LIST="stage0 stage1 stage2 /home/user/pi-stages/mystage"
```

Eine eigene Stage wird nicht automatisch verarbeitet. Sie muss über `STAGE_LIST` eingebunden oder in eine tatsächlich abgearbeitete Stage-Struktur integriert werden. ([github.com](https://github.com/RPi-Distro/pi-gen/blob/master/README.md))

---

### **Eigene Stage**

Beispiel:

```text
mystage/
├── 00-run.sh
├── 01-custom-files/
│   ├── 00-run.sh
│   └── files/
│       └── etc/myapp/config.ini
└── 02-custom-packages/
    ├── 00-packages
    └── 00-run-chroot.sh
```

Übliche Dateien:

- `00-run.sh` – Skript auf dem Build-System,
- `00-run-chroot.sh` – Skript innerhalb des Zielsystems,
- `00-packages` – zu installierende Pakete,
- `00-packages-nr` – Pakete ohne empfohlene Abhängigkeiten,
- `00-debconf` – Antworten für `debconf`,
- `00-patches/` – Patch-Dateien für `quilt`.

Das Patch-Verzeichnis heißt innerhalb der jeweiligen Unterstufe `00-patches`:

```text
01-system-tweaks/
└── 00-patches/
```

Ein Verzeichnis `04-patches/` wäre nur dann richtig, wenn es sich tatsächlich um die Unterstufe `04` handelt. Die Nummer bestimmt die Reihenfolge.

---

### **Konfiguration**

`config` ist ein Bash-Shellfragment:

```bash
IMG_NAME='mein-image'
RELEASE='trixie'
TARGET_HOSTNAME='raspberrypi'
ENABLE_SSH=1
```

Eine separate lokale Konfiguration ist für Secrets und persönliche Einstellungen besser:

```bash
cat > config.local <<'EOF'
IMG_NAME='mein-image'
RELEASE='trixie'
TARGET_HOSTNAME='pi-device'
ENABLE_SSH=1
EOF
```

Build mit dieser Datei:

```bash
./build.sh -c config.local
```

Wichtige Variablen sind unter anderem:

- `IMG_NAME` – Name des Images,
- `RELEASE` – Debian-Version,
- `TARGET_HOSTNAME` – Hostname,
- `WORK_DIR` – Arbeitsverzeichnis,
- `DEPLOY_DIR` – Zielverzeichnis,
- `DEPLOY_COMPRESSION` – Kompressionsformat,
- `STAGE_LIST` – Stage-Auswahl und Reihenfolge,
- `APT_PROXY` – optionaler APT-Proxy,
- `TEMP_REPO` – temporäres Zusatz-Repository,
- `ENABLE_CLOUD_INIT` – aktiviert die entsprechende pi-gen-Konfiguration,
- `SETFCAP` – steuert die Verarbeitung von Linux-Capabilities,
- `COMPRESSION_LEVEL` – Kompressionsstufe,
- `DISABLE_FIRST_BOOT_USER_RENAME` – steuert die First-Boot-Umbenennung.

Diese Liste ist keine vollständige Referenz. Maßgeblich sind README, `build.sh` und die Dateien des konkreten Commits. ([github.com](https://github.com/RPi-Distro/pi-gen/blob/master/README.md))

---

### **Docker-Build**

Docker kann den Build teilweise vom Host-System isolieren und ist auch auf nicht Debian-basierten Hosts nützlich:

```bash
./build-docker.sh
```

Falls der Benutzer keine Docker-Berechtigung besitzt, ist je nach Host-Konfiguration `sudo` erforderlich:

```bash
sudo ./build-docker.sh
```

Prüfe anschließend Eigentümer und Rechte der erzeugten Dateien. Ein pauschales `sudo` kann sonst root-eigene Dateien im Arbeitsverzeichnis hinterlassen.

Zusätzliche Docker-Optionen:

```bash
PIGEN_DOCKER_OPTS="--add-host foo:192.0.2.10" \
./build-docker.sh
```

Die Docker-Isolation ist nicht vollständig. Loop-Geräte, `binfmt_misc` und privilegierte Container bleiben Teil des Spiels. ([github.com](https://github.com/RPi-Distro/pi-gen/blob/master/build-docker.sh))

---

### **First Boot, Benutzer und SSH**

Das Verhalten hängt vom pi-gen-Stand, den gesetzten Variablen und den aktivierten First-Boot-Komponenten ab. Eine pauschale Aussage wie „dies ist der endgültige Benutzer“ wäre daher zu glatt.

Beispiel:

```bash
FIRST_USER_NAME='pi'
FIRST_USER_PASS='nicht-in-git-ablegen'
```

Ist `FIRST_USER_PASS` nicht gesetzt, bleibt das Konto im aktuellen pi-gen-Stand gesperrt. Wird `DISABLE_FIRST_BOOT_USER_RENAME` nicht aktiviert, kann der Benutzer beim ersten Start umbenannt werden. Das ist eine Sicherheitsfunktion gegen ausgelieferte Standardbenutzer. ([github.com](https://github.com/RPi-Distro/pi-gen/blob/master/README.md))

Wenn du die Umbenennung deaktivierst:

```bash
DISABLE_FIRST_BOOT_USER_RENAME=1
```

muss ein Passwort gesetzt sein. Ein identisches Standardpasswort für eine Geräteflotte bleibt trotzdem eine schlechte Idee.

SSH-Schlüssel:

```bash
ENABLE_SSH=1
PUBKEY_SSH_FIRST_USER='ssh-ed25519 AAAA... user@example'
PUBKEY_ONLY_SSH=1
```

`PUBKEY_SSH_FIRST_USER` schreibt den Wert in die `authorized_keys` des während des Builds verwendeten ersten Benutzers. Das aktiviert SSH nicht automatisch. `PUBKEY_ONLY_SSH=1` verlangt einen gültigen öffentlichen Schlüssel und deaktiviert Passwortauthentifizierung für SSH. ([github.com](https://github.com/RPi-Distro/pi-gen/blob/master/README.md))

Nach dem ersten Boot testen:

```bash
getent passwd
find /home -path '*/.ssh/authorized_keys' -ls
sshd -T | grep -E 'passwordauthentication|pubkeyauthentication'
```

Zusätzlich den tatsächlichen Login prüfen:

```bash
ssh -o PasswordAuthentication=no user@host
```

`sshd -T` ist nur aussagekräftig, wenn der SSH-Server installiert ist und die effektive Konfiguration geladen werden kann. Welche Netzwerkschnittstellen erreichbar sind, hängt außerdem von `ListenAddress`, Firewall und Netzwerkdesign ab – nicht allein von pi-gen.

---

### **Secrets und Geräteidentitäten**

Keine Passwörter, WLAN-PSKs, Tokens oder privaten Schlüssel in Git einchecken:

```bash
FIRST_USER_PASS='ein-eigenes-starkes-passwort'
```

Auch wenn das Passwort stark ist, liegt es damit in Konfigurationsdateien, Logs oder möglicherweise im Image.

Besser:

```bash
chmod 600 config.local
```

und `config.local` aus der Versionsverwaltung ausschließen. Für Geräteflotten eignen sich individuelle Zugangsdaten oder ein First-Boot-Provisionierungsprozess.

Prüfe außerdem, dass jedes Gerät eigene Werte erhält:

- SSH-Host-Keys,
- Hostname oder Inventarnummer,
- Benutzerpasswort,
- API-Tokens und Zertifikate,
- WLAN- und VPN-Konfiguration,
- Maschinenidentität.

Ein identischer öffentlicher SSH-Schlüssel ist nicht geheim. Der zugehörige private Schlüssel wird aber zum Generalschlüssel für alle Geräte.

---

### **WLAN**

```bash
WPA_COUNTRY='DE'
```

setzt die WLAN-Regulierungsdomäne und kann WLAN-Schnittstellen freischalten. Die Variable enthält keine Zugangsdaten.

Die konkrete WLAN-Konfiguration hängt vom verwendeten Raspberry-Pi-OS-/pi-gen-Stand und den aktivierten Netzwerkkomponenten ab, beispielsweise NetworkManager, ConnMan oder eine eigene First-Boot-Provisionierung. ([github.com](https://github.com/RPi-Distro/pi-gen/blob/master/README.md))

---

### **Builds bereinigen**

pi-gen verwendet Zwischenstände in `WORK_DIR`. Das beschleunigt Folgebuilds, kann aber dazu führen, dass Änderungen scheinbar ignoriert werden.

Nach Änderungen an einer bereits gebauten Stage:

```bash
sudo CLEAN=1 ./build.sh
```

Beim Docker-Build:

```bash
PRESERVE_CONTAINER=1 CONTINUE=1 CLEAN=1 \
./build-docker.sh
```

Falls Docker-Berechtigungen fehlen, ergänzt du `sudo`. Für verlässliche Tests sollte die betroffene Stage oder der Arbeitsstand gezielt bereinigt werden.

---

### **Wiederholbar ist nicht bit-identisch**

Für wiederholbare Builds solltest du mindestens dokumentieren:

1. pi-gen-Commit,
2. Branch,
3. `RELEASE`,
4. eigene Stage-Dateien,
5. Konfiguration,
6. Build-Host oder Container,
7. APT-Quellen,
8. Bootloader- und Firmware-Versionen.

Ein Paketname wie:

```text
python3
```

bezeichnet keine feste Version. APT installiert den zu diesem Zeitpunkt verfügbaren Paketstand. Für strengere Reproduzierbarkeit brauchst du kontrollierte Paketversionen, eingefrorene Repository-Snapshots, stabile Schlüssel und definierte Zeitstempel.

`SOURCE_DATE_EPOCH` kann bei Zeitstempeln helfen, ersetzt aber keine Kontrolle über Paketquellen und Build-Umgebung.

---

### **Image prüfen und verteilen**

Prüfsumme erzeugen:

```bash
sha256sum deploy/*.img.xz > deploy/SHA256SUMS
```

Bei der Verteilung solltest du Prüfsummen signieren.

Mindestens testen:

- Boot auf jeder relevanten Pi-Generation,
- Partitionen und Dateisysteme,
- First-Boot-Verhalten,
- Benutzer und SSH,
- Netzwerk,
- Dienste,
- Hostname und Geräteidentität,
- Neustart,
- Verhalten ohne Netzwerkverbindung.

Flashen kannst du beispielsweise mit Raspberry Pi Imager oder – bei passenden Images – `bmaptool`.

---

### **Wartung**

Ein Image ist eine Momentaufnahme. Ein reproduzierbarer Build ersetzt kein Update-Konzept.

Lege fest:

- ob Geräte per APT aktualisiert werden,
- ob ein Konfigurationsmanagement zum Einsatz kommt,
- wie Sicherheitsupdates getestet werden,
- wie oft Images neu gebaut werden,
- wie lange die gewählte Basis gepflegt wird,
- ob signierte Updates erforderlich sind.

Für professionelle Flotten gehören automatisierte Smoke-Tests, SBOMs und signierte Artefakte in die CI-Pipeline.

---

### **Alternativen**

- **Raspberry Pi Imager** – für einzelne Geräte.
- **Buildroot** – für kleine, stark kontrollierte Systeme.
- **Yocto** – für umfangreiche Embedded-Produktlinien.
- **pi-gen-micro** – separates, deutlich anders konzipiertes Werkzeug für minimale Systeme.

Bleibst du nahe an Raspberry Pi OS, ist pi-gen meist der pragmatischste Weg. Für ein vollständig eigenes Embedded-System sind Buildroot oder Yocto oft passender.

---

### **Fazit**

pi-gen eignet sich gut für automatisierte und wiederholbare Raspberry-Pi-OS-Images. Entscheidend sind:

- offiziellen Repository-Namen verwenden,
- `master` und `arm64` korrekt zur Zielarchitektur wählen,
- Branch und Commit dokumentieren,
- native und emulierte Builds unterscheiden,
- Zielhardware testen,
- eigene Stages ausdrücklich einbinden,
- Secrets aus Git und Images heraushalten,
- Geräteidentitäten beim ersten Start erzeugen,
- bei Änderungen mit `CLEAN=1` bauen,
- Images prüfen, hashen und signieren,
- Updates langfristig planen.

Probier’s selbst aus – aber nicht zuerst auf der einzigen SD-Karte, die noch funktioniert.

---

### **Glossar**

- **APT** – Paketverwaltungssystem von Debian.
- **`binfmt_misc`** – Linux-Funktion zum Starten von Binärdateien anderer Architekturen.
- **First Boot** – erste Inbetriebnahme eines Systems.
- **QEMU** – Emulator für andere Prozessorarchitekturen.
- **SBOM** – Software Bill of Materials, also eine Liste der enthaltenen Softwarekomponenten.
- **Stage** – einzelne pi-gen-Bauphase.
- **`SOURCE_DATE_EPOCH`** – Variable zur kontrollierten Behandlung von Zeitstempeln bei reproduzierbaren Builds.

---

### **Schlagworte**

`raspberry-pi` `raspberry-pi-os` `pi-gen` `debian` `linux` `image-builder` `docker` `qemu` `arm64` `armhf` `bash` `cloud-init` `embedded` `reproduzierbare-builds`

---

### **Versions- und Quellenhinweis**

Geprüft am **22. September 2026** gegen das offizielle Repository, die README sowie `build.sh` und `build-docker.sh`. Die Aussagen zu Sicherheitsmaßnahmen, Flottenidentitäten, Prüfsummen und Wartung sind technische Empfehlungen und keine vollständige Sicherheitszertifizierung. ([github.com](https://github.com/RPi-Distro/pi-gen))

### **Prüfvermerk (kurz)**

Verifiziert gegen den lokalen pi-gen-Clone (arm64, Commit `74d08a3`): Branch-Zweiteilung (`master`/`arm64`, README), `depends`-Paketliste inkl. `qemu-aarch64:qemu-user-binfmt` + README-Hinweis auf `qemu-user-static` bei dynamisch gelinkten Binaries, Stage-Übersicht (stage0–5 mit `EXPORT_IMAGE`/`IMG_SUFFIX` je Stage: `-lite` in stage2, `""` in stage4, `-full` in stage5), `STAGE_LIST`-Mechanik inkl. externer Pfade (build.sh:320, 330-331), Konfigvariablen (`APT_PROXY`, `TEMP_REPO`, `PUBKEY_SSH_FIRST_USER`/`PUBKEY_ONLY_SSH` in build.sh; `PUBKEY_*`-Anwendung in stage2/01-sys-tweaks/01-run.sh — authorized_keys + sshd_config-Switch, `ENABLE_SSH` aktiviert die Unit), `DISABLE_FIRST_BOOT_USER_RENAME`-Passwortkopplung (build.sh:292-298), `CLEAN`/`CONTINUE`/`PRESERVE_CONTAINER` (build.sh:335, build-docker.sh:56, 75).

**Korrigiert gegen die Ursprungsfassung dieses Artikels:** keine inhaltlichen Fehler gefunden; ergänzt wurde die Projekt-Anmerkung oben (Overlay-Kontext, qemu-user-static-Abweichung, automatisches `IMG_SUFFIX="-lite"` aus `stage2/EXPORT_IMAGE` — die `source`-Reihenfolge in build.sh überschreibt ein Env-IMG_SUFFIX).

Offen/unverifiziert: `SOURCE_DATE_EPOCH` (im pi-gen-Repo nicht dokumentiert — allgemeine Reproducible-Builds-Konvention), pi-gen-micro-Charakterisierung (nur aus der rpi-image-gen-Doku, nicht gegen das pi-gen-micro-Repo geprüft).
