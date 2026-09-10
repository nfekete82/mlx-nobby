# MLX Control Center – Arbeitskontext

## Architektur

- **MLX-Inferenz:** läuft nativ auf macOS/Apple Silicon über `mlx_lm.server` unter `http://127.0.0.1:8000`. MLX darf niemals in Docker verschoben werden.
- **macOS-Agent:** eigener FastAPI-Dienst unter `http://127.0.0.1:8010`; er ist die Bridge zwischen der Docker-Web-App und Host-Ressourcen bzw. MLX.
- **Web-App:** läuft ausschließlich in Docker/OrbStack und ist über `http://localhost:8090` erreichbar.
- **Docker → Host:** Die Web-App erreicht den Agenten über `host.docker.internal`.
- **MLX-Manager:** `~/bin/mlx` weiterhin als bestehende Verwaltungsoberfläche verwenden.
- **MLX-Konfiguration:** `~/.config/mlx-server/config`.
- **Modell-Aliase:** `~/.config/mlx-server/models`.
- **LaunchAgent:** `~/Library/LaunchAgents/de.nobby.mlx-server.plist`.
- **MLX-Server-Logs:** `~/.config/mlx-server/server.log` und `~/.config/mlx-server/server-error.log`.

## Produktumfang

Das Control Center umfasst Dashboard, Modellverwaltung, Hugging-Face-Cache, Downloads und Background Jobs, Thinking ON/OFF, Server Start/Stop/Restart/Reset, Systemmonitor, Log Viewer sowie einen separaten Webchat unter `/chat`.

## Verbindliche Regeln

1. Bestehende funktionierende Features nicht entfernen oder ohne Not neu schreiben.
2. MLX bleibt nativ auf macOS; Docker bleibt auf die Web-App beschränkt.
3. Der macOS-Agent bleibt die einzige Bridge von Docker zum Host.
4. Den vorhandenen Manager `~/bin/mlx` weiterverwenden.
5. Keine GitHub-Verbindung einrichten und keinen Push durchführen.
6. Keine Cloud-Abhängigkeiten hinzufügen, außer auf ausdrücklichen Wunsch.
7. Vor größeren Änderungen vorhandenen Code und APIs vollständig prüfen.
8. Nach Änderungen Syntax und betroffene API-Endpunkte testen.
9. Bei Änderungen am Web-Backend bei Bedarf `docker compose up -d --build` ausführen.
10. Funktionierende Konfigurationsdateien niemals blind überschreiben.
11. Aktionen außerhalb dieses Workspace vorher kurz begründen und nur mit passender Autorisierung ausführen.

## Arbeitsweise

- Änderungen klein, kompatibel und rückgängig machbar halten.
- Bei Host-bezogenen Funktionen Schnittstellen über den Agenten bevorzugen.
- Bestehende Backup-Dateien und lokale Laufzeitdaten respektieren; nicht ohne ausdrücklichen Auftrag löschen.
