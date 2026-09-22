# Raspberry Pi Imager 2.0: Installation, eigene Images und Schul-Roll-out

Raspberry Pi Imager 2.0 ersetzt das überladene Einzelfenster früherer Versionen durch einen schrittweisen Assistenten. Dazu kommen Cloud-init als Standardverfahren bei aktuellen kompatiblen Raspberry-Pi-OS-Images, ein dokumentierter Weg für eigene Image-Repositories und eine Vorbereitung für Raspberry Pi Connect.

Für ein einzelnes Bastelprojekt ist das bequem. Für eine Schule mit dreißig Geräten wird es interessant – aber nur, wenn du weißt, wo Imager aufhört und echte Geräteverwaltung anfängt.

Aktuelle Version zum Redaktionsstand **22. September 2026**: **Raspberry Pi Imager 2.0.11.1**, laut offiziellem GitHub-Repository als Latest Release markiert. Version 2.0 erschien am 24. November 2025. ([github.com](https://github.com/raspberrypi/rpi-imager))

---

### Warum die alte Oberfläche weichen musste

Imager konnte auch vorher schon Benutzerkonto, Hostname, WLAN, SSH und Zeitzone vorkonfigurieren. Nur wuchs die Konfigurationsmaske mit jeder Funktion weiter, bis sie mächtig, aber unübersichtlich war.

Version 2.0 nutzt stattdessen einen **Wizard (Assistent, der eine Aufgabe in mehrere Schritte aufteilt)**:

```text
Raspberry Pi auswählen
     │
     ▼
Betriebssystem auswählen
     │
     ▼
Zielmedium wählen
     │
     ▼
System konfigurieren
     │
     ▼
Schreiben und Verifikation
```

Jeder Schritt bekommt das ganze Fenster. Mehr Platz für Hinweise, Eingabeprüfungen und Warnungen. Dafür kannst du nicht mehr beliebig zwischen allen Optionen hin- und herspringen.

Version 2.0 verbessert dabei ausdrücklich auch die **Barrierefreiheit**: vollständige Tastaturbedienung, Beschriftungen für Screenreader und ein verbesserter Kontrast. Für Schulen mit Inklusionsauftrag ist das kein Nebenaspekt, sondern ein Grund, warum sich die Umstellung auf 2.0 auch pädagogisch lohnt. ([raspberrypi.com](https://www.raspberrypi.com/news/a-new-raspberry-pi-imager/))

Redaktionelle Faustregel, keine Herstellervorgabe: Bei fünf Geräten reicht die grafische Oberfläche. Ab etwa zehn Geräten lohnt sich der Blick auf CLI und Repository.

---

### Cloud-init: nur mit passendem Image

**Cloud-init (Werkzeug zur automatisierten Erstkonfiguration eines Linux-Systems)** übernimmt beim ersten Start Benutzerkonten, Hostname, SSH-Schlüssel, Netzwerkeinstellungen und Dienste.

Imager erzeugt Cloud-init-Dateien standardmäßig für **aktuelle Raspberry-Pi-OS-Images auf Debian-Trixie-Basis**. Bei älteren Raspberry-Pi-OS-Versionen, bei Drittanbieter-Betriebssystemen oder bei einem beliebigen lokalen `.img` gilt das nicht automatisch – dort hängt es davon ab, ob das Image die erforderliche Integration mitbringt. ([raspberrypi.com](https://www.raspberrypi.com/news/cloud-init-on-raspberry-pi-os/))

Cloud-init ist primär für die Erstkonfiguration vorgesehen – die praktisch relevante Abgrenzung zu Werkzeugen wie Ansible, die laufende Systeme dauerhaft verwalten. Einzelne Module können je nach Konfiguration aber auch bei späteren Starts erneut ausgeführt werden.

Damit ein Image kompatibel ist, braucht es mehrere Zutaten, nicht nur eine:

- Cloud-init muss die **NoCloud-Datenquelle (lokale Quelle für Cloud-init-Konfigurationsdateien)** auf der `bootfs`-Partition erkennen.
- Für WLAN und Netzwerk muss **Network Config Version 2** unterstützt werden, typischerweise über **Netplan** mit passendem Network Renderer.
- Das aktivierte Cloud-init-Modul **`cc_raspberry_pi`** macht Raspberry-Pi-eigene Konfigurationsoptionen erst nutzbar.
- Zusätzlich braucht die Distribution die passende Anpassung namens **`raspi-config-vendor`** – das ist die distributionsspezifische Integration, die `cc_raspberry_pi` mit den tatsächlichen Systemwerkzeugen verbindet. `cc_raspberry_pi` allein reicht nicht. ([raspberrypi.com](https://www.raspberrypi.com/news/how-to-add-your-own-images-to-imager/))

Wichtige Einschränkung: Kopierst du Cloud-init-Dateien manuell auf die Boot-Partition eines fertigen Images, funktioniert das nur, wenn alle diese Zutaten zusammenpassen. Nicht jedes Image ist dafür vorbereitet.

**Und was ist mit `systemd`?** Neben `cloudinit` und `cloudinit-rpi` kennt Imager auch den Wert `systemd` – das ältere, klassische `bootfs`/`firstrun.sh`-Verfahren, bei dem ein Shell-Skript beim ersten Start läuft. Für eigene, ältere Custom Images ist das oft die einzig realistische Option: Cloud-init ist eben nicht die einzige Konfigurationsmethode, die Imager unterstützt, nur die modernere. ([raspberrypi.com](https://www.raspberrypi.com/news/how-to-add-your-own-images-to-imager/))

---

### Eigene Images einbinden – `init_format` korrekt angeben

Ein lokales `.img` lässt sich in Imager 2.0 weiterhin über **Use Custom** direkt schreiben – dafür braucht es kein Repository. Ein Repository wird erst nötig, wenn Imager das Image **gezielt anbieten, nach Gerätetyp filtern und sichere Konfigurationsoptionen einblenden** soll. Wichtig zu wissen: Bei einem lokalen `.img` über Use Custom **ohne** Repository-JSON lässt Imager die OS-Customization (Hostname, Benutzer, WLAN, SSH) komplett aus – das ist kein Fehler, sondern die beabsichtigte Absicherung gegen potenziell gefährliche Customization-Mismatches. Wer Customization für eigene Images will, braucht daher das Repository-JSON.

**Zur Schreibweise von `init_format` – ein Stück Quellenkritik:** Die offizielle Anleitung im Raspberry-Pi-Blog ist an einer Stelle in sich widersprüchlich: Im Feldverzeichnis stehen die Werte **ohne** Bindestrich (`none`, `systemd`, `cloudinit`, `cloudinit-rpi`), weiter unten im selben Dokument tauchen in einer Tabelle dieselben Werte **mit** Bindestrich auf (`cloud-init`, `cloud-init-rpi`). Der Blog verweist jedoch selbst auf die formale Referenz des Repository-Formats: **`doc/schema-notes.md` im rpi-imager-Quellrepository** („Repository JSON V4"). Dort ist die Werte-Liste eindeutig – **ohne** Bindestrich, ergänzt um zwei weitere Fälle:

```text
none            # Customization bewusst deaktivieren
systemd         # Legacy: firstrun.sh auf bootfs
cloudinit       # Cloud-init (NoCloud), generische Optionen
cloudinit-rpi   # + Raspberry-Pi-Optionen via cc_raspberry_pi
rpi-preseed     # seit Imager 2.0.11: Images mit rpi-preseed-Paket
""              # leerer String = explizit deaktiviert
```

Die Bindestrich-Varianten im Blogartikel sind dessen Fehler – maßgeblich ist die Schema-Doku. (Quellen: [raspberrypi.com](https://www.raspberrypi.com/news/how-to-add-your-own-images-to-imager/), [github.com](https://github.com/raspberrypi/rpi-imager/blob/main/doc/schema-notes.md))

`rpi-preseed` (PR #1659, Release 2.0.11) ist ein weiterer First-Boot-Customization-Pfad neben cloud-init und systemd: Er richtet sich an Images, die das Paket `rpi-preseed` mitbringen; Imager schreibt die Antwortdatei, das Image wendet sie beim ersten Start an.

**Repository JSON – vollständigeres Grundgerüst:**

```json
{
  "os_list": [
    {
      "name": "Schul-OS 2026.09",
      "description": "Standardimage für Raum 204",
      "icon": "https://schulserver.example/icon.png",
      "url": "https://schulserver.example/schule-os-2026.09.1.img.xz",
      "release_date": "2026-09-22",
      "image_download_size": 4000000000,
      "image_download_sha256": "…",
      "extract_size": 8000000000,
      "extract_sha256": "…",
      "devices": ["pi5", "pi4"],
      "capabilities": ["rpi_connect", "usb_otg"],
      "init_format": "cloudinit"
    }
  ]
}
```

Neu gegenüber der vorherigen Fassung, alle Felder offiziell dokumentiert:

- **`image_download_sha256`** prüft die komprimierte Downloaddatei, **`extract_sha256`** zusätzlich das entpackte Image. Beide zusammen decken Übertragungsfehler auf zwei Ebenen ab.
- **`release_date`** dokumentiert das Veröffentlichungsdatum – wichtig für dein eigenes Versionsmanagement.
- **`devices`** grenzt ein, für welche Raspberry-Pi-Modelle das Image überhaupt angezeigt wird. Ohne dieses Feld bietet Imager das Image möglicherweise auf Geräten an, für die es nicht passt.
- **`icon`** wird ebenfalls unterstützt und dient nur der Darstellung im Assistenten.
- **`image_download_size`** und **`extract_size`** sind keine bloßen Metadaten. Imager nutzt sie für die Fortschrittsanzeige und – wichtiger für dich – zur Prüfung, ob auf dem Zielmedium überhaupt genug Platz ist, bevor das Schreiben beginnt. ([raspberrypi.com](https://www.raspberrypi.com/news/how-to-add-your-own-images-to-imager/))

Die Werte für `capabilities` sind offiziell dokumentiert: `rpi_connect` für die Connect-Vorkonfiguration, `usb_otg` für USB-Gadget-Funktionalität (**USB-OTG**, Verfahren, mit dem sich ein Raspberry Pi einem angeschlossenen Rechner als USB-Gerät präsentiert). `usb_otg` setzt voraus, dass sowohl Gerät als auch Image diese Funktion tatsächlich unterstützen.

`init_format` legt fest, welche Customization-Optionen der Assistent anbietet. `cloudinit` setzt voraus, dass das Image die Cloud-init-Integration mitbringt (siehe oben); `cloudinit-rpi` zusätzlich `cc_raspberry_pi` + `raspi-config-vendor`; `rpi-preseed` das Paket `rpi-preseed`. Beim Wert testen: gegen die Imager-Version, die du tatsächlich einsetzt, und in deinem eigenen Repository dokumentieren, gegen welche Version getestet wurde. Ein Wert, der nicht erkannt wird, führt nicht zu einer Fehlermeldung – die betroffene Option erscheint im Assistenten einfach nicht.

---

### Eigene Images bauen: `rpi-image-gen` und `pi-gen`

Zwei Werkzeuge werden gern verwechselt:

```text
pi-gen
  └─ erzeugt Raspberry Pi OS selbst
     (das Basis-Betriebssystem)

rpi-image-gen
  └─ baut angepasste, reproduzierbare Images
     auf Basis vorhandener Komponenten
```

`rpi-image-gen` ist **ein geeigneter, offiziell von Raspberry Pi bereitgestellter Weg** für angepasste Images – nicht automatisch die beste Lösung für jede Schule. Das Projekt befindet sich in aktiver Entwicklung. Die Projekt-Workflows nutzen teils QEMU, als unterstützte beziehungsweise bevorzugte Build-Umgebung gilt aber ein natives 64-Bit-Raspberry-Pi-OS beziehungsweise ein Debian-Bookworm- oder Trixie-System auf ARM64. ([github.com](https://github.com/raspberrypi/rpi-image-gen))

Für schutzbedürftige Geräte – etwa in einem Labor mit sensiblen Daten statt einem gewöhnlichen Klassenzimmer – bietet das Projekt zusätzliche Sicherheitsbausteine als Ausblick, nicht als Pflicht für die kleine Schule von nebenan: SBOM- und CVE-Berichte zur Software-Zusammensetzung, signierten Boot, verschlüsselte Dateisysteme und eine Integration mit `rpi-sb-provisioner` für die sichere Erstinbetriebnahme. ([github.com](https://github.com/raspberrypi/rpi-image-gen))

Für eine einzelne Schule ohne bestehende Build-Infrastruktur bleibt trotzdem oft der pragmatischere Einstieg: ein sorgfältig von Hand vorbereitetes Golden Image mit anschließender Cloud-init-Anpassung pro Gerät.

Ein eigener Detailartikel vertieft `rpi-image-gen` – Konfigurationsmodell (YAML, Layer, Traits), Hooks, Build-Host-Anforderungen und PMAP/SBOM: [Eigene-Raspberry-Pi-Images-rpi-image-gen.md](Eigene-Raspberry-Pi-Images-rpi-image-gen.md).

---

### Ein Schul-Image bereitstellen: Sicherheit und Versionierung

Für ein Schul-Repository gelten ein paar Grundregeln:

- kein gemeinsames Standardpasswort für alle Geräte,
- pro Gerät individuelle Zugangsdaten über Cloud-init,
- bei **802.1X (Authentifizierungsverfahren für Netzwerkzugriff)** ein gerätebezogenes Zertifikat statt eines geteilten Passworts.

WLAN-Zugangsdaten gehören auf keinen Fall in ein öffentlich erreichbares Repository JSON.

**Versionierung einführen**

```text
schule-os-2026.09.1
schule-os-2026.09.2
schule-os-2026.10.1
```

Zu jeder Version dokumentierst du Veröffentlichungsdatum (siehe `release_date`), Änderungen und beide Prüfsummen.

**Integrität ist nicht Authentizität**

SHA-256-Prüfsummen erkennen beschädigte Downloads und Übertragungsfehler. Sie beweisen nicht, wer das Image erstellt hat. Wer die Datei austauschen kann, kann meist auch die daneben liegende Prüfsumme austauschen.

Für Herkunftssicherheit brauchst du zusätzlich HTTPS für Repository und Image, Zugriffsschutz auf den Ablageort, möglichst eine Signatur mit getrennt verteiltem öffentlichem Schlüssel sowie eine dokumentierte Verantwortlichkeit, wer Images freigibt.

**Geräteinventar führen**

| Feld | Beispiel |
|---|---|
| Gerätename | pi-raum204-03 |
| Image-Version | schule-os-2026.09.1 |
| Standort | Raum 204 |
| Connect-Status | registriert |
| Letztes Update | Datum |

**Patch-Strategie, Rollback und verlorene Geräte**

Kläre vorab: Wer entscheidet über Updates, automatisch oder kontrolliert? Wie oft wird das Basis-Image neu gebaut? Ab wann gilt eine Version als veraltet? Halte zusätzlich ein funktionierendes Vorgänger-Image bereit, falls die neue Version Probleme macht, und plane für verlorene oder kompromittierte Geräte den Widerruf von Connect-Zugriff und Zugangsdaten sowie – je nach Hardware und Einsatzmodell mit zusätzlichem Verwaltungsaufwand verbunden – eine Verschlüsselung.

**Vor dem Roll-out testen:** WLAN, Proxy, Benutzeranmeldung, SSH, Connect, Updates, Drucker, Unterrichtssoftware, Zurücksetzen, Verhalten ohne Internetverbindung.

---

### Automatisierung und Kommandozeile

Für Linux gibt es die CLI-Funktion nicht automatisch in jeder Installation. Das separate Paket **`rpi-imager-cli`** stellt die Kommandozeilenvariante bereit – die grafische Installation über das AppImage bringt sie nicht zwangsläufig mit. Prüfe vor dem Einsatz, welches Paket deine Distribution anbietet. ([github.com](https://github.com/raspberrypi/rpi-imager/releases))

```bash
sudo rpi-imager --cli \
  schule-os-2026.09.1.img.xz /dev/sdX
```

Diese Reihenfolge (`--cli IMAGE DEVICE`) zeigt auch die offizielle `rpi-image-gen`-Dokumentation. ([github.com](https://github.com/raspberrypi/rpi-image-gen)) Prüfe trotzdem vorab mit `rpi-imager --help`, ob deine konkrete Version davon abweicht – der Parametersatz hat sich zwischen 2.0.x-Ständen bereits verändert.

Das Zielgerät (`/dev/sdX`) muss stimmen. Ein Tippfehler überschreibt hier ohne Rückfrage die falsche Platte. Kontrolliere vorher mit `lsblk`.

---

### Raspberry Pi Connect vorbereiten

**Raspberry Pi Connect (browserbasierter Fernzugriff auf Raspberry Pi OS)** lässt sich in Imager 2.0 vorkonfigurieren. Der Assistent hinterlegt einen Auth-Key, sodass sich das Gerät nach dem ersten Start selbst registriert.

- Jeder Pi benötigt einen **eigenen** Auth-Key.
- Persönliche Auth-Keys sind **sechs Stunden** gültig.
- Organisations-Keys gelten je nach Konfiguration **ein bis 90 Tage**. ([raspberrypi.com](https://www.raspberrypi.com/documentation/services/connect.html))
- Für eine Geräteflotte ist **Raspberry Pi Connect for Organisations** die sinnvollere Grundlage als persönliche Konten.

Connect ersetzt weder Patchmanagement noch Inventarisierung noch zentrale Richtlinienverwaltung.

```text
Remote Shell
  └─ funktioniert auch auf Lite-Images

Screen Sharing
  └─ benötigt Desktop-Image, Wayland
     und aktive grafische Sitzung
```

Für unbeaufsichtigte Desktop-Geräte heißt das in der Regel: **Desktop Autologin** aktivieren. User-Lingering hält nur die Shell erreichbar und ersetzt Autologin nicht.

---

### Schreiben und Verifikation sind zwei Schritte

Imager wartet beim Schreiben stärker auf Bestätigungen des Betriebssystems, dass Daten wirklich angekommen sind. Die anschließende Verifikation liest die Daten erneut und vergleicht sie mit dem Ausgangsimage.

Verifikation kann bestimmte Kapazitätsfälschungen erkennen – etwa Karten, die eine größere Kapazität vortäuschen, als sie besitzen. Sie garantiert aber keine dauerhafte Zuverlässigkeit und ersetzt keine Langzeittests im laufenden Betrieb.

---

### Installation auf den Plattformen

| Plattform | Weg |
|---|---|
| Windows / macOS | Installer von raspberrypi.com |
| Linux (grafisch) | AppImage von der offiziellen Seite |
| Linux (CLI) | Paket `rpi-imager-cli` |
| Linux (Distributionspaket) | `apt install rpi-imager` – Version prüfen |

`apt install rpi-imager` installiert die Version aus dem Repository deiner Distribution, die deutlich älter als 2.0 sein kann. Prüfe mit `rpi-imager --version`. Steht dort 1.x, fehlen Wizard und Cloud-init-Integration – dann führt der Weg über das offizielle AppImage. ([github.com](https://github.com/raspberrypi/rpi-imager/releases))

---

### Datenschutz

Zur Telemetrie von Imager liegt mir keine belastbare offizielle Angabe vor – ausdrücklich ungeprüft.

Ein eigenes Repository reduziert den Downloadverkehr für Kataloge und Images, hält den Datenverkehr aber nicht grundsätzlich „im Haus": Imager kann weiterhin externe Dienste kontaktieren, etwa bei aktivierter Connect-Vorkonfiguration.

---

### Fazit

Imager 2.0 ist ein deutlicher Fortschritt – Wizard, Barrierefreiheit, Cloud-init-Standard und ein dokumentiertes Repository-Format. Für eine Schule ist es ein guter Auslieferungsweg – mehr aber nicht. Geräteinventar, Patchstrategie, Rollback-Plan und Umgang mit verlorenen Geräten musst du daneben aufbauen.

Bau dir ein Testgerät, leg ein Repository JSON an und teste den kompletten Ablauf gegen deine konkrete Imager-Version, bevor du bestellst.

---

## Glossar

- **802.1X** – Authentifizierungsverfahren für Netzwerkzugriff.
- **Auth-Key** – Zeitlich begrenzter Schlüssel zur Registrierung bei Raspberry Pi Connect.
- **`capabilities`** – Feld im Content-Repository-JSON für zusätzliche unterstützte Funktionen, u. a. `rpi_connect`, `usb_otg`.
- **`cc_raspberry_pi`** – Cloud-init-Modul für Raspberry-Pi-spezifische Konfigurationsoptionen.
- **Cloud-init** – Werkzeug zur automatisierten Erstkonfiguration eines Linux-Systems.
- **`devices`** – Feld im Repository-JSON, das die passenden Raspberry-Pi-Modelle festlegt.
- **`extract_sha256`** – Prüfsumme des entpackten Images.
- **`image_download_sha256`** – Prüfsumme der komprimierten Downloaddatei.
- **NoCloud** – Lokale Datenquelle für Cloud-init-Konfigurationsdateien.
- **pi-gen** – Werkzeug zur Erzeugung von Raspberry Pi OS.
- **`raspi-config-vendor`** – Distributionsspezifische Integration, die Cloud-init mit Raspberry-Pi-Systemwerkzeugen verbindet.
- **Raspberry Pi Connect** – Browserbasierter Fernzugriff auf Raspberry Pi OS.
- **rpi-image-gen** – Werkzeug zum Bauen angepasster, reproduzierbarer Images.
- **`rpi-imager-cli`** – Separates Linux-Paket für die Kommandozeilenvariante von Imager.
- **`rpi-preseed`** – First-Boot-Customization-Pfad (seit Imager 2.0.11) für Images, die das gleichnamige Paket mitbringen.
- **`rpi-sb-provisioner`** – Werkzeug zur sicheren Erstinbetriebnahme von Geräten.
- **SHA-256** – Prüfsummenverfahren zur Erkennung von Übertragungsfehlern.
- **USB-OTG** – Verfahren, mit dem sich ein Raspberry Pi als USB-Gerät präsentiert.
- **Wizard** – Assistent, der eine Aufgabe in mehrere Schritte aufteilt.

---

## Prüfvermerk (kurz)

Verifiziert: Version 2.0.11.1, Release-Datum 2.0, Cloud-init-Standardverhalten, Barrierefreiheits-Neuerungen, `capabilities`/`devices`/`image_download_sha256`/`release_date`-Felder, `cc_raspberry_pi`, `raspi-config-vendor`, `rpi-imager-cli`-Paket, `rpi-image-gen`/`pi-gen`-Unterscheidung, Connect-Key-Laufzeiten, `init_format`-Werteliste (formale Referenz `doc/schema-notes.md` im rpi-imager-Repo: `none`/`systemd`/`cloudinit`/`cloudinit-rpi`/`rpi-preseed`/`""` ohne Bindestrich; die Bindestrich-Tabelle im Blogpost ist fehlerhaft), `rpi-preseed` ab 2.0.11.

Offen/ungeklärt: Imager-Telemetrie, exakter CLI-Parametersatz je Version.

Redaktionelle Einschätzung, keine Herstellervorgabe: alle Schul-Roll-out-Empfehlungen, Faustregeln zur Gerätezahl.

### Schlagworte

`raspberry-pi` `raspberry-pi-imager` `cloud-init` `raspberry-pi-connect` `rpi-image-gen` `pi-gen` `schul-image` `content-repository` `custom-images` `ssh` `netplan` `debian` `barrierefreiheit` `geräteverwaltung` `linux`
