#!/bin/bash
# doitpi_firstboot.sh – Einmaliges Skript für den ersten Start von DoitPi
#
# Aufgaben:
#   - Ansible und Python-Interpreter prüfen (Warnung bei Fehler, kein Abbruch)
#   - Alte Benutzer- und Pfadangaben (/home/pi, User=pi) in systemd-Units ersetzen
#   - Ersten Start als erledigt markieren und bei Änderungen sauber neu starten
#   - Alte /home/pi-Pfade im Home-Verzeichnis des Benutzers ersetzen

# Bei Fehlern, nicht gesetzten Variablen und fehlschlagenden Pipes abbrechen
set -euo pipefail

# Log-Umleitung: Alle Ausgaben (stdout + stderr) in Datei UND auf Bildschirm
exec 1> >(tee -a /var/log/doitpi_firstboot.log)
exec 2>&1

# Hilfsfunktion: Meldung mit Zeitstempel auf stderr ausgeben
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >&2
}

# Prüft, ob die Cloud-init-Stufe "init" im aktuellen Boot erfolgreich war.
#
# Warum diese Stufe: Sie enthält das Anlegen bzw. Umbenennen des Benutzers
# (users_groups). Erst danach ist UID 1000 verlässlich der Zielbenutzer.
#
# Warum Python statt Bash: status.json ist JSON; mit grep/sed ließe sich der
# Block der richtigen Stufe nicht robust herausfiltern ("end" und "errors"
# kommen in jeder Stufe vor). Cloud-init ist selbst in Python geschrieben,
# python3 ist hier also immer vorhanden.
#
# Warum nicht "cloud-init status": Der Befehl fasst alle Stufen zusammen und
# meldet zu diesem Zeitpunkt noch "running". Mit --wait würde der Dienst auf
# cloud-final warten und einen Ordering-Zyklus erzeugen.
#
# Rückgabewerte:
#   0  Stufe beendet und ohne Fehler
#   1  Stufe nicht beendet oder mit Fehlern
#   2  Statusdatei fehlt, ist kein gültiges JSON oder hat unerwartete Struktur
cloudinit_init_ok() {
    python3 - <<'PY'
import json, sys
try:
    with open("/run/cloud-init/status.json") as f:
        stage = json.load(f)["v1"]["init"]
except (OSError, KeyError, TypeError, ValueError):
    sys.exit(2)
if not isinstance(stage, dict) or not isinstance(stage.get("errors"), list):
    sys.exit(2)
sys.exit(0 if (stage.get("end") or stage.get("finished")) and not stage["errors"] else 1)
PY
}

# Hilfsfunktion: Text in allen Dateien eines Verzeichnisses ersetzen.
# Aufruf: replace_in_files <suchmuster> <ersatz> <verzeichnis>
# Das Suchmuster ist ein regulärer Ausdruck (GNU sed, Basismodus).
# Ausgabe: Pfade der tatsächlich geänderten Dateien auf stdout, eine pro Zeile.
replace_in_files() {
    local search="$1" replace="$2" dir="$3" file
    # grep findet nur Dateien mit Treffer, sed läuft also nur dort.
    # "|| true", weil grep ohne Treffer mit 1 endet und set -e sonst abbricht.
    while IFS= read -r -d '' file; do
        sed --in-place "s|${search}|${replace}|g" "${file}"
        echo "${file}"
    done < <(grep --recursive --files-with-matches --null -- "${search}" "${dir}" 2>/dev/null || true)
}

# Nur als root ausführen, da systemweite Dateien geändert werden
if (( EUID != 0 )); then
    echo "Dieses Skript muss als root ausgeführt werden." >&2
    exit 1
fi

# Markerdatei: Existiert sie, wurde der erste Start bereits abgeschlossen
MARKER=/var/lib/doitpi/firstboot.done
if [[ -e "${MARKER}" ]]; then
    log "Erster Start bereits erledigt, beende."
    exit 0
fi

# Erfolg der Cloud-init-Netzwerkstufe vor der Benutzerermittlung sicherstellen.
CLOUDINIT_STATUS=0
cloudinit_init_ok || CLOUDINIT_STATUS=$?
if (( CLOUDINIT_STATUS != 0 )); then
    case "${CLOUDINIT_STATUS}" in
        1) log "Cloud-init-Netzwerkstufe mit Fehlern oder nicht beendet, Marker wird nicht gesetzt." ;;
        2) log "Cloud-init-Status fehlt oder ist ungültig (/run/cloud-init/status.json), Marker wird nicht gesetzt." ;;
        *) log "Cloud-init-Prüfung konnte nicht ausgeführt werden (Exit-Code ${CLOUDINIT_STATUS}), Marker wird nicht gesetzt." ;;
    esac
    exit 1
fi

mkdir -p "$(dirname "${MARKER}")"

# Passwd-Eintrag des Standardbenutzers (UID 1000) holen, sonst abbrechen
USER_ENTRY=$(getent passwd 1000 || true)
if [[ -z "${USER_ENTRY}" ]]; then
    log "Fehler: Kein Benutzer mit UID 1000 gefunden."
    exit 1
fi
USER_NAME=$(echo "${USER_ENTRY}" | cut --delimiter=: --fields=1)
USER_HOME=$(echo "${USER_ENTRY}" | cut --delimiter=: --fields=6)

# Ansible-Test 1 (immer, auch offline): Das Modul "ping" prüft, ob Ansible
# und der System-Python zusammenarbeiten. Es ist kein ICMP-Ping und ändert
# nichts am System.
log "Teste Ansible mit dem Modul ping."
if ! ansible \
        --extra-vars ansible_python_interpreter=/usr/bin/python3 \
        --inventory localhost, --connection local \
        --module-name ping \
        localhost; then
    log "Warnung: Ansible-Test (ping) fehlgeschlagen. Installation und Python-Interpreter prüfen."
fi

# Alte Pfade und Benutzernamen in den systemd-Units ersetzen.
# "/home/pi" nur als ganzer Pfadbestandteil, damit z. B. /home/pilot unberührt bleibt.
# Sind Dateien geändert worden, ist ein Neustart nötig, damit systemd sie einliest.
CHANGED_FILES=""
if [[ "${USER_NAME}" != "pi" ]]; then
    CHANGED_FILES=$(
        {
            replace_in_files '/home/pi\b' "${USER_HOME}" /etc/systemd/system
            replace_in_files '^User=pi$' "User=${USER_NAME}" /etc/systemd/system
        } | sort -u
    )
fi

NEEDS_REBOOT=false
if [[ -n "${CHANGED_FILES}" ]]; then
    log "Units geändert, Neustart wird nötig."
    NEEDS_REBOOT=true
fi

# Codeserver für den neuen Benutzer aktivieren.
systemctl enable "code-server@${USER_NAME}.service"

# --- Home-Verzeichnis: alte /home/pi-Pfade ersetzen ---------------------------
# Python-venvs (Shebangs, pyvenv.cfg, activate-Skripte), ~/.bashrc und andere
# Dateien im Home-Verzeichnis enthalten absolute Pfade auf /home/pi und
# funktionieren nach dem Umzug auf einen anderen Benutzer nicht mehr.
# Statt eine feste Liste zu pflegen, wird das gesamte Home-Verzeichnis
# durchsucht. Bei Treffern wird ein Neustart angefordert, damit alle Dienste
# und Sitzungen mit den angepassten Dateien starten.
if [[ "${USER_NAME}" != "pi" ]]; then

    # Dateien mit Treffer sammeln:
    #   --binary-files=without-match : Binärdateien überspringen
    #   --null / mapfile -d ''       : Dateinamen mit Leerzeichen bleiben heil
    #   --exclude-dir=.cache         : Cache-Inhalte sind reproduzierbar und
    #                                  müssen nicht angepasst werden
    #   || true                      : "keine Treffer" (Exit-Code 1) ist ein
    #                                  normaler Zustand und darf wegen
    #                                  "set -e" nicht zum Abbruch führen
    #   \b (Wortgrenze) verhindert Fehlersetzungen in Pfaden wie /home/pixel.
    #   "/home/pi/platformio-env" wird korrekt erkannt, weil auf das "i"
    #   ein "/" folgt. \b setzt GNU grep und GNU sed voraus (Standard auf
    #   Raspberry Pi OS).
    mapfile -d '' home_files < <(
        grep --recursive --binary-files=without-match --files-with-matches \
             --null --no-messages \
             --exclude-dir=.cache \
             '/home/pi\b' "${USER_HOME}" || true
    )

    if (( ${#home_files[@]} > 0 )); then
        log "Ersetze /home/pi in ${#home_files[@]} Dateien unter ${USER_HOME}."

        # \b (Wortgrenze) verhindert Fehlersetzungen in Pfaden wie /home/pixel.
        # "/home/pi/platformio-env" wird korrekt erkannt, weil auf das "i"
        # ein "/" folgt. \b setzt GNU sed voraus (Standard auf Raspberry Pi OS).
        sed --in-place "s|/home/pi\b|${USER_HOME}|g" "${home_files[@]}"

        # sed --in-place legt intern eine neue Datei an. Läuft das Skript als
        # root, kann der Besitzer dabei wechseln; chown stellt ihn wieder her.
        chown --no-dereference "${USER_NAME}:" "${home_files[@]}"
        NEEDS_REBOOT=true
    fi
fi

# Build-Hilfsdatei entfernen: Sie erzwingt bei Paket-Updates immer die neue
# Konfigurationsdatei des Pakets und würde eigene Anpassungen überschreiben.
rm -f /etc/apt/apt.conf.d/99forceconfnew

# Ersten Start als erledigt markieren und Dienst für künftige Starts deaktivieren.
# "disable" ohne "--now", weil das Skript selbst noch läuft.
touch "${MARKER}"
systemctl disable doitpi_firstboot.service \
    || log "Warnung: Dienst konnte nicht deaktiviert werden."

# Neustart nur, wenn Units geändert wurden oder das System ihn anfordert
# (/var/run/reboot-required legen z. B. Kernel-Updates an)
if [[ "${NEEDS_REBOOT}" == true || -e /var/run/reboot-required ]]; then
    sync
    log "Starte in 20 Sekunden neu."
    sleep 20
    systemctl reboot
else
    log "Erster Start abgeschlossen, kein Neustart nötig."
fi
