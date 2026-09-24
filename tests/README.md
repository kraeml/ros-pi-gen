# Testinfra – automatisierte Abnahmehilfe (Gruppe Q)

Automatisiert die **Gruppe Q** des
[Testprotokoll-AccessPopup.md](../Testprotokoll-AccessPopup.md) in drei
Ebenen — **Build-Log** (Q0), **Image-Inhalt** (Datei-Manifest, Q1–Q9-
Vorprüfungen im arm64-Container) und **echte Hardware** (`pi-smoke.sh`,
Q1–Q9 final am Pi). Die Gruppen A–D bleiben manuell; `pi-state.sh` und
`pi-smoke.sh` liefern die Beobachtungen.

## Schnellstart

```bash
# venv im Repo-Root einmalig anlegen (falls noch nicht vorhanden)
python3 -m venv ../.venv && ../.venv/bin/pip install -r requirements.txt

./run_tests.sh                    # Build-Host-Ebene: Q0 + Q1a + Q2–Q9 + Manifest
./run_tests.sh -k q5              # einzelner Test
./run_tests.sh --clean-cache      # Test-Cache (tests/.work) vor dem Lauf löschen

# Hardware-Lauf (Gruppe Q final am echten Pi, read-only):
ssh pi@<ip> 'bash -s' < tests/tools/pi-smoke.sh
```

Komfortabler via Makefile im Repo-Root: `make venv`, `make test`
(durchgereicht an diese Suite) — siehe
[README](../README.md#build-mit-make-empfohlener-weg).

`run_tests.sh` findet die venv automatisch unter `ros-pi-gen/.venv`
(überschreibbar mit `PIGEN_TEST_VENV`), installiert `requirements.txt`
idempotent darin und ruft pytest auf. Alternativ direkt:
`../.venv/bin/python -m pytest .` (Aufruf aus `tests/`).

## Voraussetzungen (Build-Host-Ebene)

| Werkzeug | Wofür |
|---|---|
| Docker Engine + arm64-Emulation | Container-Tests (Q1a, Q2–Q9, hostname-SSID) — `docker run --platform linux/arm64 debian:trixie true` muss gehen; die Suite setzt den nötigen OFD-tauglichen Container-qemu-Entry **selbst** (Sessionstart, `tools/binfmt.sh setup` — gleicher Version-Gate-Mechanismus wie beim Build; auf qemu ≥ 8-Hosts No-op; Opt-out `PIGEN_TEST_NO_BINFMT=1`). Hintergrund: nach `make build` ist der Build-Entry entfernt und Host-qemu 4.x wedged systemd beim Q1a-Container-Boot (fcntl-OFD → EINVAL) |
| `7z`, `debugfs` (e2fsprogs) | Boot-Partition entpacken, ext4 lesen (ohne Root) |
| nftables-Hilfscontainer | Q6 (wird einmalig gebaut, dann gecached) |

**Platzbedarf:** Cache unter `tests/.work/` (8–12 GB je nach Image-/
Variantenumfang: entpacktes Image, Partitions-Slices, RootFS-Staging).
`PIGEN_TEST_CACHE` überschreibbar; `PIGEN_TEST_CLEAN=1` löscht vor dem
Lauf — `--clean-cache` (Schnellstart) setzt intern dieselbe Variable.
Kein sudo nötig.

**Image-Auswahl:** automatisch die neueste `image_*.img[.xz]` in
`ros-pi-gen/deploy/` (Docker-Build via `make build`) bzw.
`ros-pi-gen/pi-gen/deploy/` (nativer/manueller Lauf), überschreibbar mit
`PIGEN_TEST_IMAGE=/pfad/zum/image.img.xz`.

## Testkatalog (Build-Host-Ebene)

| Test | Protokoll | Prüft | Methode |
|---|---|---|---|
| `test_q0a–d` | – | Image vorhanden, pi-gen-Commit gepinnt (`74d08a3`), `07-accesspopup/01-run.sh` gelaufen (nicht geskippt), Log vollständig & zum Image passend | Build-Log + `.info` |
| `test_q0e–g` | – | Build-Log: jedes `Begin` hat `End`, **kein `Skip`**, Pflichtstufen komplett (stage0–2 inkl. 05/06/07 + export-image), docker-ce/ansible-Installation belegbar (`Setting up …` bei Erstinstallation, `… is already the newest version` bei Wiederholungslauf mit persistiertem `work/`) + visudo-Beleg | Build-Log |
| `test_q1a` | Q1 | systemd-Boot des RootFS im arm64-Container: `running`/`degraded` + exec-Zugang | Docker, privilegiert |
| `test_image_files[*]` | – | Datei-Manifest: Overlay-Dateien im RootFS + Boot-Partition, Docker/Ansible-Binaries, Inhalts-Marker (`ap_pw`, `table ip accesspopup`, Redirect 8052, …) | debugfs |
| `test_q2` | Q2 | `AccessPopup.timer` = `enabled` | Container |
| `test_q3` | Q3 | `hostname-ssid.service` = `enabled` | Container |
| `test_q4` | Q4 | `acpu_web*` **nicht** enabled; keine wants-Symlinks | Container + debugfs |
| `test_q5` | Q5 | `ap_pw='Pi-WLAN-Setup-2026'`, `ap_ssid`-Platzhalter | debugfs |
| `test_q6` | Q6 | `nft -c accesspopup.rules` | nativer amd64-Hilfscontainer (`--network host`) |
| `test_q7` | Q7 | Dispatcher `0755`, root:root | debugfs `stat` |
| `test_q8` | Q8 | `visudo -cf /etc/sudoers.d/acpu` + Beleg im Build-Log | Container + Build-Log |
| `test_q9` | Q9 | `NetworkManager-dispatcher` vorhanden/aktivierbar | Container |
| `test_overlay_*` | – | Overlay-Dateien: Exec-Bits, `00-packages` je Stage, AccessPopup-Dateisatz | Repo-Dateien |
| `test_hostname_ssid[*]` | §8.6 | `hostname-ssid.sh`-Logik: `<hostname>-AP`, Umlaute, Kürzung, Fallback, idempotent; **Hostnamenwechsel** (Dispatcher-Fall: SSID folgt neuem Hostnamen statt bestehendem `ap_ssid`) | Docker (stub-hostname) |
| `test_extras_*` | TODO Block 3 | docker-ce/ansible installiert, docker.service enabled, cloud-init ok | Container |

## Architektur (Build-Host-Ebene)

Session-scoped Fixture-Kette (tests/conftest.py) — die Suite **baut kein
Image**, sie setzt `make build` voraus:

1. `discover_image` — neuestes `image_*.img[.xz]` aus `deploy/` bzw.
   `pi-gen/deploy/` (überschreibbar `PIGEN_TEST_IMAGE`); ohne Fund → Skip.
2. `prepare` — Image entpacken, Partition-Slices in den Cache
   (`tests/.work`); daraus liest `debugfs` root_img/boot.
3. `find_build_log` — komplette `build-docker.log`/`build.log` neben der
   Image-Quelle (pro Build einmaliges Artefakt, keine Rotation).
4. `stage_rootfs` → `docker import` — RootFS-Staging-Kopie einmal pro
   Session als arm64-Image importieren (Owner via `--owner=0` normalisiert,
   Tag aus Pfad-Digest).
5. `crun` — pro Aufruf ein frischer `docker run --rm --platform linux/arm64`
   gegen dieses importierte Image (kein Zustand zwischen Befehlen).

Container-Modell: **Q1a** startet einen laufenden systemd-Container
(`docker run -d --privileged`, am Testende aufgeräumt); **Q2–Q9** spawnen
Wegwerf-Container je Befehl vom selben RootFS (`is-enabled`/`visudo` lesen
Unit-Dateien — kein gebootetes System nötig); **Q6** nutzt ein separates
amd64-Hilfsimage mit `--network host`.

Q2–Q9 hängen **nicht** von Q1 ab (kein Test-Ordering/Dependency):
`BOOT_TIMEOUT` wirkt nur auf die Q1a-Poll-Schleife; bei Q1-Fail laufen
Q2–Q9 eigenständig weiter.

## Hardware-Läufe (Gruppe Q final am Pi)

`tests/tools/pi-smoke.sh` läuft **auf dem Pi** (read-only) und prüft Q1–Q9
hier endgültig — insbesondere **Q6 gegen den echten bcm-Kernel**:

```bash
ssh pi@<ip> 'bash -s' < tests/tools/pi-smoke.sh
```

Erzeugt eine Markdown-Tabelle (Q-IDs, PASS/FAIL), Beobachtungs-Hilfen für
A/B/D (hostname→SSID, NM-Profile, AP-Zustand, Port 8052, nft-Tabellen,
`accesspopup.conf` mit maskiertem Passwort, Journal-Tail) und Exit-Code 0
nur bei bestandenen harten Q-Checks. Status-Schnellreport ohne Pass/Fail-
Logik: `tools/pi-state.sh`.

Empfohlener Abnahmefluss: erst `run_tests.sh` am Build-Host (spürt
Build-/Paketierfehler vor dem Flashen), dann `pi-smoke.sh` am Gerät, dann
die manuellen Protokollzeilen A–D mit den ausgegebenen Beobachtungen.

## Warum kein QEMU-Vollsystem-Test?

Ein echter Kernel-Boot-Test in QEMU (qemu 6.2, `-M raspi3b`) wurde versucht
und **abgebrochen**. Gesicherte Befunde der Diagnose (für einen späteren
Versuch mit qemu ≥ 9 wertvoll):

1. `kernel8.img` ist gzip-komprimiert — `qemu -kernel` braucht das entpackte
   rohe arm64-Image (Magic `ARM\x64` an Offset 0x38).
2. `raspi3b` verlangt Zweierpotenz-SD-Größe (qcow2-Overlay mit 8G löst das).
3. Das Image-DTB bindet die **PL011 an das Bluetooth-serdev**
   (`brcm,bcm43438-bt`): kernel-printk erscheint, aber Userspace-Schreibzugriffe
   auf `/dev/console` landen im BT-Port — die Konsole bleibt stumm. Fix im
   Diagnosestand: compatible-Zeichenkette in einer gepatchten DTB-Kopie
   neutralisieren.
4. `earlycon=pl011,mmio32,0x3f201000` ist nötig (ohne `mmio32` stumm).
5. K.O.-Kriterium: systemd stirbt früh (`bpf-restrict-fs`-Schritt) und der
   Gast resettet — `bcm2835_powermgt_write: WDOG`/RSTC-Schreibzugriff löst in
   qemu 6.2 einen **Maschinen-Reset** aus (Quellcode-Kommentar: „XXX: should
   be a per-board reset"). `systemd-bpf-restrict-fs` zu maskieren ändert
   daran nichts; Kernel, SD, RootFS und `/sbin/init`-Start funktionieren bis
   dahin nachweislich.
6. qemu-user 6.2 (Container-Emulation) hat eigene Grenzen (Service-Spawn mit
   `Result: resources`) — deshalb bleibt Q1a bewusst auf Boot-Zustand +
   exec-Zugang beschränkt.

`pi-smoke.sh` am echten Gerät ist der saubere Ersatz: gleiche Prüfungen,
echter Kernel, echte Peripherie.

## Grenzen

- **Q1a** prüft kein echtes Kernel-Booting — der Kernel-Beleg kommt vom
  Hardware-Lauf (`pi-smoke.sh`, Q1).
- **pi-gen-Pin (`74d08a3`, Q0b):** bewusste Stabilitätsentscheidung —
  Updates nur per Pin-Änderung im ros-pi-gen-Repo, nie automatisch
  (Rationale: README, Abschnitt Struktur / TODO Block 1, Pin-Update-
  Politik).
- **Q6** (Container) validiert Syntax/Features gegen den Host-Kernel; der
  verbindliche Lauf ist Q6 am Pi (bcm-Kernel) bzw. der Hardware-Test D5.
  Voraussetzung: `NETLINK_NETFILTER` mit geladenen `nf_tables`/`nfnetlink`-
  Modulen im Host-Kernel (moderne Kernel-Versionen bringen das mit; das
  Docker-Bridge-Netns bietet den Netlink nicht — daher `--network host`).
  Bei „Protocol not supported" skippt der Test statt zu failen.
- **Q2–Q9** werden im Container am echten RootFS geprüft (echte `systemctl`/
  `visudo`-Binaries), Ownership via `tar --owner=0` beim Import normalisiert.
- Q0 erwartet, dass der neueste Build-Log zum neuesten Image gehört
  (`build-docker.log`/`build.log` im selben Verzeichnis).
- **Q8** liest den Build-Log komplett ein (`build_log_text`); die Log-Datei
  ist ein pro Build einmaliges Artefakt neben dem Image (keine Rotation) —
  Kürzung/Verlust würde auch Q0a–d treffen, Risiko damit theoretisch.
- **Q1a-Fail-Output:** Container-Log-Tail (2000 Zeichen) geht in die
  pytest-Ausgabe; vollständige Container-Logs als CI-Artefakt speichern
  = Aufgabe des Workflows (siehe GitHub-Image-Workflow.md, Upload-Schritt).
- **extras/cloud-init** prüft bewusst nur „nicht failed" (Oneshot-Service,
  nach Boot typ. inactive) — als spätere Verfeinerung böte
  `cloud-init status` ein präziseres Signal (done/running/error/degraded,
  meldet auch interne Fehler trotz „erfolgreich beendet").
- Hardware-Gruppen A–D (AP-Verhalten, Captive Portal, Isolation, Mehrgeräte)
  bleiben manuell — die Automatisierung liefert nur Beobachtungen.

## Umgebungsvariablen

| Variable | Default | Wirkung |
|---|---|---|
| `PIGEN_TEST_IMAGE` | auto (neuestes in `deploy/` bzw. `pi-gen/deploy/`) | explizites Image |
| `PIGEN_TEST_CACHE` | `tests/.work` | Cache-Verzeichnis |
| `PIGEN_TEST_CLEAN` | – | `1` = Cache vor dem Lauf löschen (`--clean-cache` setzt intern diese Variable). Nicht parallel-sicher (pytest-xdist): wirkt prozessübergreifend |
| `PIGEN_TEST_BOOT_TIMEOUT` | `900` | Q1a: Sekunden bis systemd-Zustand |
| `PIGEN_TEST_DOCKER_TIMEOUT` | `300` | Timeout je Container-Kommando |
| `PIGEN_TEST_NO_BINFMT` | – | `1` = Container-qemu-Entry nicht selbst setzen/räumen (wenn der Host binfmt anderweitig managed) |
| `PIGEN_TEST_VENV` | `ros-pi-gen/.venv` | venv für run_tests.sh |

## Wartung

- **Manifest ergänzen:** `test_image_files.py` — Liste `ROOTFS_MANIFEST` /
  `BOOT_MANIFEST` (eine Zeile pro Datei oder Inhalts-Marker).
- **Neue Dateien in `stage-custom/07-accesspopup/files/`:** zwei Stellen —
  Liste in `test_overlay_files.py::test_overlay_accesspopup_files_komplett`
  (Overlay-Ebene) und ggf. `ROOTFS_MANIFEST` in `test_image_files.py`
  (Image-Ebene).
- **Pflichtstufen ergänzen:** `REQUIRED_SUBSTAGES` in `test_q0_image_stand.py`.
- Änderungen an `stage-custom/**` → Overlay-Guard sofort, Image-Tests nach Rebuild.
- Neue Protokollzeilen in Gruppe Q → Testfunktion mit passender ID
  (`test_q<N>_*`) bzw. Abschnitt in `pi-smoke.sh`.
