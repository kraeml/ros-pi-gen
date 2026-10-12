# Projektanweisungen: ros-pi-gen

## Projektziel und Architektur

Dieses Repository baut Debian-Trixie-Images für Raspberry Pi 3, 4 und 5 (arm64). Der Build basiert auf dem als Git-Submodul gepinnten `pi-gen`; projektspezifische Stages und Varianten liegen unter `stage-custom/`. `headless` ist das derzeit freigegebene Angebot. Die Desktop-Variante ist getrennt und darf nicht als bereitgestellt oder freigegeben angenommen werden.

Das Root-`Makefile` ist der zentrale Einstiegspunkt. GitHub Actions und andere Runner sollen vorhandene Make-Targets und versionierte Tools aufrufen, statt Build- oder Publish-Logik in Workflow-YAML zu duplizieren. Technische Release-Gates und Veröffentlichungsregeln stehen in [`RELEASE-GATES.md`](RELEASE-GATES.md); bei Änderungen daran müssen diese Regeln ausdrücklich berücksichtigt werden.

## Relevante Verzeichnisse

- `stage-custom/`: pi-gen-Stages, Paketlisten, Konfiguration, Services und Dateien im Zielimage.
- `tools/`: Build-, Paketierungs-, Imager-Manifest-, Release- und S3-Test-Publisher-Tools.
- `tests/`: pytest-Tests für Stages, Image-Prüfungen, Paketierung und Releasewerkzeuge.
- `assets/`: projektweite Assets, darunter das Raspberry-Pi-Imager-Icon.
- `.github/workflows/`: CI- und Release-Runner-Adapter.
- `pi-gen/`: gepinntes Git-Submodul; nicht ungefragt aktualisieren oder dessen Änderungen in diesem Projekt verstecken.
- `deploy/`, `work/`, `.venv/`, `package/`: erzeugte Build-, Test-, Paket- und Umgebungsartefakte; vor Änderungen oder Löschungen deren Inhalt und Zweck prüfen.

## Arbeitsweise und Codekonventionen

- Vor Änderungen die betroffenen Dateien und benachbarten Tests lesen. Bestehende Architektur, Abhängigkeiten, Dateinamen, Formatierung und Fehlerbehandlung fortführen.
- Build-, Manifest- und Veröffentlichungslogik in versionierten Skripten bzw. Make-Targets halten. Workflow-Dateien sollen möglichst nur Checkout, Runner-Setup, Secrets-Injektion und Aufrufe dieser Targets enthalten.
- Python-Tools und Tests orientieren sich an den vorhandenen Modulen und pytest-Mustern. Shellskripte mit sicherem Fehlerverhalten (`set -euo pipefail`, wo passend) schreiben und ShellCheck-Konventionen beachten.
- Keine Kommentare hinzufügen, außer wenn ausdrücklich verlangt. Keine Secrets, Passwörter, privaten Schlüssel oder lokalen Zugangsdaten in Repository-Dateien oder Logs aufnehmen.
- Keine neue Abhängigkeit einführen, ohne zuerst deren Notwendigkeit und Verfügbarkeit im Projekt zu prüfen.
- Bei Änderungen an Paketnamen, Metadaten, Manifesten oder Schema-Pins die zugehörigen Validatoren und Tests mitändern. URLs, Geräte-Tags, Varianten oder Veröffentlichungsziele nicht erraten.

## Build und Tests

Die üblichen lokalen Befehle aus dem Repository-Root:

```sh
git submodule update --init
make venv
make lint
make setup VARIANT=headless
make build VARIANT=headless
make test
```

`make build` verwendet standardmäßig Docker und `RELEASE_BUILD=1`. Der Release-Build deaktiviert die temporäre `stage-custom/04-user-data`-Test-Stage und auditiert das erzeugte Image. `RELEASE_BUILD=0` ist ein lokaler Opt-in für den dokumentierten Test-Quickfix und darf nicht für veröffentlichungsbestimmte Images genutzt werden.

Für Imager-Paketierung muss `BASE_URL` explizit gesetzt werden, z. B.:

```sh
make package VARIANT=headless BASE_URL=http://127.0.0.1:8000/
```

Die konkrete URL muss vom Imager-Rechner erreichbar sein. Pakete validieren Manifestformat und -schema; Tests der Paketierung befinden sich in `tests/test_package_image.py`.

`make lint` führt Python-Kompilierungsprüfungen, ShellCheck und das im Makefile festgelegte pytest-Subset aus. Für die vollständige Test-Suite `make test` verwenden. Einen Image-Build oder Hardware-/Imager-Test nur ausführen, wenn Umgebung und Zielgerät dafür geeignet sind.

## Varianten und Image-Inhalte

- Varianten heißen exakt `headless` und `desktop`; Auswahl erfolgt über `VARIANT` bei `make setup`/`make build`.
- Das gepinnte `pi-gen`-Submodul und die Imager-Schema-/Gerätekatalog-Pins nicht automatisch aktualisieren. Pin-Änderungen müssen nachvollziehbar und mit Tests abgesichert sein.
- Keine Testzugänge, fest codierten Passwörter, Betreiber-Schlüssel oder temporären Quickfix-Inhalte in produktionsbestimmte Images aufnehmen.
- Pakete, Dienste und Konfigurationen gehören in die passende Stage und Variante. Bereits vorhandene Muster in `stage-custom/` verwenden.

## Sicherheit und Veröffentlichungen

- Keine destruktiven Aktionen, externen Uploads, Bucket-/Policy-Änderungen, Git-Tags, Pushes oder Releases ohne ausdrücklichen Auftrag und erforderliche Freigabe durchführen.
- S3-Testveröffentlichungen sind von Produktionsveröffentlichungen getrennt. Produktionsimages und Imager-Manifeste werden nach den aktuellen Regeln in `RELEASE-GATES.md` veröffentlicht.
- Vor Änderungen an Upload- oder Release-Abläufen die Freigabe-Gates in `RELEASE-GATES.md` lesen. Ein Test- oder Dry-Run-Schalter ersetzt keine notwendige Freigabe.
- Keine bestehenden veröffentlichten Objekte automatisch löschen oder Releases zurückziehen. Bei unklarem Teilfehler anhalten und Status melden.
- Vor Commit nur beabsichtigte Dateien stagen; nicht committen, sofern der Benutzer es nicht ausdrücklich verlangt.
- Commit-Nachrichten auf Deutsch und im Stil `Bereich: Kernaussage` verfassen.

## Verifikation nach Codeänderungen

Nach Implementierung die engsten passenden Tests ausführen und `make lint` laufen lassen, sofern die Änderung das Projekt betrifft. Für Workflow- oder Releaseänderungen auch die relevanten Release-Tests und Richtlinien in `RELEASE-GATES.md` prüfen. Ergebnisse und nicht ausgeführte Prüfungen kurz melden.
