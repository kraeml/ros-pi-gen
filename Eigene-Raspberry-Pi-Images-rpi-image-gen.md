# Eigene Raspberry-Pi-Images bauen: `rpi-image-gen` richtig einsetzen

Raspberry Pi OS ist für viele Projekte völlig ausreichend. SD-Karte beschreiben, Benutzer anlegen, Netzwerk konfigurieren – fertig.

Bei einem Kiosk-Terminal, einem Industriecontroller oder einem Embedded-Gerät brauchst du oft mehr Kontrolle: ein definiertes System, eigene Dienste, passende Partitionen, reproduzierbare Builds und möglichst wenig Ballast.

Dafür gibt es `rpi-image-gen`.

> **Geprüfter Stand: 22. September 2026.** Die Angaben beziehen sich auf `v2.8.0`, veröffentlicht am 13. August 2026. Das Projekt entwickelt sich weiter – „aktuell“ ist hier also ein Begriff mit Verfallsdatum. ([github.com](https://github.com/raspberrypi/rpi-image-gen/releases))

---

### Was `rpi-image-gen` erzeugt

`rpi-image-gen` baut angepasste Software-Images für Raspberry-Pi-Geräte. Je nach Konfiguration entstehen unter anderem:

- bootfähige Disk-Images,
- Dateisystem-Tarballs für Container oder andere Zielsysteme,
- SBOM-Dateien,
- Image-Description-Dateien,
- Provisioning Maps,
- komprimierte Deployment-Artefakte,
- Prüfsummen und weitere Build-Ergebnisse.

Ein `.img` ist also nicht zwingend das einzige Resultat. Die fertigen Artefakte werden in einem versionsbezogenen Deployment-Verzeichnis gesammelt. ([raspberrypi.github.io](https://raspberrypi.github.io/rpi-image-gen/layer/deploy-base.html))

```text
YAML-Konfiguration
       │
       ├── Zielgerät
       ├── Gerätevariante
       ├── Image-Layout
       ├── Layer und Traits
       ├── Pakete und Hooks
       └── Provisioning
              │
              ▼
      Image, Tarball, SBOM,
      Image Description und
      weitere Artefakte
```

**Layer (wiederverwendbare Konfigurationsschicht)** bündeln Pakete, Dateien, Abhängigkeiten und Skripte. So lassen sich gemeinsame Bestandteile für mehrere Geräte wiederverwenden. ([raspberrypi.github.io](https://raspberrypi.github.io/rpi-image-gen/layer/index.html))

---

### `rpi-image-gen` oder `pi-gen`?

`pi-gen` ist das Werkzeug, mit dem die offiziellen Raspberry-Pi-OS-Images gebaut werden. Es eignet sich besonders, wenn du Raspberry Pi OS mit zusätzlichen Stages erweitern möchtest. ([github.com](https://github.com/raspberrypi/rpi-image-gen))

`rpi-image-gen` setzt stärker auf deklarative Konfiguration, Layer, Image-Layouts und getrennte Geräteklassen.

| Werkzeug | Schwerpunkt |
|---|---|
| `rpi-image-gen` | Layer, YAML, eigene Image-Layouts |
| `pi-gen` | Raspberry-Pi-OS-nahe Builds mit Stages |
| Buildroot | Kleine, stark integrierte Embedded-Systeme |
| Yocto | Eigene Linux-Distributionen und Produktplattformen |

Für ein Kiosk-Projekt kann Yocto überdimensioniert sein. Für ein langfristig gepflegtes Industrieprodukt kann es trotzdem die bessere Wahl darstellen. Der Werkzeugkasten muss zum Problem passen – nicht umgekehrt.

---

### Das Konfigurationsmodell

YAML ist das bevorzugte Konfigurationsformat. Die wichtigsten Bereiche sind:

- `device`: Zielhardware,
- `image`: Image-Aufbau und Partitionierung,
- `layer`: zusätzliche Layer,
- `packages`: zusätzliche Debian-Pakete,
- `trait`: Hardware-, Boot- und Systemfähigkeiten,
- `include`: Einbindung weiterer Konfigurationen.

Ein **Trait (beschreibbare Fähigkeit oder Eigenschaft)** kann beispielsweise festhalten, dass ein Gerät Bluetooth, bestimmte Bootmechanismen oder spezielle Hardware unterstützt. Geräteklasse und Gerätevariante werden getrennt modelliert: `pi5` bezeichnet etwa die Klasse, während eine Variante zusätzliche Unterschiede wie `lite` beschreiben kann. ([raspberrypi.github.io](https://raspberrypi.github.io/rpi-image-gen/))

Ein schematisches Beispiel:

```yaml
include:
  - base.yaml
  - device/pi5.yaml

device:
  class: pi5
  storage_type: sd
  layer: rpi5

image:
  layer: image-rpios
  compression: zstd
  boot_part_size: 200%
  root_part_size: 300%

layer:
  application: my-kiosk

packages:
  - curl
  - vim

trait:
  hw:bluetooth: true
```

Das Beispiel zeigt die Struktur, ist aber keine garantiert sofort baubereite Konfiguration. Die verfügbaren Layer, Variablen und Traits hängen vom verwendeten Commit ab.

`device.layer` bestimmt das Geräte-Layer, `image.layer` das Image-Layer. Unter `layer` lassen sich zusätzliche Layer einbinden; die Schlüssel wie `application` sind frei wählbar, die Werte müssen auf vorhandene Layer zeigen. Je nach Ziel kommen beispielsweise `image-rpios`, `image-rota` oder andere Image-Layer infrage. ([github.com](https://github.com/raspberrypi/rpi-image-gen/blob/master/docs/config/index.adoc))

---

### Includes und Variablenauflösung

Konfigurationen können weitere YAML-Dateien einbinden:

```yaml
include:
  - device/pi5.yaml
  - image/kiosk.yaml
```

Die Dateien werden in Reihenfolge verarbeitet. Später geladene Werte können frühere Werte überschreiben; die einbindende Datei hat Vorrang vor ihren Includes.

Zusätzlich können Werte über die Kommandozeile gesetzt werden:

```bash
rpi-image-gen build \
  -c config.yaml \
  -- IGconf_device_class=pi5 \
     IGconf_image_compression=xz
```

Layer deklarieren ihre Variablen und können Validierungsregeln sowie Überschreibungsstrategien festlegen. Dadurch weiß das Build-System, welche Werte zulässig sind und ob eine Variable beim ersten, letzten oder erzwungenen Setzen gewinnt. ([github.com](https://github.com/raspberrypi/rpi-image-gen/blob/master/docs/config/index.adoc))

Bei Listen ist Vorsicht angebracht: Werden beispielsweise `packages` in mehreren Include-Dateien definiert, werden Einträge nicht automatisch wie in einer klassischen Liste angehängt. Die Zusammenführung kann positionsbezogen erfolgen. Für vorhersehbare Ergebnisse sollte eine gemeinsame Paketliste möglichst nur an einer Stelle definiert werden. ([github.com](https://github.com/raspberrypi/rpi-image-gen/blob/master/docs/config/index.adoc))

---

### Installation und erster Build

Der dokumentierte Einstieg:

```bash
git clone https://github.com/raspberrypi/rpi-image-gen.git
cd rpi-image-gen

sudo ./install_deps.sh

./rpi-image-gen build \
    -c ./config/trixie-minbase.yaml
```

Das Beispiel erzeugt ein Image im Arbeitsverzeichnis:

```text
work/image-deb13-arm64-min/deb13-arm64-min.img
```

Verwendet werden unter anderem:

- `mmdebstrap` für das Ziel-Dateisystem,
- `genimage` für Disk-Images,
- YAML für Konfigurationen,
- Build-Hooks für eigene Aktionen. ([github.com](https://github.com/raspberrypi/rpi-image-gen))

Achtung bei Bestandskonfigurationen: **Mit v2.8.0 wurde die INI-Unterstützung ersatzlos entfernt** (Release-Notes, Abschnitt „Breakages": „Dropped INI config support … anyone still using .ini build configs must migrate to YAML"). YAML ist damit das einzige Konfigurationsformat – wer noch `.ini`-Build-Konfigurationen hat, muss sie vor dem Upgrade auf v2.8.0 nach YAML migrieren. ([github.com](https://github.com/raspberrypi/rpi-image-gen/releases))

---

### Der Build-Host

Der offiziell unterstützte native Pfad ist:

- Raspberry Pi OS 64 Bit,
- Debian Bookworm ARM64,
- Debian Trixie ARM64.

Container und nicht ARM64-basierte Hosts können über QEMU funktionieren, sind aber nicht der formal unterstützte Standardweg. Der Build erzeugt unter anderem Chroots und Mount-Namespaces; in Containern können dafür zusätzliche Rechte wie `CAP_SYS_ADMIN` erforderlich sein. ([github.com](https://github.com/raspberrypi/rpi-image-gen))

Für reproduzierbare Ergebnisse solltest du zusätzlich dokumentieren:

- Host-Betriebssystem,
- Git-Commit von `rpi-image-gen`,
- verwendete Paketquellen,
- Layer-Versionen,
- Container- oder QEMU-Version,
- Build-Logs.

---

### Image-Layer und Partitionierung

`image-base` stellt gemeinsame Grundlagen bereit. Ein tatsächlich bootfähiges Layout entsteht aber erst durch ein passendes nachgelagertes Image-Layer, etwa für Raspberry Pi OS, A/B-Systeme oder OTA-nahe Verfahren. ([raspberrypi.github.io](https://raspberrypi.github.io/rpi-image-gen/layer/image-base.html))

Ein Image besteht typischerweise aus:

```text
Boot-Partition
Root-Dateisystem
Datenpartition
optional: redundante Systempartitionen
```

Die Standardgröße einer Partition entspricht häufig nur dem tatsächlich erzeugten Dateisystem. Für beschreibbare Partitionen bleibt dann kaum oder gar kein freier Platz. Größen sollten deshalb ausdrücklich geplant werden. ([raspberrypi.github.io](https://raspberrypi.github.io/rpi-image-gen/layer/image-base.html))

Ein Image kann zwar booten und trotzdem für den Produktbetrieb ungeeignet sein. Wenn nach dem ersten Update kein Platz mehr für Pakete und Logs vorhanden ist, war die Partitionierung zu optimistisch.

---

### Dateisystem-Tarballs

Nicht jedes Ziel braucht ein vollständiges Disk-Image. Ein Dateisystem-Tarball kann sinnvoll sein für:

- Container,
- eigene Provisionierungsabläufe,
- vorbereitete Root-Dateisysteme,
- Tests,
- Systeme, deren Partitionierung ein anderes Werkzeug übernimmt.

Damit trennt sich die Erstellung des Dateisystems von der späteren Gestaltung des Speichermediums. Die Deployment-Schicht kann sowohl Disk-Images als auch Tarballs und weitere Artefakte ablegen. ([raspberrypi.github.io](https://raspberrypi.github.io/rpi-image-gen/layer/deploy-base.html))

---

### Kiosk-System mit Wayland und Chromium

Das Beispiel `webkiosk` zeigt einen typischen Einsatzfall: Das Gerät startet direkt in eine Browser-Anwendung im Vollbild.

**Wayland (Protokoll für moderne Linux-Grafikausgabe)** übernimmt die Kommunikation zwischen Anwendung und Compositor. **Cage (minimaler Wayland-Compositor)** ist auf einzelne Vollbildanwendungen zugeschnitten.

Für ein Kiosk-System brauchst du typischerweise:

- Chromium,
- Wayland,
- Cage,
- eine systemd-Unit,
- Start- und Konfigurationsdateien.

**systemd (Dienst- und Systemverwaltung unter Linux)** startet den Browser und kann ihn bei Abstürzen neu starten.

Die verfügbaren Layer und Variablen solltest du mit folgenden Befehlen prüfen:

```bash
./rpi-image-gen layer --list
./rpi-image-gen layer --describe webkiosk
```

---

### Hooks und Build-Phasen

Ein **Hook (Skript an einer definierten Stelle des Build-Ablaufs)** kann Dateien kopieren, Benutzer anlegen, Dienste aktivieren oder Konfigurationen erzeugen.

Welche Hook-Namen zulässig sind, hängt von Build-Phase und Layer ab. Je nach Projektstand gibt es Hooks für Dateisystemaufbau, Image-Erstellung, SBOM-Erzeugung und Deployment. Die Namen sollten deshalb nicht blind aus einem alten Beispiel übernommen werden. ([raspberrypi.github.io](https://raspberrypi.github.io/rpi-image-gen/layer/index.html))

Eigene Hooks sollten:

- deterministisch,
- nachvollziehbar,
- idempotent,
- frei von zufälligen Zeitstempeln sein.

**Idempotent** bedeutet: Mehrmaliges Ausführen führt zum gleichen Ergebnis wie einmaliges Ausführen.

Editor-Backups wie `customize01~` gehören nicht in ein Verzeichnis, in dem der Hook-Runner Skripte sucht. Sonst wird aus der Sicherungsdatei plötzlich ein Build-Schritt. Linux ist geduldig, aber nicht hellsichtig.

---

### Provisioning und Image Description

Für bestimmte Raspberry-Pi-Provisionierungsabläufe erzeugt `rpi-image-gen` zusätzlich eine **Image Description**. Sie beschreibt unter anderem:

- Partitionstabelle,
- Image-Dateien,
- Dateisystemtypen,
- Größen,
- Metadaten,
- Provisioning-Informationen.

Eine **Provisioning Map (PMAP)** beschreibt, wie das Image auf dem Zielgerät eingerichtet werden soll – beispielsweise welche Partitionen verschlüsselt werden oder welche Sicherheitsattribute gelten.

Diese Informationen werden in eine JSON-Datei wie `image.json` eingebunden. Für Raspberry-Pi-Provisionierungswerkzeuge ist eine PMAP je nach Ablauf erforderlich. ([raspberrypi.github.io](https://raspberrypi.github.io/rpi-image-gen/layer/image-base.html))

Die Trennung ist sinnvoll:

```text
Image Description
 ├── Layout: Was enthält das Image?
 └── PMAP:   Wie wird es auf dem Gerät eingerichtet?
```

Damit kann ein externes Werkzeug die eigentliche Provisionierung übernehmen, ohne den kompletten Buildprozess zu kennen.

---

### A/B-Systeme, OTA und `image-rota`

Ein **A/B-System (zwei bootfähige Systembereiche)** hält zwei Systemversionen vor. Während System A läuft, wird System B aktualisiert. Nach erfolgreicher Prüfung kann das Gerät von B starten.

`image-rota` stellt hierfür ein konkretes Image-Layout bereit. Das ist mehr als ein allgemeiner Hinweis auf „OTA-Fähigkeit“, aber noch kein vollständiger Updatebetrieb. ([raspberrypi.github.io](https://raspberrypi.github.io/rpi-image-gen/layer/index.html))

**OTA (Over-the-Air)** umfasst zusätzlich:

- Download,
- Authentifizierung,
- Signaturprüfung,
- Rollback,
- Statusrückmeldung,
- Geräteverwaltung.

`rpi-image-gen` erzeugt die passenden Artefakte und Layouts. Die Infrastruktur für den eigentlichen Flottenbetrieb bleibt projektspezifisch.

---

### SBOM und Sicherheit

Eine **SBOM (Software Bill of Materials – maschinenlesbare Liste der enthaltenen Software)** dokumentiert, welche Pakete und Komponenten im Build enthalten sind.

Sie hilft bei:

- CVE-Prüfungen,
- Compliance,
- Produktdokumentation,
- Wartung,
- Sicherheitsinventaren.

Zusätzlich solltest du Sicherheitsfragen separat planen:

- keine festen Passwörter,
- keine privaten Schlüssel im Repository,
- gerätespezifische SSH-Host-Schlüssel,
- signierte Artefakte,
- Secure Boot, falls von Hardware und Bootkette unterstützt,
- geschützte CI-Secrets,
- definierte Rollback-Strategie.

Die Provisionierungsdokumentation beschreibt außerdem Integrationen für signierten Boot und verschlüsselte Dateisysteme. ([github.com](https://github.com/raspberrypi/rpi-image-gen))

---

### Reproduzierbare Builds

Für möglichst reproduzierbare Builds solltest du mindestens festlegen:

- Git-Commit von `rpi-image-gen`,
- Debian- und Raspberry-Pi-Paketquellen,
- Paket-Snapshots oder eigenen Paket-Cache,
- Layer-Versionen,
- Build-Host,
- Build-Container,
- `SOURCE_DATE_EPOCH`,
- Konfigurationsdateien,
- SBOM und Logs.

`SOURCE_DATE_EPOCH` vereinheitlicht Zeitstempel in Build-Artefakten. Vollständig bit-identische Ergebnisse sind trotzdem nicht garantiert, wenn sich Paketquellen, Firmware oder externe Dateien ändern.

---

### CI und Hardwaretests

Das Repository enthält ein Test-Harness und nutzt CI-Builds. Native ARM64- und QEMU-Umgebungen können dabei unterschiedliche Prüfziele abdecken. ([github.com](https://github.com/raspberrypi/rpi-image-gen))

Für dein eigenes Projekt empfiehlt sich:

1. Konfiguration und Layer prüfen,
2. Image in CI bauen,
3. Partitionen kontrollieren,
4. SBOM erzeugen,
5. Boot mit QEMU testen,
6. auf jeder unterstützten Raspberry-Pi-Klasse booten,
7. Netzwerk, Dienste und Updatepfad prüfen.

QEMU ersetzt keinen echten Hardwaretest. GPIO, WLAN, Bluetooth, Kamera, Firmware und Speichergeräte verhalten sich dort nur bedingt realistisch.

---

### Image auf eine SD-Karte schreiben

Das Image lässt sich mit Raspberry Pi Imager über **Use Custom** schreiben.

Alternativ:

```bash
sudo rpi-imager --cli \
    ./work/image-deb13-arm64-min/deb13-arm64-min.img \
    /dev/mmcblk0
```

Vorher unbedingt prüfen:

```bash
lsblk
```

`/dev/mmcblk0` ist nur ein Beispiel. Je nach Rechner kann die Karte auch als `/dev/sdb` erscheinen. Ein falsches Zielgerät überschreibt vorhandene Daten. Die verfügbaren Optionen können sich außerdem zwischen Imager-Versionen ändern. ([github.com](https://github.com/raspberrypi/rpi-image-gen))

---

### Alternativen

- [`rpi-image-gen`](https://github.com/raspberrypi/rpi-image-gen) – Layer und YAML für angepasste Raspberry-Pi-Images
- [`pi-gen`](https://github.com/RPi-Distro/pi-gen) – Raspberry-Pi-OS-nahe Builds
- [Buildroot](https://buildroot.org/) – kompakte Embedded-Systeme
- [Yocto Project](https://www.yoctoproject.org/) – eigene Linux-Distributionen
- [Raspberry Pi Imager](https://www.raspberrypi.com/software/) – schreibt fertige Images

---

### Fazit

`rpi-image-gen` ist mehr als ein Werkzeug zum Erzeugen einer `.img`-Datei. Es verbindet:

- YAML-Konfiguration,
- Geräteklassen und Varianten,
- Traits,
- Layer,
- Image-Layouts,
- Dateisystem-Tarballs,
- SBOM,
- Provisioning Maps,
- Image-Description-Dateien,
- CI und Deployment-Artefakte.

Für ein Kiosk-Projekt reicht ein schlankes Image mit passendem Geräte- und Image-Layer. Für ein Produkt brauchst du zusätzlich Paket-Snapshots, Signaturen, Geheimnisverwaltung, Hardwaretests und einen belastbaren Updateprozess.

Starte mit:

```bash
git clone https://github.com/raspberrypi/rpi-image-gen.git
cd rpi-image-gen

sudo ./install_deps.sh
./rpi-image-gen layer --list
```

Dann wählst du einen passenden Geräte-Layer, ein geeignetes Image-Layout und baust zunächst ein möglichst kleines System. Der Rest kommt später. Meistens zusammen mit drei weiteren YAML-Dateien und einer systemd-Unit, die angeblich nur „kurz“ angepasst werden sollte.

---

### Schlagworte

`raspberry-pi` `rpi-image-gen` `embedded-linux` `debian` `yaml` `layers` `traits` `kiosk` `wayland` `systemd` `sbom` `provisioning` `ota` `buildroot` `yocto`

---

### Glossar

- **A/B-System:** Zwei bootfähige Systembereiche für robuste Updates.
- **Build-Host:** Rechner, auf dem das Image erzeugt wird.
- **Hook:** Skript an einer definierten Stelle des Build-Ablaufs.
- **Idempotent:** Mehrmaliges Ausführen erzeugt dasselbe Ergebnis wie einmaliges Ausführen.
- **Image Description:** JSON-Beschreibung von Layout und Provisionierungsinformationen.
- **Layer:** Wiederverwendbare Konfigurationsschicht.
- **OTA:** Aktualisierung eines Geräts über das Netzwerk.
- **Provisioning Map:** Beschreibung, wie ein Image auf dem Zielgerät eingerichtet wird.
- **SBOM:** Maschinenlesbare Liste der enthaltenen Software.
- **Trait:** Beschreibbare Hardware-, Boot- oder Systemfähigkeit.
- **Wayland:** Protokoll für moderne Linux-Grafikausgabe.
- **YAML:** Textformat für strukturierte Konfigurationen.

## Prüfvermerk (kurz)

Verifiziert gegen Primärquellen (Release-Notes v2.8.0, README.adoc, `docs/config/index.adoc`, `docs/execution/index.adoc`, `docs/provisioning/index.adoc`, Layer-Baum im Repository, Layer-Referenz auf raspberrypi.github.io): Version v2.8.0 (13.08.2026, Latest Release), YAML-Konfigurationsmodell (Includes in Reihenfolge, positionaler Listen-Merge mit Override-Warnung, `IGconf_`-Sektionen, `trait:` als Sondersektion ohne `IGconf_`-Übersetzung), Quick-Start samt Ausgabepfad `work/image-deb13-arm64-min/deb13-arm64-min.img`, Build-Hosts (nativ RPi OS 64/Bookworm/Trixie arm64; Container/QEMU nicht formal unterstützt, `CAP_SYS_ADMIN`-Anforderung), CLI-Overrides über `-- IGconf_…=…`, `layer --list`/`--describe`, webkiosk-Beispiel (Wayland/Cage/Chromium, A/B), image-base → image-rpios/image-rota, Tarballs und versioniertes Deploy-Verzeichnis, IDP/PMAP/`image.json`/`rpi-sb-provisioner`, SBOM, `test/`-Harness mit CI.

**Korrigiert gegen die Ursprungsfassung dieses Artikels:** Die Aussage, INI-Konfigurationen würden in der geprüften Version weiterhin unterstützt, war falsch – v2.8.0 hat die INI-Unterstützung entfernt („Breakages" in den Release-Notes).

Offen/nicht belegbar: `SOURCE_DATE_EPOCH` wird in der rpi-image-gen-Dokumentation nicht erwähnt – es ist eine allgemeine Konvention reproduzierbarer Builds, hier ohne projektseitigen Beleg übernommen.

Redaktionelle Einschätzung, keine Herstellervorgabe: Werkzeugwahl-Tabelle (pi-gen/Buildroot/Yocto), Partitionierungs- und CI-Empfehlungen, Kiosk-Bewertung.
