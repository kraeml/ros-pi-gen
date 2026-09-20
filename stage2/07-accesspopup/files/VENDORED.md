# Vendored Upstream: RaspberryConnect/AccessPopup

- Quelle: https://github.com/RaspberryConnect/AccessPopup
- Gepinnter Commit: `ba6eff170d6bf04848d4ea93da06d5cd7068b16f` (main, 2026-07)
- Versionen im Pin: accesspopup 0.9 (22.03.2026), installconfig.sh 1.01, acpu_web wie gepinnt
- Lizenz: GPL-3.0 (`LICENSE` im Original mitgeliefert)

## Enthalten

| Datei | Zweck |
|---|---|
| `accesspopup` | Hauptskript (AP↔WLAN-Wechsel, NM-AP-Modus, 2-Min-Timer) |
| `accesspopup.conf` | AP-Defaults; von ros-pi-gen vorbelegt (`ap_pw='Pi-WLAN-Setup-2026'`, `ap_ssid`-Platzhalter) |
| `acpu_web/` | Optionale Web-UI (Port 8052); Abhängigkeiten gepinnt in `requirements.txt` |
| `LICENSE` | GPL-3.0 im Original |

## Nicht enthalten (für den Image-Build irrelevant)

- `installconfig.sh` – interaktiver Installer (Schritte in `01-run.sh` repliziert)
- `nw_setup_offline.sh` – nur vom interaktiven Installer genutzt
- `README.md` / `ChangeLog.txt` – Original online

## Update-Vorgehen

1. Neuen Upstream-Commit wählen (`git ls-remote https://github.com/RaspberryConnect/AccessPopup.git main`)
2. Dateien in `files/` ersetzen, Pin + Versionsstand **hier** und in `TODO.md` (Block 2) aktualisieren
3. Build (`build-docker.sh`) + Tests gemäß `AccessPopup.md` §8
