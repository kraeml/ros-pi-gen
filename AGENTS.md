# Agenten-Anweisung: Veröffentlichung von ros-pi-gen-Images

## Ziel und Umfang

Das fertige Image soll über den Raspberry Pi Imager mit einem eigenen Repository-Manifest auffindbar und herunterladbar sein. Maßgebliche Verteilung ist S3-kompatibler Objektspeicher; GitHub Releases sind ebenso Teil des Veröffentlichungswegs.

Build, Tests, Paketierung und S3-Upload müssen über Make-Targets und versionierte Skripte lokal ausführbar und unabhängig von GitHub sein. GitHub Actions ist ein Runner-Adapter, Ziel der Build-Logik und auch einer Publish-Logik. Dieselbe Kette soll später auf Codeberg, GitLab oder einem selbst betriebenen lokalen Runner laufen können. Zugangsdaten werden jeweils als Runner-Secrets oder lokale AWS-CLI-Profile bereitgestellt und **nie** ins Repository geschrieben.

Erste vollständige Veröffentlichungskette: Image bauen und testen, Imager-Manifest samt Prüfsummen paketieren, anschließend Image und Manifest per HTTPS erreichbar auf S3 veröffentlichen. Lokaler HTTP-Test und OMV/LAN-Test sind vorgelagerte Prüfschritte. Änderungen an der GitHub-Automatisierung erfolgen erst nach den vorgesehenen Gates. Jedes Freigabe-Gate bekommt ein eignes git flow feature und nach Freigabe kann dieses geschlossen werden.

## Reihenfolge und Freigabe-Gates

1. Lokaler HTTP-Test auf der Developer-Maschine.
2. OMV-S3-Test im lokalen Heim- bzw. Klassenzimmernetz.
3. Hetzner-S3-Veröffentlichung für WAN-Zugriff.
4. Portabler CI-Runner-Adapter; zunächst GitHub Actions, später gegebenenfalls Codeberg, GitLab oder lokaler Runner.

Nach jeder Etappe Ergebnis melden und auf Freigabe warten:

- Gate 1: lokaler Imager-Test, vor OMV-Bucket-Anlage oder Upload.
- Gate 2: OMV-Test, vor Hetzner-Bucket-Anlage oder Upload.
- Gate 3: Hetzner-Veröffentlichung, vor Anlage oder Aktivierung des GitHub-Workflows.
- Gate 4: vor jedem Push oder Tag, der einen echten CI-Build oder Upload auslösen kann.
- Auch Bucket-Erstellung und Änderungen an öffentlichem Zugriff benötigen vorherige ausdrückliche Freigabe.

## S3-Profile und Ziele

AWS CLI v2 ist installiert. Vor S3-Aktionen Profilkonfiguration prüfen, ohne Zugangsschlüssel auszugeben oder zu protokollieren:

- OMV-Profil: `s3-intern`; Endpoint `https://s3-intern.kraeml-bayern.de`. konfigurierte Region `eu-central-1`;
- Hetzner-Profil: `hetzner-prod`; Endpoint `https://hel1.your-objectstorage.com`; konfigurierte Region `hel1`. Die Profilwerte sind maßgeblich; keine Region aus anderen Hetzner-Regionen übernehmen.
- Bucketname auf beiden unabhängigen S3-Diensten: `ros-pi-gen-images`. Beide Buckets existieren noch nicht. Die Namen müssen nur beim jeweiligen Anbieter eindeutig sein.
- Objektpräfix in beiden Buckets: `ros-pi-gen/`. Manifest: `ros-pi-gen/imager/os-list.json`; Releases: `ros-pi-gen/releases/<version>/<Image-Dateiname>`.

Vor Erstellung jeweils Anbieter, Endpoint, Region, Berechtigungen und Bucketname verifizieren. Bucket nicht ohne Gate anlegen. Bestehende Profile nicht überschreiben oder Zugangsdaten ändern. Bei einer Schule mit eigener OMV-Installation ist das Schulprofil separat einzurichten; `s3-intern` und dessen Zugangsdaten sind nicht übertragbar.

Öffentliche anonyme Lesezugriffe auf Manifest und Image sind nötig, damit Raspberry Pi Imager sie herunterladen kann. Vorhandene HTTPS-/Bucket-Konfiguration prüfen. Keine Bucket-Policy, ACL oder OMV-Einstellung ohne ausdrückliche Freigabe ändern. Falls öffentlicher Zugriff fehlt oder die öffentliche Objekt-URL nicht bekannt ist: anhalten, Befund und erforderliche Änderung nennen und Freigabe abwarten.

## Klassenzimmer-OMV einrichten

Für eine Schule mit eigenem OpenMediaVault und S3-kompatiblem Dienst gilt derselbe Ablauf, aber mit schulspezifischen Endpunkt-, Regions- und Zugangsdaten. Keine Zugangsdaten oder bestehenden Policies übernehmen:

1. Im OMV-S3-Dienst prüfen, ob der Bucket `ros-pi-gen-images` bereits existiert; andernfalls Bucket-Erstellung mit der OMV-Administration abstimmen.
2. Den vom konkreten S3-Dienst vorgegebenen HTTP/HTTPS-Endpoint und die Signaturregion ermitteln. Beides ist installationsspezifisch und nicht aus der LAN-Erreichbarkeit ableitbar.
3. AWS CLI v2 auf einem berechtigten Veröffentlichungsrechner verwenden. Ein dediziertes lokales Profil mit dem schuleigenen Endpoint, der bestätigten Region und separaten Zugangsdaten einrichten. Schreibrechte auf den Bucket beziehungsweise das Projektpräfix beschränken; Schüler benötigen keine Schreibzugänge.
4. Mit der OMV-Administration anonymes Lesen per HTTP/HTTPS für Manifest und Images beziehungsweise das Projektpräfix einrichten. Keine Bucket-Policy, ACL oder OMV-Einstellung ohne ausdrückliche Freigabe ändern.
5. Vom Klassenzimmernetz aus Manifest und Image abrufen, Prüfsumme kontrollieren und den Raspberry Pi Imager mit der Manifest-URL testen.
6. Schulspezifischen Endpoint, Profilnamen, Bucket, bestätigte Region und Zugriffsvoraussetzungen lokal dokumentieren; keine Secrets committen oder mit anderen Schulen teilen.

`ros-pi-gen-images` ist nur innerhalb des jeweiligen S3-Dienstes eindeutig zu halten; OMV und Hetzner können denselben Namen unabhängig voneinander verwenden. Wenn der Klassenzimmer-OMV-Server außerhalb des LAN nicht erreichbar ist, ist das erwartetes Verhalten. Die OMV-Quelle dient der Verteilung im eigenen Netz; Hetzner ist der WAN-Verteilweg.

## Versionierung und Image-Paket

Anzeigename: `Roboter-OS <YYYY.MM.PATCH> (Headless)` oder `(Desktop)` entsprechend `VARIANT`.

- `YYYY.MM` folgt dem Veröffentlichungsmonat, `PATCH` beginnt bei `1` und wird pro Veröffentlichung fortgezählt.
- Version wird bei der Veröffentlichung manuell angegeben, etwa `scripts/publish-s3.sh hetzner 2026.09.1`; kein automatischer Git-Tag-Import, solange dies nicht separat beschlossen ist.
- Vor Generierung des Manifests das Raspberry-Pi-Imager-Repository-JSON-Schema verifizieren. Die vorhandene Workflow-Planung beschreibt V4 `os_list` als `imager-repository.json`; Dateiname, Schema und Imager-Kompatibilität im ersten echten Test verbindlich festlegen. Keine erfundenen Felder wie `version` hinzufügen.
- Der tatsächliche Build-Artefaktname ist datumspräfixiert (`image_<Datum>-raspberrypi-trixie-custom-lite.img.xz`). Das Manifest muss exakt auf den paketierten und hochgeladenen Dateinamen zeigen. `VARIANT` wählt Headless oder Desktop; die Unterscheidung muss zuverlässig im Manifestnamen sichtbar sein.
- Paketierung muss das Image eindeutig auswählen und Abbruch bei null oder mehreren passenden Build-Artefakten auslösen, statt stillschweigend das falsche Image zu verwenden.
- SHA-256 für komprimiertes Download-Image und erforderliche entpackte Image-Prüfsumme aus dem echten Build-Artefakt erzeugen. Größen und URLs ebenfalls daraus ableiten.
- `init_format` primär `cloudinit-rpi`; falls dies auf echter Hardware nicht funktioniert, kontrolliert auf `cloudinit` wechseln. Entscheidung im JSON-Erzeugungsskript dokumentieren.
- Keine `.bmap` erzeugen, solange kein konkreter Bedarf beauftragt wurde.
- Zum Testen soll auch ein docker getriebenes `rpi-imager-cli` herangezogen werden. Docker deshalb, da OS unabhängig und eine parallel Installation zu rpi-imager nicht möglich ist.

## Etappe 1: lokaler HTTP-Test

Nur auf der Developer-Maschine testen; `127.0.0.1` ist ausschließlich von genau dieser Maschine erreichbar und kein LAN-Link.

- HTTP-Server aus einem Verzeichnis starten, das Manifest und Image enthält, z. B. `python3 -m http.server 8000` im Paketverzeichnis.
- Manifest-URL für diesen Test: `http://127.0.0.1:8000/os-list.json`; Image-URL darin muss ebenfalls lokal auflösbar sein.
- Raspberry Pi Imager CLI auf derselben Maschine mit dieser Quelle testen. `curl` allein belegt nicht, dass der Imager Manifest und Image erfolgreich lädt.
- JSON mit `python3 -m json.tool` validieren und SHA-256 des bereitgestellten Images mit dem Manifest vergleichen.
- Rollback: Server mit Strg+C stoppen; keine dauerhaften Änderungen.

→ Gate 1.

## Etappe 2: OMV/LAN-S3

Ziel: Schülergeräte im Heim- Klassenzimmernetz können das Image auch ohne Internet herunterladen. Bucket und öffentliche Lesbarkeit sind derzeit nicht eingerichtet.

- Profil `s3-intern` nur verwenden, nachdem Endpoint, Signaturregion und Zugriff erfolgreich geprüft wurden. Die derzeitige Profilkonfiguration ist nicht als korrekt/funktionsfähig bestätigt.
- Erst nach Freigabe Bucket `ros-pi-gen-images` auf OMV anlegen und unter dem Präfix `ros-pi-gen/` veröffentlichen.
- Provider- und Regionswerte aus dem Profil/OMV beziehen; keine Werte raten und keine lokale Profilkorrektur ohne Auftrag durchführen.
- Image hochladen und Download/Prüfsumme prüfen, bevor das stabile Manifest aktualisiert wird.
- JSON-URL, öffentliche HTTPS-Erreichbarkeit aus dem Klassenzimmernetz und Imager-Test prüfen.
- Rollback: stabiles Manifest auf die zuvor veröffentlichte Version zurücksetzen. Vorherige Release-Objekte nicht automatisch löschen.

→ Gate 2.

## Etappe 3: Hetzner/WAN-S3

Ziel: öffentliche Verteilung über das Internet. Bucket `ros-pi-gen-images` ist neu; keine Objekte in anderen Buckets wie `kraeml-bayern` verwenden oder verändern.

- Profil `hetzner-prod`, Endpoint `https://hel1.your-objectstorage.com`, Region `hel1`.
- Bucket-Erstellung und notwendige Public-Read-Konfiguration erst nach ausdrücklicher Freigabe. Zuvor prüfen, ob die verwendeten Credentials Bucket-Erstellung erlauben; bestehende Policies nicht ersetzen.
- Nur `ros-pi-gen/*` beschreiben. Keine Objekte löschen.
- Image hochladen und öffentlich per HTTPS samt Prüfsumme verifizieren; das stabile Manifest erst danach aktualisieren.
- JSON- und Image-URLs außerhalb des eigenen Netzes prüfen und den Imager-Test durchführen.
- Rollback: Manifest auf vorherige Version zurücksetzen. Ein fehlgeschlagener Lauf kann ein nicht referenziertes Release-Objekt hinterlassen; solche Objekte nicht automatisch löschen. Gleichzeitige oder wiederholte Veröffentlichungen derselben Version verhindern oder sicher abbrechen.

→ Gate 3.

## Etappe 4: portabler CI-Runner

Erste Integration ist GitHub Actions auf `ubuntu-latest`; Build-/Test-/Paketierungs-/Uploadlogik bleibt jedoch in Make-Targets und lokalen Skripten, damit kein GitHub-spezifischer Pfad nötig ist.

- Ergänze `make package` für lokales und CI-identisches Erzeugen von Manifest und Prüfsummen.
- Ergänze `scripts/publish-s3.sh <ziel> <version>` für OMV und Hetzner. Zielkonfiguration über vorhandene AWS-CLI-Profile lokal und Secrets/Umgebungsvariablen im CI bereitstellen. Keine Credentials in Skriptargumenten, Logs oder Repositorydateien schreiben.
- Der erste Workflow-Runner-Adapter ist GitHub Actions und veröffentlicht nur nach Hetzner; der OMV-Endpunkt ist LAN-only und wird nicht aus dem GitHub-Runner angesprochen. Diese Plattformwahl legt den Build- oder Publish-Ablauf nicht fest: dieselben versionierten Make-Targets und Skripte müssen auch mit Codeberg, GitLab oder einem lokalen Runner nutzbar sein.
- Workflow ruft vorhandene Make-Targets und Skripte auf, mindestens: Submodule initialisieren, Abhängigkeiten für Lint/Test bereitstellen, Lint, Setup, Build, Test, Package, Hetzner-Publish.
- CI muss die vorhandenen Voraussetzungen erfüllen: pi-gen-Submodul am gepinnten Commit, Docker und arm64/binfmt, ShellCheck, Testabhängigkeiten sowie ausreichender Speicherplatz. Runner-Disk-Cleanup und tatsächlichen Speicherbedarf beim ersten Lauf verifizieren.
- Hetzner-Secrets im GitHub-Repository manuell bereitstellen: `HETZNER_ACCESS_KEY_ID`, `HETZNER_SECRET_ACCESS_KEY`. Entsprechende Secret-Referenzen dürfen im Workflow stehen; Secrets selbst werden nicht angelegt oder ausgelesen.
- Derselbe portable Ablauf muss später auf Codeberg, GitLab und einem lokalen Runner verwendbar sein. Plattform-spezifisch bleiben nur Trigger, Secret-Injektion und Runner-Konfiguration.
- GitHub Releases sind neben dem S3-Hetzner Veröffentlichungsziel und ebenso Ziel für den Imager-Download. Maßgeblich sind S3-Manifest und S3-Image.

Kontrolle: Build, Tests und Paketierung erfolgreich; Image-Upload und Prüfsummenprüfung vor Manifest-Update; anschließend öffentliches Manifest und Image erreichbar, JSON korrekt und Imager-Test erfolgreich. Test-Trigger dürfen kein Produktionsmanifest aktualisieren. Testversionen beziehungsweise separater Testpfad müssen vor Workflow-Lauf festgelegt sein.

→ Gate 4 gilt vor jedem Push/Tag, der den CI-Lauf oder einen echten Upload auslöst.

## Durchgehende Regeln

- Bei unklaren Endpoints, Regionen, Bucket-Berechtigungen, JSON-Schema oder Varianten anhalten und nachfragen; keine Werte raten.
- Image zuerst hochladen und verifizieren, Manifest zuletzt aktualisieren.
- Alte Release-Objekte nicht automatisch löschen.
- Veröffentlichungsskripte lokal und im Workflow identisch ausführbar halten.
- Prüfsummen belegen Integrität, nicht Herkunft. Signaturen (Sigstore/GPG) sind nicht Teil dieser Etappen.
- Vor jedem Push/Tag mit echtem CI- oder Upload-Effekt explizite Freigabe einholen.
- Arbeiten mit git flow features
