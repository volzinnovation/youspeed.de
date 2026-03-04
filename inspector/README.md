# YouSpeed Web Inspector

Eigenständiges Browser-Tool zum visuellen Prüfen von Ways auf OSM-Karte gegen lokale YouSpeed-SQLite.

## Features

- Lädt eine lokale SQLite-Datenbank (URL oder Dateiauswahl).
- Standard-URL ist das Seed-Bundle: `/iphone/SpeedConsumerApp/karlsruhe-regbez_speeds.sqlite`.
- Zeigt ein Fadenkreuz im Kartenmittelpunkt.
- Identifiziert per Knopfdruck die Straße unter dem Fadenkreuz via `ways`/`way_geom`.
- Nimmt eine Way-ID an und zentriert auf deren Geometrie.
- Zeigt das aktuell geladene Bundle inkl. Metadaten (falls vorhanden).
- Liest die aktuelle Browser-Position (Geolocation).

## Starten

Vom Repo-Root starten (wichtig, damit der Default-Pfad auf die Seed-DB erreichbar ist):

```bash
cd /Users/raphaelvolz/Github/youspeed.de
python3 -m http.server 8080
```

Dann im Browser öffnen:

`http://localhost:8080/inspector/`

Hinweis: Geolocation benötigt einen sicheren Kontext (`https://` oder `localhost`).
