# Chatmodell oben links auswählen

In der Chat-Oberfläche ist der aktive Modellname oben links jetzt ein deutlich
erkennbarer Button mit Pfeil. Ein Klick zeigt alle registrierten Modell-Aliase
(z. B. verschiedene lokal registrierte Chatmodelle). Der aktive Eintrag
ist markiert. Bei laufender Generierung ist der Wechsel gesperrt.

## Vorgehen

1. Einen bestehenden oder neuen Chat öffnen.
2. Oben links auf den Modellnamen klicken.
3. Ein **bereits registriertes und verfügbares** Chatmodell auswählen.
4. Warten, bis das neu gewählte Modell im Header als bereit angezeigt wird.
5. Bei Bedarf kann ein vorhandener Systemprompt-Preset gewählt werden;
   der Modellwechsel setzt die Chat-Historie und den Prompt-Preset nicht zurück.

**Wichtig:** Das Modell wird aktuell für die gemeinsame Chat-Runtime
ausgewählt, nicht als separate geladene Instanz für jede Unterhaltung.
Der Mac hält weiterhin nur das jeweils aktive Chatmodell.
Die Wahl wird im persistenten `chat`-Rollenprofil gespeichert und
gilt damit bei folgenden normalen Chatnachrichten. Ein Wechsel über
das Header-Menü verändert **keine** Zuordnungen für `agent`,
`coding` oder `vision`. Andere Aufgaben mit expliziter Modellrolle
können die gemeinsame Runtime später ihrerseits umschalten; wenn der
normale Chat wieder dran ist, stellt die Chat-Rollensteuerung das
gewählte Chatmodell wieder her.

Die Auswahl **pro gespeicherter Unterhaltung** ist noch keine Funktion
dieses ersten Ausbauschritts; beim Wechsel zwischen Chatverläufen wird
der gewählte aktive Chatmodus beibehalten. Der Header zeigt jederzeit
das tatsächlich aktive Modell, nicht nur die gewünschte Rolle.

## Technisch

Der Header nutzt die bestehende `/api/mlx/aliases`-Liste und wechselt
jetzt über `POST /api/mlx/model/chat/{alias}`.
Das Agent-Ziel `POST /api/model/chat/{alias}` validiert das registrierte
Modell, führt das bestehende bewachte `switch_model_runtime` unter
`MODEL_RUNTIME_LOCK` aus, und speichert `roles["chat"] = alias`
**erst nach erfolgreichem Modellwechsel**.
Bei unregistriertem Modell, belegter Runtime oder fehlgeschlagenem
Start bleiben die Rollen unverändert. Die bisherige
`POST /api/mlx/model/{alias}`-Route für explizite vollständige
Modellwechsel bleibt erhalten.

Für den neuen Agent-Endpunkt muss nach `git pull` der Agent aktualisiert
werden (`./scripts/mlx agent restart`). Ist das Frontend noch über eine
ältere Docker-Image-Version erreichbar, muss außerdem die Weboberfläche
mit den neuen Assets bereitgestellt werden.
