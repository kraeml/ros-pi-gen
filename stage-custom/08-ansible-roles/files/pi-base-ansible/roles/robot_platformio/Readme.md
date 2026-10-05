# robot_platformio – PlatformIO Entwicklungsumgebung

Ansible-Rolle zur Installation von [PlatformIO](https://platformio.org/) auf dem Raspberry Pi.
PlatformIO ermöglicht die Entwicklung und das Flashen von Firmware für Mikrocontroller
(z. B. Arduino, ESP32, STM32) direkt vom Pi aus.

## Beispiel-Playbook

```yaml
- hosts: robots
  roles:
    - robot_platformio
```

Oder gezielt via Tag:

```bash
ansible-playbook -i provisioning/ansible/inventories/dev provisioning/ansible/playbook.yml --tags platformio
```

## Variablen

| Variable | Beschreibung | Standardwert |
|----------|-------------|--------------|
| `robot_platformio_venv_path` | Pfad zum PlatformIO-Virtualenv | `{{ ansible_facts['user_dir'] }}/platformio-venv` |
| `robot_platformio_packages` | Systemabhängigkeiten (apt) | Siehe `defaults/main.yml` |

## Was wird installiert?

- Systemabhängigkeiten via `apt` (Python, Build-Tools, USB-Bibliotheken)
- PlatformIO via `pip` in einem eigenen Virtualenv unter `~/platformio-venv`
- PATH-Eintrag in `~/.bashrc` (wirksam nach erneutem Login oder `source ~/.bashrc`)

## Hinweise

- PlatformIO steht nach der Installation unter `~/platformio-venv/bin/pio` zur Verfügung
- Der PATH wird in `~/.bashrc` eingetragen – für die aktuelle Session `source ~/.bashrc` ausführen
- USB-Zugriff auf Programmer/Debugger erfordert ggf. udev-Regeln (werden von PlatformIO automatisch eingerichtet: `pio system install udev`)
