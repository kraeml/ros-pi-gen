# Testprotokoll – AccessPopup / WLAN-AP-Fallback

Vorlage für die Abnahmetests gemäß AccessPopup.md §8.6. Jede Zeile ausfüllen;
ein Test gilt erst als bestanden, wenn „Erwartet" eingetreten ist **und**
„Beobachtet" das bestätigt.

## Metadaten

| Feld | Wert |
|---|---|
| Datum | |
| Tester/in | |
| Pi-Modell | (z. B. Pi 4B 4 GB) |
| Image-Stand | (Dateiname + pi-gen-Commit `74d08a3`) |
| AccessPopup-Pin | `ba6eff1` (`files/VENDORED.md`) |
| Web-UI | AccessPopup-Web-UI, Port 8052, Dispatcher-gated |
| AP-Defaults | SSID `<hostname>-AP` · PW `Pi-WLAN-Setup-2026` · IP `192.168.50.5` |

---

## Gruppe Q – QEMU-Smoke-Test (Build-Host, vor dem Flashen)

| # | Testfall | Erwartet | Beobachtet | OK |
|---|---|---|---|---|
| Q1 | Image bootet in qemu-aarch64 | Kein Kernel-Panik, Login/SSH erreichbar | | ☐ |
| Q2 | `systemctl is-enabled AccessPopup.timer` | `enabled` | | ☐ |
| Q3 | `systemctl is-enabled hostname-ssid.service` | `enabled` | | ☐ |
| Q4 | `systemctl is-enabled acpu_web.service acpu_web_app.socket` | **nicht** enabled (Dispatcher-Gating) | | ☐ |
| Q5 | `/etc/accesspopup.conf` | `ap_pw='Pi-WLAN-Setup-2026'`, `ap_ssid`-Platzhalter vorhanden | | ☐ |
| Q6 | `nft -c -f /etc/nftables.d/accesspopup.rules` | Syntax OK | | ☐ |
| Q7 | Dispatcher-Dateirechte | `0755`, root:root, nicht gruppenschreibbar | | ☐ |
| Q8 | `visudo -cf /etc/sudoers.d/acpu` | OK (im Build-Log) | | ☐ |
| Q9 | `systemctl status NetworkManager-dispatcher` | Unit vorhanden/aktivierbar | | ☐ |

---

## Gruppe A – Grundfunktion (Erstkonfiguration, Zuhause)

Voraussetzung: kein WLAN gespeichert (frisches Image, Imager nur für Hostname).

| # | Testfall | Erwartet | Beobachtet | OK |
|---|---|---|---|---|
| A1 | Boot ohne bekanntes WLAN | AP erscheint ≤ 2 min nach NM-Start | | ☐ |
| A2 | SSID-Prüfung | SSID = `<hostname>-AP`, Fallback `Roboter-AP` bei unbrauchbarem Hostnamen | | ☐ |
| A3 | Verbinden per Smartphone (PW `Pi-WLAN-Setup-2026`) | Verbindung erfolgreich | | ☐ |
| A4 | Captive-Portal-Erkennung | Portal öffnet automatisch (iOS/Android/Windows) | | ☐ |
| A5 | Fallback-URL | `http://192.168.50.5:8052` öffnet die Web-UI | | ☐ |
| A6 | Heim-WLAN einrichten (Web-UI) | Profil wird gespeichert; Erfolgsmeldung + Hinweis zum Wechsel | | ☐ |
| A7 | AP-Abschaltung | Roboter im Heim-WLAN (≤ 2 min), AP verschwindet, Portal gestoppt | | ☐ |

## Gruppe B – Schul-/Heim-Wechsel (Mehrfachnutzung)

| # | Testfall | Erwartet | Beobachtet | OK |
|---|---|---|---|---|
| B1 | Schul-WLAN per Pi-Imager + individueller Hostname | Schul-Verbindung beim ersten Boot (kein AP in der Schule) | | ☐ |
| B2 | Hostname im Imager geändert (z. B. `roboter-07`) | AP-SSID folgt Hostnamen (`roboter-07-AP`) | | ☐ |
| B3 | Heim-WLAN über Portal ergänzen | Beide Profile gleichzeitig gespeichert (`nmcli con show`: Schul- + Heim-Profil) | | ☐ |
| B4 | Zuhause: Boot | Verbindet automatisch ins Heim-WLAN, kein AP | | ☐ |
| B5 | Zurück in die Schule | Schul-WLAN automatisch (Autoconnect), Heim-Profil bleibt gespeichert | | ☐ |
| B6 | WLAN-Verlust (Schul-WLAN aus/fallen) | AP kehrt nach ≤ 2 min zurück | | ☐ |
| B7 | Besser werdendes WLAN | Wechsel zurück ins WLAN, sobald bekanntes Netz wieder in Reichweite und kein AP-Client mehr verbunden | | ☐ |

## Gruppe C – Fehlerfälle

| # | Testfall | Erwartet | Beobachtet | OK |
|---|---|---|---|---|
| C1 | Falsches WLAN-Passwort | Neues Profil wird verworfen; vorherige Profile unangetastet; AP kehrt zurück (kein Fehlerloop) | | ☐ |
| C2 | Ungültige SSID (Steuerzeichen/zu lang) | Eingabe im Portal/Helper abgelehnt, kein beschädigtes Profil | | ☐ |
| C3 | WLAN außer Reichweite | AP nach ≤ 2 min | | ☐ |
| C4 | Kurzzeitiger WLAN-Verlust (< 2 min) | Roboter verbindet sich selbst wieder, kein AP-Zwischenspiel | | ☐ |
| C5 | Mehrere bekannte WLANs | Verbindet mit dem besten/verfügbaren bekannten Netz (NM-Autoconnect) | | ☐ |
| C6 | Gleichzeitige Portal-Anfragen (2 Browser) | Keine korrupten Profile; zweiter Client wartet/bricht sauber ab | | ☐ |
| C7 | Neustart während der Konfiguration | Nach Reboot startet AP erneut; Konfiguration wiederholbar | | ☐ |
| C8 | Stromverlust während Profiländerung | Kein korruptes NM-Profil (NM-Profile werden atomar geschrieben) | | ☐ |
| C9 | Zwei Pis nebeneinander | Individuelle SSIDs (`<host>-AP`), Ports/IPs konfliktfrei je Gerät | | ☐ |

## Gruppe D – Isolation & Gating (Sicherheit)

| # | Testfall | Erwartet | Beobachtet | OK |
|---|---|---|---|---|
| D1 | AP-Client → Internet | **Gesperrt** (nft forward-Drop trotz NM-shared-NAT) | | ☐ |
| D2 | AP-Client → SSH auf den Pi | **Gesperrt** | | ☐ |
| D3 | AP-Client → Docker-/ROS-Ports | **Gesperrt** | | ☐ |
| D4 | AP-Client → Portal/DNS/DHCP/mDNS | Funktioniert | | ☐ |
| D5 | `nft list ruleset` während AP | Tabellen `ip accesspopup` + `ip6 accesspopup` geladen; nach AP-Ende entfernt | | ☐ |
| D6 | Web-UI aus dem Schul-/Heim-LAN | **Nicht** erreichbar (Port 8052 zu, außer im AP-Fenster) | | ☐ |
| D7 | Normaler WLAN-Betrieb ohne AP | SSH/Docker/ROS aus Heim-WLAN wie üblich erreichbar (Regeln entfernen nichts) | | ☐ |

---

## Ergebnis

| Gruppe | Bestanden | Anmerkungen |
|---|---|---|
| Q – QEMU | ☐ | |
| A – Grundfunktion | ☐ | |
| B – Schul-/Heim-Wechsel | ☐ | |
| C – Fehlerfälle | ☐ | |
| D – Isolation/Gating | ☐ | |

Offene Punkte / Follow-ups:

```text
(Platz für Notizen)
```

Abgenommen am: ____________ von: ____________
