# MLX Nobby – Medien-Anonymmodus und Same-Origin-Schutz

## Anonymmodus

In **Einstellungen → Chat-Verhalten** den Schalter **„Anonymmodus für
Bilder und Videos“** aktivieren. Alternativ das durchgestrichene Auge oben
in der Chat-Kopfzeile anklicken. Beide Schalter sind synchron.

- Bilder, generierte Videos, Chat-Medien, Varianten, Galeriekacheln,
  Medienbibliothek und die große Bild-/Videovorschau sind zunächst
  deutlich weichgezeichnet.
- Maus über dem Medium: temporär scharf; beim Verlassen wieder unscharf.
- Tastaturfokus kann Medien ebenfalls sichtbar machen.
- Touch: erstes Tippen deckt das Medium auf, zweites Tippen öffnet die
  Vorschau bzw. startet die normale Aktion. Tippen außerhalb blendet
  aufgedeckte Medien wieder aus.
- Die Einstellung wird im Browser unter
  \`mlx.mediaPrivacy.enabled.v1\` gespeichert und beim Laden VOR dem
  Anzeigen von Bildern angewendet.
- Es handelt sich **nur um einen optischen Sichtschutz**, nicht um
  Verschlüsselung oder eine Zugriffssperre. Download, Bilddateien,
  Netzwerk-/Browsercache und die lokale Medienbibliothek bleiben erhalten.
  Für echte Geheimhaltung Gerät/Betriebssystem und Datenzugriff schützen.

## HTTP 403: „Nur lokale Zugriffe vom selben Ursprung sind erlaubt“

Der LocalRequestGuard verhindert DNS-Rebinding und fremde Origins.
Anonyme Medien dürfen diese Prüfung **nicht** deaktivieren.

Eine häufige lokale Ursache ist die Mischung von
\`http://localhost:8091\` und \`http://127.0.0.1:8091\`. Die
geprüfte Ausnahme erlaubt jetzt genau diese *literalen Loopback-Namen*,
wenn Browser und Backend denselben HTTP-Port nutzen. Externe Websites,
fremde Ports und beliebige LAN/Tailscale-Hosts bleiben gesperrt.

### Bei der Docker-Vorschau (Port 8091)

Öffne die Vorschau im Browser unter
\`http://127.0.0.1:8091/chat\` und verwende relative API-Pfade wie
\`fetch('/api/mlx/…')\`. Bei einem selbst gewählten privaten
DNS-/Tailnet-Namen muss dessen Hostname **explizit** freigegeben werden:

\`\`\`bash
MLX_ALLOWED_HOSTS='localhost,127.0.0.1,::1,mein-mac.example.ts.net'
\`\`\`

Bei \`docker compose\` muss die Variable in der Umgebung des Compose-
Prozesses gesetzt und der Webcontainer neu erstellt werden; ein bloßes
\`export\` bei laufendem Container ändert dessen Umgebung nicht. Die
\`docker-compose.yml\` leitet \`MLX_ALLOWED_HOSTS\` schon weiter.

Für die isolierte Office-Vorschau mit \`docker run\` bei Bedarf
\`-e MLX_ALLOWED_HOSTS="$MLX_ALLOWED_HOSTS"\` ergänzen.

**Nicht**: \`MLX_ALLOWED_HOSTS=*\`, beliebige private Netze oder
\`Access-Control-Allow-Origin: *\` – das wäre in diesem lokalen Dienst
ein unnötiges Sicherheitsrisiko. Tailscale Serve sollte Host und
Origin korrekt weitergeben. Auf Port 8090 bleibt die lokale
\`127.0.0.1\`-Bindung bestehen.
