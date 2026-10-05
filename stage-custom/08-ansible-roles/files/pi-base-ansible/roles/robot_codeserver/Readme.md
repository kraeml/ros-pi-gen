# 🛠️ `robot_codeserver` - Rolle für Entwicklungszwecke

## 📌 Einsatzzweck

Diese Rolle installiert **code-server** für **lokale Entwicklungsumgebungen**.
⚠️ **Nicht für den produktiven Einsatz geeignet!**

## ⚠️ Sicherheitshinweise

- **Passwort** (`robot_codeserver_password`) **MUSS geändert werden**, bevor der Service öffentlich zugänglich ist!
- **Bind-Adresse**: `0.0.0.0:8080` (nur für vertrauenswürdige Netzwerke verwenden!)
- **Keine HTTPS-Verschlüsselung** (nur für lokale Entwicklung oder vertrauenswürdige Netzwerke)
- **Firewall**: Port 8080 muss ggf. manuell freigegeben werden

## 🔧 Variablen

| Variable | Beschreibung | Standardwert |
|----------|-------------|--------------|
| `robot_codeserver_password` | Passwort für den Web-Login | `"change_me"` *(⚠️ Ändern!)* |
| `robot_codeserver_port` | Port, auf dem code-server lauscht | `8080` |

## 🚀 Installation

```yaml
- hosts: robots
  roles:
    - robot_codeserver
```
