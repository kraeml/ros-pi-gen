# Agenten-Anweisung: Veröffentlichung von ros-pi-gen-Images (überarbeitet)

Diese Fassung trennt die aktuell verbindlichen Regeln vom dokumentierten Verlauf der Gates 1 bis 3. Der GitHub-only-Pfad ist ein vorübergehender Workaround für S3-Probleme; die Zielarchitektur bleibt ein Dual-Publish mit gleichrangigen GitHub- und S3-Quellen.

---

## 1. Grundsätze

- **Zielarchitektur:** GitHub Releases und Hetzner-S3 sind gleichrangige Produktionsquellen. Beide enthalten dieselbe freigegebene Imageversion und Prüfsummen, jedoch jeweils eigene Manifeste und stabile Imager-Einstiege. Der Imager oder Betreiber wählt die Quelle; es gibt keinen automatischen Fallback zwischen Quellen.
- **Vorübergehender GitHub-only-Workaround:** Wegen der S3-Probleme veröffentlicht der aktuelle Produktionsworkflow nur auf GitHub. Das ist eine befristete Ausnahme, keine Änderung der Zielarchitektur. Der vorhandene S3-Produktionspublisher bleibt als Wiederherstellungspfad erhalten; Produktionsveröffentlichungen nach S3 sind bis zur ausdrücklichen Reaktivierungsfreigabe gesperrt.
- **Stabile Imager-URLs im aktuellen Workaround:**
  - GitHub: `https://github.com/kraeml/ros-pi-gen/releases/latest/download/headless-os-list.json`
  - GitHub Desktop-Manifest zusätzlich nach Bereitstellung von Desktop.
- **Stabile Imager-URLs nach Wiederherstellung des Dual-Publish:**
  - GitHub Headless: `https://github.com/kraeml/ros-pi-gen/releases/latest/download/headless-os-list.json`
  - Hetzner-S3 Headless: `https://hel1.your-objectstorage.com/ros-pi-gen-images/ros-pi-gen/imager/headless/s3/os-list.json`
  - Desktop erhält je Quelle einen eigenen stabilen variantenspezifischen Manifestpfad, sobald bereitgestellt.
- **Wiederherstellung von S3-Produktion:** Erst nach Fehleranalyse und bestätigter Behebung, erfolgreichem freigegebenem S3-Testupload inklusive anonymem Abruf, Prüfsummenvergleich und echtem Imager-Import, erfolgreichem Read-only-Preflight auf den Produktionsversionspfad sowie separater ausdrücklicher Freigabe darf der Produktionspfad reaktiviert werden. Dafür sind Workflow, Make-Targets und Preflight konsistent umzustellen. Die Freigabe des S3-Testuploads allein erlaubt keine Produktion.
- **Portabel bauen.** Build, Tests und Paketierung laufen über Make-Targets und versionierte Skripte, lokal und ohne GitHub. GitHub Actions ist nur Runner und Release-Adapter. Trigger, Secrets, Runner-Setup und Release-Adapter sind plattformabhängig. Der Rest muss auch auf Codeberg, GitLab und lokalen Runnern laufen.
- **Keine Secrets im Repository.**
- **Jedes Freigabe-Gate bekommt ein eigenes git-flow-Feature**, das nach der Freigabe geschlossen werden kann.
- **Nichts mit echter Wirkung ohne ausdrückliche Freigabe:** keine Bucket-Erstellung, keine Änderung öffentlicher Zugriffe, keine Pushes oder Tags, die CI oder Uploads auslösen.
- **Bei Unklarheit anhalten und nachfragen.** Das gilt für Endpoint, Region, Bucket, Policy, Schema, URL und Variante. Keine Werte raten.

## 2. Gates

Nach jeder Etappe: Befund und Ergebnis melden, dann auf die ausdrückliche Freigabe warten.

| Gate | Inhalt | Freigabe nötig vor |
|---|---|---|
| 1 | Lokaler HTTP-/Imager-Test | OMV-Bucket-Anlage oder Upload |
| 2 | OMV/LAN-Test (nur Headless, Desktop zurückgestellt) | Hetzner-Bucket-Anlage oder Upload |
| 3 | Hetzner/WAN-Test (Headless; Desktop zurückgestellt) | Anlage oder Aktivierung des GitHub-Workflows |
| 4 | Runner-Adapter und Produktionsrelease | jedem Push oder Tag, der einen echten Build oder Upload auslösen kann |

Bucket-Erstellung und Änderungen am öffentlichen Zugriff brauchen jeweils eine eigene Freigabe. Die bisherigen Freigaben gelten nur für die MinIO-Installation und das Präfix `ros-pi-gen-test/*`. Für andere Anbieter, Präfixe oder Policies gelten sie nicht.

Gate 3 ist mit Headless abgenommen; Desktop bleibt zurückgestellt. Das ist der tatsächlich geprüfte Umfang des abgeschlossenen WAN-Tests, nicht die Freigabe oder Bereitstellung von Desktop. Desktop benötigt einen eigenen Build, Test und eine ausdrückliche Freigabe, bevor es veröffentlicht wird.

## 3. S3-Profile und Zugriff

**Profile (AWS CLI v2).** Vor jeder S3-Aktion die Profilwerte prüfen. Zugangsschlüssel werden dabei weder ausgegeben noch protokolliert.

| | OMV/MinIO | Hetzner |
|---|---|---|
| Profil | `s3-intern-admin` | `hetzner-prod` |
| Endpoint | `https://s3-intern.kraeml-bayern.de` | `https://hel1.your-objectstorage.com` |
| Region | `eu-central-1` | `hel1` |
| Öffentliche Objekt-URL | `https://s3-intern.kraeml-bayern.de/ros-pi-gen-images/<key>` | `https://hel1.your-objectstorage.com/ros-pi-gen-images/<key>` |

Beide Dienste verwenden Path-Style-URLs. Der Bucket heißt bei beiden `ros-pi-gen-images`, die Buckets sind unabhängig voneinander. Die Profilwerte sind maßgeblich, Regionen anderer Hetzner-Standorte werden nicht übernommen.

Das ältere Profil `s3-intern` gehört nur zu `vagrant-boxes` und darf für ros-pi-gen nicht verwendet werden. `s3-intern-admin` ist privilegiert; OMV-Publisher und Gate-2-Aufrufe müssen strikt auf `ros-pi-gen-test/` begrenzt bleiben. Gate-3-Aufrufe auf Hetzner bleiben ebenfalls auf den Testpräfix beschränkt. Der separate S3-Produktionspfad ist bis zur ausdrücklich freigegebenen Wiederherstellung gesperrt.

**Pfade im Testpräfix:**
- stabiles Manifest: `ros-pi-gen-test/imager/<variant>/s3/os-list.json`
- archivierte Kopie: `ros-pi-gen-test/releases/<version>/<variant>-os-list.json` (`<version>` enthält das Suffix `-test`)

**Vor jedem Testupload:**
1. Anbieter, Endpoint, Region und Berechtigungen prüfen.
2. Prüfen, ob die Zielversion unter `ros-pi-gen-test/` schon Objekte enthält. Bei Treffern sicher abbrechen.
3. Anonymes Lesen per HTTPS muss möglich sein. Wenn nicht, anhalten und den Befund melden.

**Regeln beim Schreiben:**
- Nichts außerhalb von `ros-pi-gen-test/` verändern oder löschen.
- Keine bestehende Policy oder ACL überschreiben.
- Nach einem Teilfehler die Version nicht wiederverwenden. Nach Prüfung und Entscheidung die nächste PATCH-Version nehmen.
- Die Existenzprüfung ist keine atomare Sperre. Parallele Test-Publishes derselben Version per Workflow-Concurrency serialisieren.

## 4. OMV im eigenen Klassenzimmer

Eine Schule mit eigenem OpenMediaVault-S3-Dienst verwendet ihre eigenen Angaben und Zugangsdaten. `s3-intern` ist nicht übertragbar.

1. Mit der OMV-Administration klären, ob `ros-pi-gen-images` existiert. Falls nicht, die Anlage abstimmen. Testobjekte kommen nur unter `ros-pi-gen-test/`.
2. HTTPS-Endpoint und Signaturregion des Dienstes ermitteln. Beides ist installationsspezifisch und lässt sich nicht aus der LAN-Erreichbarkeit ableiten.
3. Auf dem Veröffentlichungsrechner ein eigenes AWS-Profil einrichten, mit separaten Zugangsdaten und Schreibrechten nur auf das gewählte Präfix. Schüler erhalten keinen Schreibzugang.
4. Anonymes Lesen per HTTPS mit der Administration einrichten. Keine Policy, ACL oder OMV-Einstellung ohne Freigabe ändern.
5. Aus dem Klassenzimmernetz Manifest und Image anonym abrufen, die Prüfsumme vergleichen und den Raspberry Pi Imager testen.
6. Endpoint, Profilname, Bucket, Region und Zugriffsvoraussetzungen lokal dokumentieren. Nichts davon wird committet oder zwischen Schulen geteilt.

Ein OMV-Dienst, der nur im LAN erreichbar ist, verhält sich erwartungsgemäß. OMV dient der lokalen Verteilung, Hetzner dem Zugriff über das Internet.

## 5. Versionen, Varianten, Paketnamen

**Produktions-Tags**
- Format: `image-YYYY.MM.PATCH`, zum Beispiel `image-2026.09.1`.
- Der Tag muss **annotiert** sein. Lightweight-Tags sind ungültig.
- Die Version kommt ausschließlich aus diesem Tag.
- `release_date` ist der Tagger-Zeitstempel in UTC. Jahr und Monat müssen dazu passen, auch wenn die lokale Zeit noch im Vormonat lag.
- PATCH beginnt bei 1 und zählt je Veröffentlichung hoch.
- Ungültige oder bereits veröffentlichte Versionen lehnt der GitHub-Release-Adapter vor dem Upload ab.

**Teststände**
- Gate-2/3-Tests: lokale, annotierte Tags `image-YYYY.MM.PATCH-test`. Die Paketversion trägt das Suffix, der Anzeigename ist als Test markiert, der Status ist `test`. Gate 3 ist mit Headless abgenommen; Desktop bleibt zurückgestellt.
- Test-Tags werden nicht gepusht und erzeugen weder Produktionsmanifeste noch GitHub-Releases.
- Gate-1-Pakete ohne Tag haben den Status `local-test` und einen Namen, der sie als nicht veröffentlichbar kennzeichnet. Sie gehen weder nach S3 noch zu GitHub. Paketstatus und Paketversion sind getrennte Werte.

**Varianten und Namen**
- Headless und Desktop sind unabhängig installierbar.
- Anzeigename: `Roboter-OS <YYYY.MM.PATCH> (Headless)` beziehungsweise `(Desktop)`.
- Dateinamen: `roboter-os-<version>-headless.img.xz` und `roboter-os-<version>-desktop.img.xz`. GitHub- und S3-Ziele verwenden exakt dieselben Namen.
- Jedes Manifest enthält genau einen passenden Eintrag mit genau einem Image. Einen automatischen Fallback gibt es nicht.

**Übergangsregelung (bis Desktop bereitgestellt ist)**

| | Headless-only (jetzt) | Vollständig (nach Desktop) |
|---|---|---|
| Images | 1 | 2 |
| Manifest-Assets | `headless-os-list.json` | zusätzlich `desktop-os-list.json` |
| Prüfsummen | `SHA256SUMS` mit 1 Dateinamen | `SHA256SUMS` mit 2 Dateinamen |

Der Adapter lehnt unvollständige Pakete ab, die nicht unter die Übergangsregelung fallen. Vor dem nächsten Produktions-Tag nach der Desktop-Bereitstellung muss der Workflow auf beide Varianten erweitert werden. Die Gate-2-Headless-Ausnahme ist kein Produktionsrelease.

**Release-Regeln**
- GitHub-`latest` zeigt nur auf ein vollständiges GitHub-Produktionsrelease (während der Übergangszeit auf ein Headless-only-Release). Test- und Prereleases werden nicht als `latest` markiert.
- Im aktuellen Workaround zeigen Image- und Icon-URLs im GitHub-Manifest auf versionierte GitHub-Release-Assets. Nach Wiederherstellung des Dual-Publish verweisen das S3-Manifest auf S3-Objekte und das GitHub-Manifest auf GitHub-Assets; beide Ziele bleiben gleichrangig.
- Die stabile Imager-URL jeder Quelle liefert nur ihr eigenes Manifest. Betreiber wählen die Quelle explizit; keine Quelle wird stillschweigend durch die andere ersetzt.
- `SHA256SUMS` hat das `sha256sum`-Format mit den kanonischen Dateinamen.
- Das Assetgrößenlimit von GitHub (erwartet: 2 GiB pro Asset) muss zum Umsetzungszeitpunkt verifiziert werden. Bei Überschreitung stoppen und die alternative Verteilung abstimmen.

## 6. `make package` und Manifest

`make package VARIANT=headless` beziehungsweise `VARIANT=desktop` paketiert je eine Variante. Der Ablauf ist lokal und in CI identisch.

1. **Version bestimmen.** Siehe Abschnitt 5. Genau ein passendes Build-Artefakt auswählen, bei keinem oder mehreren abbrechen. Buildnamen sind datumspräfixiert, etwa `image_<Datum>-raspberrypi-trixie-custom-lite.img.xz`.
2. **Umbenennen** auf den kanonischen Dateinamen.
3. **Prüfsummen und Größen** aus dem echten Artefakt ermitteln: SHA-256 des komprimierten und des entpackten Images, dazu Download- und Extraktgröße. Sie werden einmal erzeugt.
4. **Manifest rendern** mit expliziter Basis-URL. Keine Basis-URL raten:
   - lokal: `http://127.0.0.1:8000/`
   - Gate 2/3: bestätigte OMV- oder Hetzner-Objektbasis, nur für Testpakete
    - Produktion im aktuellen Workaround: die versionierte GitHub-Release-Asset-URL
    - Produktion nach Wiederherstellung: getrennte, bestätigte GitHub- und S3-Basen; gleichrangige Manifeste zeigen jeweils ausschließlich auf Assets ihrer eigenen Quelle

5. **Validieren.**
   - JSON-Syntax und Schema (Imager V4), gepinnt auf einen festen rpi-imager-Commit.
   - Die Geräteliste `os_list_imagingutility_v4.json` ändert sich mehrfach täglich (CI-Befund vom 2026-10-02). Deshalb wird nur der deterministisch serialisierte Teilblock `imager.devices` per SHA-256 gepinnt, nicht die Gesamtdatei.
   - `devices`-Tags werden gegen diese gepinnte Liste geprüft. `python3 -m json.tool` ist nur eine zusätzliche Syntaxprüfung.
6. **Im ersten echten Test** Manifestname, Schema und Imager-Kompatibilität verbindlich bestätigen.

**Inhalt des Manifests**
- Das Manifest folgt dem V4-Sublist-Schema. Kein `imager`-Katalogblock, keine erfundenen Felder.
- Geräte: arm64 Raspberry Pi 3/4/5, Tags exakt `pi3-64bit`, `pi4-64bit`, `pi5-64bit`. Keine 32-bit-Tags.
- `icon` ist Pflicht. Ein Icon aus dem Paket mit relativer URL verwenden.
- `capabilities` weglassen.
- `init_format`: `cloudinit-rpi`. Auf `cloudinit` nur bei einem nachgewiesenen Hardwareproblem wechseln und das im Generator dokumentieren.
- Keine `.bmap`-Datei, solange niemand sie beauftragt.

`rpi-imager-cli` ist nur ergänzend, bis ein Repository-Import mit einer konkreten, gepinnten CLI-Version nachgewiesen ist.

## 7. Quickfix-Stage `04-user-data` ausschließen

`stage-custom/04-user-data` ist ein Test-Quickfix. In Images für S3 oder GitHub hat sie nichts verloren.

- Der Release-Build deaktiviert die Stage vor dem Build. Vorher prüfen, ob die gepinnte pi-gen-Version die SKIP-Datei der Sub-Stage tatsächlich auswertet.
- **Nach dem Build, vor der Paketierung** muss das Image diese Prüfung bestehen:
  - keine Quickfix-Seed-Datei
  - kein Benutzer `robot` mit Passwort `robot`
  - keine aktivierte Passwort-SSH-Anmeldung
  - keine Betreiber-SSH-Schlüssel
- Schlägt die Prüfung fehl, abbrechen. Das Löschen der Seed-Datei im Nachhinein oder ein Imager-Wizard ersetzt die Prüfung nicht.

## 8. Etappen

### Etappe 1: lokaler HTTP-/Imager-Test

- `make package` rendert `os-list.json` ins Paketverzeichnis. Dort startet man einen HTTP-Server, zum Beispiel `python3 -m http.server 8000`.
- Manifest, Image und Icon müssen über dieselbe Basis-URL erreichbar sein.
- Auf demselben Rechner geht `http://127.0.0.1:8000/os-list.json`. Läuft der Imager in einer VM, braucht er eine vom Gast erreichbare Host-Adresse, die der VM-Konfiguration zu entnehmen ist.
- Gültig ist nur der echte Raspberry Pi Imager mit Repository-Import über HTTP. `curl`, ein direkter Image-Download oder `rpi-imager --cli --help` allein bestätigen den Import nicht.
- Das Image wird aus dem Gastnetz geladen und per SHA-256 gegen das Paketmanifest geprüft.
- Rollback: HTTP-Server mit Strg+C stoppen. Es bleiben keine dauerhaften Änderungen.

### Etappe 2: OMV/LAN-S3

Ziel: Schülergeräte holen Images im Klassenzimmernetz ohne Internet.

`tools/publish-s3.sh <paketverzeichnis>` ist der lokale Adapter.
- Er akzeptiert nur ein Headless-Testpaket mit Status `test`: ein Image, ein passendes Manifest, `SHA256SUMS`.
- Er prüft Paketdaten, Manifest, Image-Prüfsumme und die Wiederverwendung der Version.
- Bei fehlenden Leserechten oder unklaren Ergebnissen bricht er vor jedem Schreibzugriff ab.
- Schreiben erfordert `ROS_PI_GEN_GATE2_WRITE_APPROVED=yes`.
- Für MinIO setzt er `AWS_REQUEST_CHECKSUM_CALCULATION=when_required` und `AWS_RESPONSE_CHECKSUM_VALIDATION=when_required`.
- Er schreibt nur Headless-Image, Icon, versioniertes und stabiles Headless-Manifest, niemals Desktop- oder Produktionsobjekte.

Die Bucket-Policy gewährt anonymes `GetObject` nur auf `ros-pi-gen-test/*`, kein Listen, kein Schreiben. `ros-pi-gen/` ist unberührt. `ListObjectsV2` funktioniert mit `s3-intern-admin`. STS `GetCallerIdentity` lehnt dieser MinIO ab, der Publisher braucht es nicht.

**Rollback:** die archivierte vorherige Manifestkopie auf den stabilen Pfad zurückkopieren. Gibt es noch keine, anhalten und die Entscheidung erfragen.

### Etappe 3: Hetzner/WAN-S3

Ziel: öffentliche Verteilung über das Internet.

- Der Bucket `ros-pi-gen-images` (Region `hel1`) ist angelegt. Andere Buckets, insbesondere `kraeml-bayern`, werden nicht verwendet oder verändert.
- Das Gate-3-Headless-Testpaket wurde erfolgreich geprüft. Dieser abgeschlossene Teststatus erlaubt ausschließlich Testveröffentlichungen unter `ros-pi-gen-test/`, nicht die Reaktivierung von S3-Produktionsveröffentlichungen.
- Vor einer Bucket-Anlage prüfen, ob die Credentials sie erlauben. Anlage und Public-Read nur nach Freigabe, ohne bestehende Policies zu ersetzen.
- Schreiben nur nach `ros-pi-gen-test/*`. `publish-s3.sh` erzwingt den Status `test` und bricht ab, wenn unter `releases/<version>/` schon Objekte liegen.
- **Reihenfolge beim Upload:** erst Image und Icon hochladen und öffentlich samt Prüfsumme prüfen. Dann die versionierte Manifestkopie archivieren. Das stabile Manifest wird zuletzt aktualisiert.
- Abruf und Imager-Test erfolgen von außerhalb des eigenen Netzes.
- Verwaiste Releaseobjekte bleiben erhalten. Es wird nichts automatisch gelöscht.

### Etappe 4: portabler Runner und GitHub-Adapter

Der bestehende `GitHub-Image-Workflow.md` wird vor der Aktivierung mit dieser Anweisung abgeglichen. Diese Anweisung ist maßgeblich.

**Workflow auf `ubuntu-latest`** (dünner Adapter): Submodule initialisieren, Abhängigkeiten bereitstellen, Lint, Setup, freigegebene Varianten bauen und testen, paketieren, GitHub Release anlegen.

**Trigger:** nur ein annotierter Tag `image-YYYY.MM.PATCH`. Ungültiges Format oder bereits veröffentlichte Version scheitern vor jedem Upload. Testveröffentlichungen laufen nie über die Produktionsautomatisierung, sondern manuell und lokal über `publish-s3.sh`.

**Aktueller Ablauf (GitHub-only-Workaround):**
1. Nur Tagformat, GitHub-Release-Wiederverwendung und Paketkonsistenz prüfen. Keine S3-Profile, Credentials oder S3-Preflights.
2. Draft anlegen mit den kanonischen Images, dem variantenspezifischen GitHub-Manifest, `SHA256SUMS` und Icon.
3. Im Draft nur Existenz und Größe der Assets über die authentifizierte GitHub-API prüfen. Draft-Assets werden nicht anonym abgerufen.
4. Release veröffentlichen und als GitHub-`latest` markieren.
5. Danach versionierte GitHub-Asset-URLs und die stabile GitHub-Manifest-URL anonym per HTTPS samt Redirect prüfen.
6. Scheitert diese Prüfung, den Lauf stoppen und den Befund melden. Das Release wird nicht automatisch zurückgezogen und nichts automatisch gelöscht.

**Zielablauf nach ausdrücklicher S3-Reaktivierungsfreigabe:**
1. Vor dem ersten Upload GitHub und S3 auf Versionswiederverwendung prüfen. S3-Preflight ist read-only und muss bei unklarem Ergebnis geschlossen fehlschlagen.
2. GitHub-Draft erstellen und dessen Assets ausschließlich authentifiziert prüfen.
3. S3-Image und Icon in die versionierte Test- oder freigegebene Produktionsstruktur schreiben und anonym samt Größe und SHA-256 verifizieren.
4. Die S3-Manifestkopie versioniert archivieren, abrufen und inhaltlich validieren; das stabile S3-Manifest zuletzt aktualisieren.
5. GitHub-Release veröffentlichen und als `latest` markieren. Der S3-Stand und das GitHub-Release müssen dieselbe Version, Images und Prüfsummen enthalten.
6. Beide stabilen Manifest-URLs sowie die versionierten Assets jeder Quelle anonym prüfen. Bei Fehler anhalten; keine automatische Löschung oder Rücknahme. Die Quellen bleiben gleichrangig und ohne automatischen Fallback.

Die Reaktivierung erfordert zusätzlich zu Gate 4 eine eigene ausdrückliche Freigabe für Produktionsschreibzugriffe. Sie erfolgt erst nach dokumentierter Behebung des S3-Problems, erfolgreichem freigegebenem Testupload und Imager-Test sowie überprüftem Read-only-Produktionspreflight. Die bestehende S3-Produktionsimplementierung ist bis dahin kein freigegebener Workflow-Schritt.

**CI-Voraussetzungen:** pi-gen-Submodul am gepinnten Commit, Docker mit arm64/binfmt, ShellCheck, Testabhängigkeiten, ausreichend Speicher. Disk-Cleanup und den tatsächlichen Speicherbedarf beim ersten Lauf prüfen. Redirect-Verhalten von Manifest, Icon und Image beim ersten GitHub-Imager-Test prüfen.

## 9. Durchgehende Regeln

- Prüfsummen belegen Integrität, nicht Herkunft. Signaturen sind nicht Teil dieser Etappen.
- Alte Releaseobjekte werden nie automatisch gelöscht.
- Während des S3-Problems sind GitHub-Release-Assets das einzige aktive Produktionsziel. Zielarchitektur nach separater Reaktivierungsfreigabe: gleichrangige GitHub- und S3-Produktionsquellen, jeweils mit eigenem Manifest und ohne automatischen Fallback.
- S3-Testobjekte bleiben bis dahin ausschließlich Testziele der Gates 2 und 3. Produktionsobjekte dürfen erst nach den Wiederherstellungsbedingungen aus Abschnitt 1 geschrieben werden.

---

## Stand der Gates (Dokumentation, keine Regel)

**Gate 1 (abgeschlossen).** Der Raspberry Pi Imager lief in der grafischen Vagrant-VM, importierte das Repository über `http://192.168.33.1:8000/os-list.json` und schrieb das Testimage auf eine SD-Karte. Die SHA-256 des Downloads stimmte mit dem Paket überein. Die Imager-Version in der VM wurde nicht erfasst. Die Annahme ist damit nur für diese VM belegt, nicht für andere Versionen oder Umgebungen. Die Host-Version 1.7.5 war nicht die getestete.

**Gate 2 (Headless abgenommen, Desktop zurückgestellt).**
- `2026.10.1-test` scheiterte an einer Checksum-Inkompatibilität zwischen AWS CLI und MinIO (`InvalidArgument`). Es blieben keine Objekte zurück. Die Version wurde verworfen.
- `2026.10.2-test` wurde erfolgreich veröffentlicht und anonym geprüft (SHA-256 `cace6e0e…b2fbd2`). Sie bleibt als Rollback-Ziel erhalten.
- `2026.10.3-test` ist der aktuelle Stand. Es war ein echter `RELEASE_BUILD=1`-Build mit deaktivierter und auditierter Quickfix-Stage. SHA-256: `02449c5b…55752d`. Das stabile Manifest zeigt auf diese Version.
- Der Imager-Test lief in der VM `robotics-lab-vm` mit `rpi-imager 2.0.11.1-1`. Repository-Import, Anzeige samt Icon, Schreiben auf die SD-Karte und Verifikation waren erfolgreich.
- Beide Testversionen bleiben parallel erhalten. Ein Rollback wurde bisher nicht ausgeführt.

**Gate 3 (Headless abgenommen).**
- Public-Read gilt nur für `ros-pi-gen-images/ros-pi-gen-test/*`. Geprüft wurde anonym: Zugriff im Präfix 200, außerhalb 403, Bucket-Listing 403. Die Probe-Objekte wurden gelöscht.
- Ein früher angelegter, leerer Bucket `ros-pi-gen-test` wurde nach Bestätigung der Leere gelöscht. Er ist nicht mit dem Objektpräfix `ros-pi-gen-test/` zu verwechseln.
- `2026.10.3-test` wurde hochgeladen. Der erste Versuch brach wegen eines zu kurzen Client-Timeouts bei der Downloadverifikation ab. Das unvollständige Image wurde gelöscht, danach lief dieselbe Version vollständig durch.
- Anonyme Abrufe und SHA-256 stimmen (`02449c5b…55752d`). Stabiles und versioniertes Manifest sind identisch.
- Imager-Test über echtes NAT-Internet: Import, Anzeige und Schreiben auf die SD-Karte waren erfolgreich.
- Offen sind GitHub-Redirect, Assetgrößen (Etappe 4) und die Desktop-Variante.

---

## Die wichtigsten Änderungen

- **Wiederholungen entfernt.** Die Regel „nur `ros-pi-gen-test/`, Produktion unberührt“ stand ursprünglich rund zwanzigmal im Text. Sie steht jetzt einmal im Abschnitt Zugriff und einmal in den Etappen, wo sie operativ gilt.
- **Regeln und Berichte getrennt.** Die Testergebnisse standen verstreut zwischen den Vorgaben. Sie stehen jetzt gesammelt am Ende, die Regeln bleiben schlank.
- **Tabellen statt Fließtext.** Das betrifft die Gates, die Profile und die Übergangsregelung.
- **Kurze Sätze statt Einschubketten.** Die Regelreihenfolge ist übersichtlicher, die Bedeutung ist unverändert.
- **Gekürzt wurden:** doppelte Erklärungen zu Variantenumfang, `latest` und Manifest-Rendering sowie mehrfach genannte Details zu Path-Style und Policy.
- **Gekürzte Prüfsummen** (`cace6e0e…b2fbd2`, `02449c5b…55752d`) dienen nur der Lesbarkeit. Die vollständigen Werte stehen im Original und sollten dort bleiben, wo sie als Beleg gebraucht werden.
