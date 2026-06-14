# YouSpeed Web Inspector

Eigenständiges Browser-Tool zum visuellen Prüfen von Ways auf OSM-Karte gegen lokale YouSpeed-SQLite.

## Features

- Lädt eine lokale SQLite-Datenbank (URL oder Dateiauswahl).
- Standard-URL ist das Seed-Bundle: `/iphone/SpeedConsumerApp/karlsruhe-regbez_speeds.sqlite`.
- Zeigt ein Fadenkreuz im Kartenmittelpunkt.
- Identifiziert per Knopfdruck die Straße unter dem Fadenkreuz via `ways`/`way_geom`.
- Nimmt eine Way-ID an und zentriert auf deren Geometrie.
- Visualisiert Tunnel-/Motorway-Ein- und Ausstiege als Portalpunkte sowie zugehörige Inside-/Outside-Ways aus `corridor_progress` und `corridor_pairs`.
- Zeigt das aktuell geladene Bundle inkl. Metadaten (falls vorhanden).
- Liest die aktuelle Browser-Position (Geolocation).
- Liest auch annotierte Replay-/Benchmark-Logs mit `replayDebug`-Feld und markiert Replay-Abweichungen, Hindsight-Fehler und Replay-Korrekturen direkt im Fix-Inspector.

## Annotierte Replay-Logs erzeugen

`scripts/iphone/collect_current_matcher_metrics.swift` schreibt standardmäßig annotierte NDJSON-Kopien nach:

`/Users/raphaelvolz/Github/youspeed.de/inspector/logs/replay_debug/`

Diese Dateien behalten die ursprünglichen Logzeilen und ergänzen pro Fix ein `replayDebug`-Objekt mit Replay-Ergebnis, Hindsight-Label und Fehlerklassifikation. Im Inspector können sie direkt per Dateiauswahl geladen werden.

## Starten

Vom Repo-Root starten (wichtig, damit der Default-Pfad auf die Seed-DB erreichbar ist):

```bash
cd /Users/raphaelvolz/Github/youspeed.de
python3 -m http.server 8080
```

Dann im Browser öffnen:

`http://localhost:8080/inspector/`

Hinweis: Geolocation benötigt einen sicheren Kontext (`https://` oder `localhost`).
