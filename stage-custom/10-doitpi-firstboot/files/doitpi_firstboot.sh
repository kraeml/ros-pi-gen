#!/bin/bash
# doitpi_firstboot.sh – Einmaliges Skript für den ersten Start von DoitPi
#
# Aufgaben:
#   - Ansible und Python-Interpreter testen (immer, auch offline)
#   - Alte Benutzer- und Pfadangaben (/home/pi, User=pi) in systemd-Units ersetzen
#   - APT-Paketlisten per Ansible aktualisieren, falls Internet vorhanden ist
#   - Ersten Start als erledigt markieren und bei Änderungen sauber neu starten

# Bei Fehlern, nicht gesetzten Variablen und fehlschlagenden Pipes abbrechen
set -euo pipefail

# Hilfsfunktion: Meldung mit Zeitstempel auf stderr ausgeben
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >&2
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
mkdir -p "$(dirname "${MARKER}")"
if [[ -e "${MARKER}" ]]; then
    log "Erster Start bereits erledigt, beende."
    exit 0
fi

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
    log "Fehler: Ansible-Test (ping) fehlgeschlagen. Installation und Python-Interpreter prüfen."
    exit 1
fi

# Alte Pfade und Benutzernamen in den systemd-Units ersetzen.
# "/home/pi" nur als ganzer Pfadbestandteil, damit z. B. /home/pilot unberührt bleibt.
# Sind Dateien geändert worden, ist ein Neustart nötig, damit systemd sie einliest.
CHANGED_FILES=""
if [[ "${USER_NAME}" != "pi" ]]; then
    CHANGED_FILES=$(
        {
            replace_in_files '/home/pi\(/\|$\)' "${USER_HOME}\1" /etc/systemd/system
            replace_in_files '^User=pi$' "User=${USER_NAME}" /etc/systemd/system
        } | sort -u
    )
fi

NEEDS_REBOOT=false
if [[ -n "${CHANGED_FILES}" ]]; then
    log "Units geändert, Neustart wird nötig."
    NEEDS_REBOOT=true
fi

# Internetverbindung prüfen (3 Versuche, je 2 Sekunden Timeout)
if ping -c 3 -W 2 9.9.9.9 &>/dev/null \
   || curl --connect-timeout 2 -sI https://1.1.1.1 &>/dev/null; then
    log "Internet verfügbar, aktualisiere Paketlisten mit Ansible."

    # Ansible-Test 2 (nur mit Internet): Das Modul "apt" aktualisiert die
    # Paketlisten und prüft nebenbei, ob das apt-Modul funktioniert.
    #   --connection local      : kein SSH, direkt auf diesem Rechner
    #   --inventory localhost,  : Inventar aus einem einzelnen Host (Komma beachten!)
    #   cache_valid_time=3600   : Update überspringen, wenn der Cache jünger als 1 h ist
    if ! ansible \
            --extra-vars ansible_python_interpreter=/usr/bin/python3 \
            --inventory localhost, --connection local \
            --module-name apt \
            --args "update_cache=yes cache_valid_time=3600" \
            localhost; then
        log "Fehler: Ansible-Test (apt) fehlgeschlagen."
        exit 1
    fi
else
    log "Warnung: Keine Internetverbindung, apt-Test und Paketlisten-Update übersprungen."
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
