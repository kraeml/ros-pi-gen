# AccessPopup – Konzept & Lösungsrecherche (KI-Arbeitspapier)

> **Zweck dieses Dokuments:** Als vollständiger Prompt für eine KI-Anfrage dienen,
> um inhaltliche Lösungen für das automatische WLAN-/AccessPoint-Management im
> Roboter-Image zu bewerten und einen Umsetzungsplan zu erarbeiten. Alle relevanten
> Fakten sind hier enthalten – die KI braucht keinen Repo-Zugriff.

---

## 1. Kontext

**Projekt:** Eigenes Raspberry-Pi-OS-Image (Debian **Trixie**, **arm64**) für einen
autonomen Roboter, gebaut mit [pi-gen](https://github.com/RPi-Distro/pi-gen)
(arm64-Branch, gepinnter Commit `74d08a3`, Stand 2026-09) aus dem Overlay-Repo
`ros-pi-gen`. Eigene Sub-Stages: `05-docker-ansible` (Docker CE + Ansible),
`06-variant` (Paketlisten headless/desktop), `07-accesspopup` (AccessPopup
AP-Fallback + Web-UI, umgesetzt).

**Relevante Image-Fakten (verifiziert):**

- **NetworkManager** ist Netzbetreiber: in pi-gens `stage2/02-net-tweaks`
  (network-manager, wpasupplicant, WLAN-Firmware) und zusätzlich in
  `06-variant/00-packages` (headless) enthalten
- **cloud-init** wird von pi-gens `stage2/04-cloud-init` **immer** installiert
  (`cloud-init` + `rpi-cloud-init-mods`), ist aber faktisch schlafend: ohne
  `ENABLE_CLOUD_INIT=1` installiert die Stage keine
  `user-data`/`meta-data`/`network-config` nach `/boot/firmware` → cloud-init
  findet keine Datasource-Dateien und konfiguriert nichts
  - Synergie: Raspberry-Pi-Imager-OS-Customization (WLAN vorkonfigurieren) schreibt
    genau diese Dateien → cloud-init legt beim First Boot die NM-Profile an
- **Randbedingung aus pi-gen:** ohne `WPA_COUNTRY` in der config schreibt
  `02-net-tweaks` `WirelessEnabled=false` nach `/var/lib/NetworkManager/`
  (WLAN-Radio ist ab First Boot soft-disabled) → Abhilfe: `WPA_COUNTRY='DE'` in
  der pi-gen-config setzen
- **Interfaces:** Raspberry Pi OS nutzt `wlan0` (keine predictable names für
  Onboard-WLAN); USB-Dongles kämen als `wx*`/`wlx*` dazu
- **Pi-Modelle:** Pi 3B+/4/5; headless-Betrieb; kein Desktop in der Default-Variante
- **Build-Pipeline:** pi-gen-Chroot (Docker, QEMU-arm64); Installation im Image
  muss **nicht-interaktiv** laufen; NetworkManager läuft im Chroot **nicht** →
  nichts darf zur Build-Zeit einen laufenden NM oder aktives Radio voraussetzen

---

## 2. Kernidee / Zielbild

Der Roboter bleibt **ohne konfiguriertes WLAN erreichbar**. Genauer:

1. Boot ohne gespeicherte WLAN-Zugangsdaten (oder kein bekanntes WLAN in Reichweite)
   → Gerät aktiviert einen **temporären AccessPoint**
2. Nutzer verbindet sich per **Browser** (Einsteiger-freundlich, möglichst ohne CLI)
   mit dem AP und hinterlegt SSID + Passwort des Heim-WLANs
3. Gerät verbindet sich ins Heim-WLAN; AP schaltet ab
4. Verliert das Gerät später das WLAN (Reichweite, Ausfall) → AP kommt
   automatisch wieder zurück

**Design-Entscheidung (bereits festgelegt):**

- Der AP dient **ausschließlich zur WLAN-Konfiguration** (kein Dauer-AP)
- Aktivierung nur, wenn kein WLAN konfiguriert/erreichbar ist
- Default-SSID/-Passwort sind akzeptabel, weil der AP nur bei fehlendem WLAN aktiv ist
- **Wichtig:** bei längerem AP-Einsatz (>10 min) müssen Passwort und
  Firewall-Regeln angepasst werden (Sicherheitsfenster)

---

## 3. Anforderungen & Constraints

| # | Anforderung | Art |
|---|---|---|
| A1 | NetworkManager-basiert (NM ist im Image Netzbetreiber) | Muss |
| A2 | PiOS Bookworm+/Trixie-Kompatibilität (Trixie arm64) | Muss |
| A3 | Einsteiger-Konfiguration im **Browser**, nicht per CLI | Muss |
| A4 | Nicht-interaktive Installation im pi-gen-Chroot möglich | Muss |
| A5 | Dauerhaft im Image (headless-Variante), wartbar & versioniert | Muss |
| A6 | Roboter-Anwendung (ROS 2 in Docker/Ansible) darf nicht gestört werden | Sollte |
| A7 | Kleines Bild-Volumen; keine Desktop-Abhängigkeiten | Sollte |
| A8 | GPLv3- oder MIT-kompatible Lizenz, Quelle vendor'bar | Sollte |
| A9 | Log-Diagnose (war der AP aktiv? warum?) per SSH einsehbar | Nice |

**Bekannte technische Stolpersteine:**

- Interaktive Installer (Menü mit `read`) sind im pi-gen-Chroot unbrauchbar; ein
  laufender NM ist dort nicht vorhanden
- hostapd-Systemdienst kollidiert mit NM-AP-Modus, wenn er enabled ist
  (dnsmasq als Dienst analog; `dnsmasq-base` als Bibliothekspaket ist ok)
- Beim AP→WLAN-Wechsel (und zurück) brechen SSH/VNC-Verbindungen ab
- Scan während aktivem AP ist je nach Chip nicht möglich (→ manueller SSID-Fallback)

---

## 4. Offene Fragen (an die KI)

1. Welcher Lösungsansatz erfüllt A1–A9 am besten? (Vergleichsmatrix, siehe §5)
2. AP nur „kein WLAN konfiguriert" vs. „kein bekanntes WLAN erreichbar" –
   welches Verhalten ist für einen mobilen Roboter sinnvoller?
3. Captive-Portal-Redirect (Auto-Öffnen des Konfigurationsportals) – wert?
4. Soll der AP **parallel** (virtuelles Interface `uap0`) oder **exklusiv**
   (NM-AP-Modus auf `wlan0`) laufen?
5. Sicherheitskonzept für das AP-Fenster: Passwortrotation, nftables-Regeln,
   Web-UI-Auth?
6. Teststrategie: QEMU-Smoke-Test (Boot, Timer enabled, Ports) +
   Real-Hardware-Checkliste?

---

## 5. Bestehende Lösungen (Rechercheergebnis)

| Lösung | Ansatz | Browser-Konfig. | NM-kompatibel | Lizenz | Anmerkung |
|---|---|---|---|---|---|
| [AccessPopup](https://github.com/RaspberryConnect/AccessPopup) (RaspberryConnect, 2026) | Bash + systemd-Timer (alle 2 min); NM-AP-Modus (`nmcli device wifi hotspot`, `ipv4.method=shared`), kein hostapd; Wechsel AP↔WLAN | ✅ optionale Web-UI (Python/uvicorn, Port 8052) | ✅ rein nmcli/iw | GPL-3.0 | Abhängig: `iw`, `dnsmasq-base`; Default SSID `AccessPopup`, PW `1234567890`, IP `192.168.50.5`; wird von Waveshare-Robotern (WAVEGO Pro) eingesetzt; Installer interaktiv → im Build nachzubilden; letzte Änderung 2026-07, kleiner Einmann-Fork-Risiko |
| [Autohotspot](https://www.raspberryconnect.com/projects/65-raspberrypi-hotspot-accesspoints/183-raspberry-pi-automatic-hotspot-and-static-hotspot-installer) (RaspberryConnect) | Wie AccessPopup, aber dhcpcd-basiert (ältere PiOS) | ❌ | ❌ (dhcpcd) | GPL-3.0 | Nur relevant für Bullseye-; für unser NM-Image ungeeignet |
| [pi-wifi-setup](https://github.com/medvedodesa/pi-wifi-setup) (2026) | Python-Paket (`pip install`); **hostapd+dnsmasq auf virtuellem `uap0`** parallel zu `wlan0`; **Captive Portal** (DNS-Redirect auf http://192.168.4.1); Flask-Web-UI; Zugangsdaten via `nmcli` gespeichert; **GPIO-Taster** reaktiviert Setup-Modus; Hooks `on_pause`/`on_resume` für die Roboter-App | ✅ Portal öffnet automatisch | ⚠️ speichert via nmcli, aber AP läuft über hostapd | MIT | Passt gut zur „Einsteiger"-Anforderung; konkurriert aber mit NM-AP-Design (hostapd-Dienst); Pip-Paket in pi-gen integrierbar |
| [RaspAP](https://github.com/RaspAP/raspap-webgui) | Vollwertige Router-Web-GUI (hostapd + dnsmasq-Dienst + lighttpd, Client-Konfig, VPN etc.) | ✅ ausgereift | ❌ hostapd-architektur | GPL-3.0 | Overkill + Architekturkonflikt mit „NM als Owner"; für Travel-Router (Dauer-AP) gemacht, nicht für Setup-AP |
| [Kupiki-Hotspot-Script](https://github.com/pihomeserver/Kupiki-Hotspot-Script) | hostapd + CoovaChilli Captive Portal + Nginx | ✅ | ❌ | GPL-3.0 | Alt/ungepflegt; Chilli-Overkill |
| [rsmoorthy gist „Switch Hotspot/Wifi"](https://gist.github.com/rsmoorthy/30e2b373cf4fcae59af12af060d21134) | Einfaches Bash-Skript + systemd, Config-Datei `/boot/wificfg.txt` | ❌ | teilweise | – | Minimal, keine Pflege, als Referenz brauchbar |
| OpenWrt-Travelrouter (z. B. [Build-Script](https://www.reddit.com/r/raspberry_pi/comments/1avxvfz/openwrt_raspi_travelrouter_build_script_multiwan/), GL.iNet-Hardware) | Ganz anderes OS (OpenWrt, Multi-WAN, VPN, Captive-Portal) | ✅ | – | GPL/andere | Für „Roboter braucht ROS/Debian" nicht einsatzbar; nur als Muster für Travel-Router-Features |
| Raspberry-Pi-Imager + cloud-init (im Image vorhanden) | WLAN **vor** dem ersten Boot per Imager-Customization setzen → cloud-init schreibt NM-Profile | ✅ (Imager-App, nicht im AP) | ✅ | – | Kein AP-Fallback; gute **Ergänzung** (Primärkonfig), nicht Ersatz |
| Eigenbau-Mini-Skript (~50 Zeilen) | systemd-Timer: wenn kein WLAN-Profil aktiv → `nmcli device wifi hotspot …` | ❌ (nmcli-only) | ✅ | – | Schlank, aber ohne Web-UI; Edge-Cases (Scan-Busy, Profil-Erneuerung, PiZeroW-Quirks) selbst pflegen |

**Vorgemerkte Empfehlung (vorab evaluiert, von der KI zu verifizieren):**
AccessPopup als Basis (NM-konform, Web-UI, aktiv gepflegt, Anforderung A1–A5
erfüllbar) + `WPA_COUNTRY='DE'` in der config; pi-wifi-setup als Alternative,
wenn Captive-Portal-Öffnen und GPIO-Taste wichtiger sind als reine
NM-Architektur. Für die Build-Integration gilt in beiden Fällen: Installation
nicht-interaktiv in einer eigenen pi-gen-Sub-Stage `07-accesspopup`
(`00-packages`: iw, dnsmasq-base, python3-venv, python3-pip; `NN-run.sh`
repliziert die Installer-Schritte; Units nur `enable`, kein Start im Chroot).

---

## 6. Bewertungsmatrix-Vorlage für die KI-Ausgabe

Kriterien (Gewichtung frei argumentieren):

1. Erfüllung Muss-/Soll-Anforderungen (§3)
2. Wartungsaufwand (externes Projekt vs. Eigenbau; Fork-Abhängigkeit)
3. Build-Integration (nicht-interaktiv, Chroot-fähig, Versionierbarkeit)
4. Einsteigerfreundlichkeit (Browser, Captive Portal, Ohne-Terminal)
5. Sicherheit im AP-Fenster (Auth, Firewall, >10-Min-Regel)
6. Bild-Volumen & Boot-Verhalten (Timer, Latenz, Roboter-App-Störung)
7. Diagnosebarkeit (Logs, Status-Abfrage)

Erwartetes Output-Format: Vergleichsmatrix → begründete Empfehlung
(Primär + Fallback) → Umsetzungsplan in Stufen (Pakete/Dateien/Units/
Konfig) → Test-Checkliste (QEMU + Real-Hardware) → Risikoliste.

---

## 7. Anhang: AccessPopup-Technik (verifiziert, für die KI ohne Netz)

- **Units:** `AccessPopup.service` (ExecStart=/usr/local/bin/accesspopup,
  After=multi-user.target, Requires=network-online.target) +
  `AccessPopup.timer` (OnBootSec=0min, OnCalendar=*:0/2)
- **AP-Profil:** `nmcli device wifi hotspot ifname wlan0 con-name AccessPopup
  ssid <SSID> band bg channel 6 password <PW>` dann
  `nmcli connection modify … ipv4.method shared ipv4.addr 192.168.50.5/24
  ipv4.gateway 192.168.50.254` (RSN/CCMP/WPA2, powersave aus)
- **Konfig:** `/etc/accesspopup.conf` → `wdev0`, `ap_ssid`, `ap_pw`, `ap_ip`,
  `ap_gate`, `re_enable_wifi`
- **Web-UI:** `/usr/local/bin/acpu_web` (FastAPI/uvicorn via systemd-Socket
  `0.0.0.0:8052`), eigener Systemuser `acpu` + sudoers
  (`NOPASSWD: /usr/bin/nmcli, /usr/sbin/iw, /usr/bin/tee, /etc/accesspopup.conf,
  /usr/local/bin/accesspopup`); Funktionsumfang: AP↔WLAN-Schalter,
  WLAN-Profile anlegen/bearbeiten/löschen, AP-SSID/PW ändern
- **Verhalten:** alle 2 min Prüfung; bekanntes WLAN in Reichweite → Rückwechsel
  (nicht während Clients am AP); `sudo accesspopup -a` = Dauer-AP
- **Bekannte Grenzen:** Web-UI ohne Auth; SSH/VNC-Abbruch beim Wechsel; Scan
  während AP je nach Chip unmöglich (→ manuelle SSID-Eingabe); kein
  Captive-Portal-Auto-Open (Nutzer muss IP/Port selbst aufrufen)

---

## 8. Umsetzungsplan v2.1 (umgesetzt 2026-09)

Umsetzung: `stage-custom/07-accesspopup/` (`00-packages`, `01-run.sh`, `files/`
inkl. `VENDORED.md`), `config` (`WPA_COUNTRY`-Fallback), README-Abschnitt
„AccessPopup – WLAN-AP-Fallback mit Web-UI", Nutzeranleitung
[WLAN-Anleitung.md](WLAN-Anleitung.md), Abnahmetests
[Testprotokoll-AccessPopup.md](Testprotokoll-AccessPopup.md).
Restende: QEMU-Smoke (Gruppe Q) + Hardware-Tests (Gruppen A–D), siehe TODO
Block 2/3.

Ergebnis der Planprüfung und Entscheidungen; supersedes die Empfehlungen aus §5.

### 8.1 Festgelegte Entscheidungen

| Punkt | Entscheidung |
|---|---|
| Basis | AccessPopup **unverändert**, vendor't + gepinnt (Commit `ba6eff1…`, siehe `stage-custom/07-accesspopup/files/VENDORED.md`), GPL-3.0-Lizenz mitgeliefert |
| Konfig-Frontend | **AccessPopup-Web-UI nutzen** (Port 8052) – kein eigenes Portal-App-Entwickeln; Web-Units werden **nicht** enable'd, sondern vom NM-Dispatcher **nur im AP-Fenster** gestartet (keine Exposition auf Schul-/Heim-LAN) |
| Captive-Portal-Effekt | ohne eigene HTTP-App: DNS-Wildcard (`/etc/NetworkManager/dnsmasq-shared.d` → `address=/#/192.168.50.5`) + nft-Redirect `tcp/80 → :8052` auf wlan0; HTTP-Proben der Clients landen direkt in der Web-UI |
| AP-Defaults | SSID `<hostname>-AP` (Hostname = Geräteidentität via Pi-Imager – **keine Etiketten, MAC nicht ablesbar**; Fallback `Roboter-AP`), Passwort `Pi-WLAN-Setup-2026` (einheitlich bekannt, aufs Kursmaterial), IP `192.168.50.5` |
| Regulierungsdomäne | `export WPA_COUNTRY="${WPA_COUNTRY:-DE}"` in der config – DE nur Build-Fallback, Imager-Wert bleibt zur Laufzeit maßgeblich |
| Sub-Stage | `stage-custom/07-accesspopup/` mit pi-gen-Konvention `00-packages` + `01-run.sh` + `files/` |

### 8.2 Architektur

```
AccessPopup (unverändert)          → AP↔WLAN-Wechsel, 2-min-Zyklus, NM-Profilverwaltung
AccessPopup-Web-UI (:8052)         → WLAN-Profile per Browser (Dispatcher-gated)
DNS-Wildcard + nft-Redirect 80→8052→ Captive-Detection öffnet das Portal automatisch
NM-Dispatcher 90-accesspopup-portal→ orchestriert Start/Stop + Profil-Tweaks
hostname-ssid.service              → SSID aus Hostnamen, auch beim Hostname-Wechsel
nft-Tabelle accesspopup            → AP-Clients isoliert (nur DHCP/DNS/Portal/mDNS)
```

### 8.3 Dispatcher-Logik

| NM-Event | Aktion |
|---|---|
| `up` + `CONNECTION_ID=AccessPopup` | Profil-Tweaks erneut anwenden (`ipv6.method=disabled`, `autoconnect=no` – AccessPopup kann das Profil bei Aktivierungsfehlern neu erzeugen!) → Web-Units + nft-Regeln starten |
| `down` + `CONNECTION_ID=AccessPopup` | Web-Units stoppen, nft-Tabellen (ip + ip6) löschen |
| Action `hostname` | `hostname-ssid.sh` ausführen; falls AP aktiv: Profil mit neuer SSID neu aufsetzen |

### 8.4 Firewall

- Eigene nft-Tabelle mit Prioritäten **< 0** → greift vor NMs `nm-shared-*`-Regeln (NM shared aktiviert per Default NAT/Forward für AP-Clients)
- Input auf wlan0: nur DHCP (67), DNS (53), Portal (80→Redirect, 8052), mDNS (5353) – **Drop für alles andere** (kein SSH/Docker/ROS vom AP)
- Forward: komplettes Drop für wlan0 (kein Internet/Ethernet-Durchgriff); ip6-Tabelle analog
- Regeln nur während AP aktiv (Dispatcher lädt/entlädt)

### 8.5 Build (pi-gen-Chroot)

`00-packages`: `iw`, `dnsmasq-base`, `nftables`, `python3-venv`, `python3-pip`.
`01-run.sh`: installiert Skript/Conf (ap_pw vorbelegt), Units + Drop-in
(`AccessPopup.service.d/order.conf` → `After=hostname-ssid.service`, Fix für
das Boot-Race bei `OnBootSec=0min`), acpu-User + sudoers (visudo-Check),
venv + gepinnte pip-Abhängigkeiten, Dispatcher/dnsmasq/nft-Dateien;
`systemctl enable AccessPopup.timer hostname-ssid.service`; **nicht** im Build:
NM-Start, AP, Scan, Skriptlauf, Web-Units-enable.

### 8.6 Tests

> **Nachtrag 2026-09-21:** der QEMU-Smoke-Test (Vollsystem-Boot in
> qemu-aarch64) wurde nach tragfähiger Diagnose abgebrochen und durch drei
> Ebenen ersetzt: Build-Log-Prüfung, Datei-Manifest + Container-Boot
> (`tests/run_tests.sh`) und Gruppe Q final am echten Gerät
> (`tests/tools/pi-smoke.sh`). Befunde und Grenzen (u. a. BT-serdev vs.
> `/dev/console`, `bcm2835_powermgt`-Maschinen-Reset in qemu 6.2):
> [tests/README.md](tests/README.md), Abschnitt „Warum kein QEMU“.
> Die Liste unten ist der ursprüngliche Plan (Historie).

- **QEMU-Smoke:** Units enabled (`AccessPopup.timer`, `hostname-ssid.service`), Web-Units **disabled**, conf-Inhalt, `nft -c`-Syntax, Dispatcher-Rechte, First-Boot-SSID (Imager-Hostname → `roboter-07-AP`)
- **Hardware A:** Boot ohne WLAN → SSID `<hostname>-AP` → Captive-Portal öffnet / Fallback `http://192.168.50.5:8052` → Heim-WLAN einrichten → AP verschwindet
- **Hardware B:** Schul-WLAN via Imager + eigener Hostname → Heim-WLAN per Portal → beide Profile gleichzeitig gespeichert → automatischer Wechsel Schul↔Zuhause
- **Hardware C:** falsches Passwort (neues Profil wird gelöscht, kein Fehlerloop), WLAN-Ausfall → AP nach ≤ 2 min, 2 Pis parallel → individuelle SSIDs, Web-UI **nicht** aus dem Heim-/Schul-LAN erreichbar, AP-Clients ohne Internet/SSH/Docker/ROS, Stromverlust während Profiländerung

### 8.7 Risiken / dokumentierte Grenzen

- Uniformes bekanntes AP-Passwort + auth-lose Web-UI: nur im AP-Fenster exponiert (Dispatcher-Gating); für Dauereinsatz Passwort ändern
- First Boot: SSID ggf. kurz `raspberrypi-AP` bis cloud-init den Imager-Hostnamen setzt → `hostname`-Dispatcher-Event korrigiert nach (Testen)
- Wechsel AP↔WLAN bricht SSH/VNC ab; Web-UI-Seite timeoutet beim Speichern absichtlich (Client muss ins neue WLAN wechseln)
- Scan während aktivem AP je nach Chip unmöglich → Web-UI bietet manuelle SSID-Eingabe
- Admin-Weg im laufenden WLAN: `sudo accesspopup -a` (Dauer-AP) → Web-UI erscheint im AP-Fenster; zurück mit `sudo accesspopup`
