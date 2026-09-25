# WLAN am Roboter einrichten – Anleitung für Einsteiger

Diese Anleitung richtet das Heim-WLAN am Roboter ein. Die Schul-WLAN-Daten
werden von der Lehrkraft mit dem **Raspberry-Pi-Imager** aufgespielt — hier
geht es nur um das WLAN zu Hause.

> **Hinweis für die Lehrkraft (Imager 2.0):** Ab Imager 2.0 ist für die
> Customization (Hostname, Schul-WLAN) ein **Repository-JSON für unser
> Roboter-Image nötig** — "Use custom" allein wird übersprungen (Details:
> [Raspberry-Pi-Imager-2.0.md](Raspberry-Pi-Imager-2.0.md)). Bis das Manifest
> ausgerollt ist: Imager ≥ 2.0.6 einsetzen und den Flash-Vorgang vorher am
> Testgerät prüfen.

## Was du brauchst

- Den Namen deines Heim-WLANs (SSID) und das WLAN-Passwort
- Ein Handy oder Laptop
- Den Namen (Hostname) deines Roboters, z. B. `roboter-07` (steht im
  Imager-Setup und wird von der Lehrkraft genannt/angeschrieben)

## Schritt für Schritt

1. **Roboter einschalten** und 1–2 Minuten warten.
2. **Mit dem Roboter-WLAN verbinden:** In der WLAN-Liste von Handy/Laptop
   erscheint der Access Point deines Roboters:
   ```text
   SSID:     roboter-07-AP        (= Hostname + „-AP")
   Passwort: Pi-WLAN-Setup-2026   (Lehrkraft verteilt es)
   ```
   Jeder Roboter hat seine eigene SSID — so findest du immer **deinen**
   Roboter.
3. **Portal öffnen:** Beim Verbinden öffnet sich das Einrichtungs-Fenster
   (Einrichtungsassistent/„Captive Portal") meist automatisch.
   Wenn nicht: Browser öffnen und
   ```text
   http://192.168.50.5:8052
   ```
   eingeben (wichtig: **http**, nicht https).
4. **Heim-WLAN eintragen:** Im Portal „Add New WiFi Network“ wählen und
   WLAN-Name (SSID) sowie Passwort manuell eingeben. Der Scan wird vermieden,
   weil er den Access Point auf manchen Geräten unterbrechen kann.
5. **Verbindung wechseln:** Der automatische Prüf-Timer pausiert während des
   Versuchs. Bei Erfolg verbindest du dein Handy/Deinen Laptop mit dem
   Heim-WLAN. Bei falschen Zugangsdaten wird der Roboter-AP wiederhergestellt.

## Typische Probleme

| Problem | Lösung |
|---|---|
| Portal öffnet sich nicht | `http://192.168.50.5:8052` manuell im Browser aufrufen (http, nicht https) |
| Browser warnt „kein Internet" | Normal — AP hat kein Internet. „Trotzdem verbinden"/„Bleiben" wählen |
| Heim-WLAN wird nicht angezeigt | SSID immer manuell eintragen; der Scan ist absichtlich nicht Teil des Einrichtungsablaufs |
| „Falsches Passwort" beim Heim-WLAN | Der Verbindungsversuch schlägt fehl und der Roboter-AP wird wiederhergestellt; Zugangsdaten erneut eingeben |
| AP verschwindet, Roboter taucht im Heim-WLAN nicht auf | 1–2 Minuten warten; der Roboter wechselt selbst. Roboter-Schalter: kurz aus/an, dann startet der AP wieder (Problem-Suchmodus) |
| Ich finde meinen Roboter nicht | AP-Name = Hostname + „-AP". Mehrere Roboter nebeneinander → die SSIDs unterscheiden sich |
| Heim-WLAN geändert (neuer Router/Passwort) | Vorgang einfach wiederholen — erst AP, dann Portal, dann neue Daten |

## Gut zu wissen

- Der AP dient **nur zur Einrichtung** — danach bleibt nur das normale WLAN.
- Der Roboter merkt sich **beide** WLANs: In der Schule verbindet er sich
  mit dem Schul-WLAN, zu Hause mit dem Heim-WLAN — ganz ohne Neueinrichtung.
- Mit dem Heim-WLAN erreichst du den Roboter wie üblich über SSH
  (`ssh pi@roboter-07` bzw. die IP-Adresse).
- Der AP-Verschlüsselungsmodus ist WPA2; bei längeren AP-Sitzungen (über
  10 Minuten, z. B. Fehlersuche) bittet die Lehrkraft um Passwort-Änderung
  in der Web-Oberfläche des AP.

Technische Details (für Betreiber:innen): siehe README-Abschnitt
„AccessPopup – WLAN-AP-Fallback mit Web-UI" und [AccessPopup.md](AccessPopup.md).
