# Roboter-OS für Raspberry Pi

Roboter-OS ist ein Debian-Trixie-System für Raspberry Pi 3, 4 und 5 (arm64). Das aktuelle Imager-Angebot ist **Headless** (ohne grafische Desktop-Oberfläche). Docker, Docker Compose, Ansible, OpenSSH und NetworkManager sind enthalten.

## Installation mit Raspberry Pi Imager

Verwende Raspberry Pi Imager **2.0.6 oder neuer**. Der Repository-Import wurde mit Version 2.0.11.1 getestet. Das aktuelle Produktionsimage ist `2026.10.2`.

1. Öffne Raspberry Pi Imager und wähle Raspberry Pi 3, 4 oder 5.
2. Öffne die Betriebssystem-Auswahl und füge ein eigenes OS-Repository hinzu. Trage diese URL ein:

   ```text
   https://github.com/kraeml/ros-pi-gen/releases/latest/download/headless-os-list.json
   ```

3. Wähle **Roboter-OS 2026.10.2 (Headless)**.
4. Wähle die SD-Karte. Der Schreibvorgang löscht alle bisherigen Daten auf ihr.
5. Im Imager-Wizard kannst du Hostname, Benutzername und Passwort festlegen sowie WLAN und SSH konfigurieren. Diese Einstellungen sind pro Gerät vorzunehmen. Verwende kein gemeinsames Standardpasswort.
6. Starte das Schreiben und warte, bis Imager die Verifikation abgeschlossen hat. Wirf die Karte danach sicher aus.
7. Stecke die Karte in den Pi und schalte ihn ein. Beim ersten Start werden die Imager-Einstellungen angewendet.

Eine lokale Image-Datei über **Use Custom** einzuspielen bietet für dieses Image nicht denselben Imager-Anpassungsablauf. Verwende das Repository oben, wenn du Hostname, Benutzer, WLAN oder SSH beim Schreiben konfigurieren möchtest.

## Beim ersten Start: WLAN und Zugriff

Der Pi verbindet sich mit dem WLAN, das du im Imager-Wizard eingerichtet hast. Bei aktivierter SSH-Option meldest du dich mit dem dort festgelegten Benutzernamen und Passwort beziehungsweise SSH-Schlüssel an. Verwende den Hostnamen oder die IP-Adresse des Pi, zum Beispiel:

```bash
ssh <benutzername>@<hostname>.local
```

Wenn kein bekanntes WLAN erreichbar ist, startet der temporäre AccessPoint-Fallback:

- SSID: `<hostname>-AP` (ohne passenden Hostnamen: `Roboter-AP`)
- Passwort: `Pi-WLAN-Setup-2026`
- Einrichtungsseite: `http://192.168.50.5:8052`

Verbinde Handy oder Laptop mit diesem AccessPoint, öffne die Einrichtungsseite und trage das WLAN manuell ein. Der AccessPoint stellt selbst keinen Internetzugang bereit. Nach erfolgreicher Verbindung zum WLAN wird er abgeschaltet. Weitere Schritte und Fehlerhilfe stehen in der [WLAN-Anleitung](WLAN-Anleitung.md).

## Was im Image enthalten ist

- Debian Trixie, 64-Bit, für Raspberry Pi 3/4/5
- Docker CE und Docker Compose
- Ansible
- OpenSSH-Server und NetworkManager
- AccessPopup zur WLAN-Einrichtung über einen temporären AccessPoint

Das veröffentlichte Imager-Angebot ist derzeit Headless. ROS 2 und eine grafische Desktop-Oberfläche sind nicht Bestandteil dieses Angebots.

## Pakete und Dienste hinzufügen

Wenn ein Paket oder Dienst dauerhaft auf allen Geräten enthalten sein soll, wird es im Image ergänzt und mit einer neuen Image-Version verteilt. Die Projektdefinitionen dafür liegen in `stage-custom/`. Änderungen direkt auf einem laufenden Pi betreffen nur dieses Gerät und gehen beim erneuten Schreiben des Images verloren.

### APT-Pakete

Allgemeine Pakete stehen zeilenweise in `stage-custom/05-docker-ansible/02-packages`. Pakete nur für die Headless-Variante gehören in `stage-custom/06-variant-headless/00-packages`. Trage dort die Debian-Paketnamen ein, zum Beispiel:

```text
jq
```

### Dateien, Konfiguration und systemd-Dienste

Zusätzliche Dateien kommen in den `files/`-Ordner der passenden Stage. Das nummerierte Skript derselben Stage installiert sie im Image und kann Konfigurationen einrichten oder Dienste aktivieren. Ein Beispiel für dieses Muster ist `stage-custom/07-accesspopup/01-run.sh`.

Ein neuer systemd-Dienst benötigt typischerweise eine Unit-Datei unter `files/`, einen Installationsschritt im Stage-Skript und die Aktivierung für den nächsten Start. Während des Image-Builds wird ein Dienst nicht als laufender Pi gestartet. Zugangsdaten, WLAN-Passwörter und private SSH-Schlüssel gehören nicht in Stage-Dateien oder öffentliche Repositories.

### Docker und Ansible

Docker und Docker Compose eignen sich, um Anwendungen als Containerdienste zu betreiben. Ansible ist ebenfalls enthalten. Im Projekt wurde Ansible mit einem lokalen Playbook im Build-Chroot für Fakten, APT-Pakete und Dateioperationen erprobt. Ein fertiges Ansible-Inventar oder allgemeines Playbook zur Fernverwaltung der Pis wird nicht mitgeliefert.

Für wiederholbare Änderungen am Image dienen `stage-custom` und ein neuer Image-Build. Für Laufzeitverwaltung müssen Betreiber ihre Compose-Dateien, Ansible-Inventare und Playbooks selbst pflegen. Technische Hinweise zum belegten Ansible-Test stehen in [Ansible im Build-Prozess](Ansible-im-Build.md).

## Updates

Ein neues Roboter-OS-Release wird im Raspberry Pi Imager über dasselbe Repository angeboten. Um ein Gerät auf ein neues Image umzustellen, schreibe die neue Version auf die SD-Karte; sichere vorher alle benötigten Daten. Individuell im Imager eingetragene Zugangsdaten und WLAN-Einstellungen beim erneuten Schreiben wieder konfigurieren.

Paketänderungen, die im Projekt in `stage-custom` aufgenommen wurden, kommen mit einer neu gebauten und veröffentlichten Image-Version auf die Geräte. Ein automatisches Over-the-Air-Update oder eine zentrale Fernverwaltung ist nicht Teil dieses Projekts. Laufende Debian-Pakete können technisch per APT aktualisiert werden; eigene Änderungen daran werden dadurch aber nicht automatisch in ein später neu geschriebenes Image übernommen.

## Für Betreiber und Mitwirkende

Der Build verwendet standardmäßig Docker. Im Repository-Root:

```bash
git submodule update --init
make venv
make setup VARIANT=headless
make build VARIANT=headless
make test
```

Das Image und Build-Logs liegen unter `deploy/`. `RELEASE_BUILD=1` ist Standard; dabei wird die temporäre Test-Seed-Stage deaktiviert und das Image vor dem Paketieren auditiert. Produktionsveröffentlichungen und ihre Freigabegates sind in [AGENTS.md](AGENTS.md) festgelegt.

Weitere technische Dokumente:

- [AccessPopup-Betreiberhinweise](AccessPopup.md)
- [Tests und Abnahme](tests/README.md)
- [Ansible im Build-Prozess](Ansible-im-Build.md)
- [Historischer GitHub-Image-Workflow-Entwurf](GitHub-Image-Workflow.md) — nicht maßgeblich; aktuelle Release-Regeln stehen in `AGENTS.md`.
