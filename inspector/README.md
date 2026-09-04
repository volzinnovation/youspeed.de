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
- Bietet einen getrennten **TSR QA**-Arbeitsbereich für Recognition-Events,
  Model-Pack-Manifeste und freigegebene Diagnostic-Bundle-Ordner.
- Prüft Diagnostic Bundles lokal auf Basiskontrakt, Datenschutzfreigabe und
  SHA-256-Integrität, rendert PPM/JPEG/PNG-Bildbelege mit Prediction- und
  Annotationsboxen und zeigt den exakten Way-/Koordinaten-/Richtungskontext.
- Simuliert die transiente Live-Override-Eignung eines Events, ohne OSM- oder
  lokale Korrekturen zu verändern. Lokale QA-Entscheidungen werden getrennt
  vom Diagnostic-Bundle-Schema als JSON-Bericht exportiert. Der Bericht bindet
  die geprüften Manifest-/Event-Dateien per SHA-256 ein und hält den Stand der
  Vertrags-, Datenschutz-, Asset- und Provenienzprüfungen fest.

## TSR QA

Im Kopf des Inspectors auf `TSR QA` wechseln. Für einen echten Diagnose-Export
den gesamten Bundle-Ordner auswählen, nicht nur `manifest.json`, damit der
Browser die referenzierten Bilddateien lesen und hashen kann. Recognition
Events (`.json`, `.jsonl`, `.ndjson`) und ein Model-Pack-Manifest können separat
geladen werden.

Events, die nicht streng zu einem Sample passen (Zeit, Way, Koordinate,
Fahrtrichtung und Modellidentität), bleiben als eigene Einträge in der
Prüfliste sichtbar. So verschwinden fehlzugeordnete oder alleinstehende
Erkennungen nicht hinter der Sample-Zeitleiste.

Der Datenschutz-Preflight gleicht die Deklaration mit dem Inhalt ab:
`location_mode=none` erlaubt keinen Way-/Koordinatenkontext; `coarse` erlaubt
höchstens drei Koordinaten-Nachkommastellen, 15-Grad-Richtungen und keine
exakte Way-/Quellsignatur. Exakter Way-, Positions- und Richtungskontext muss
als `exact_local_encrypted` deklariert sein.

`Fixture laden` öffnet ausschließlich die synthetischen Vertrags-Fixtures aus
`shared/tsr/fixtures/`. Sie enthalten weder ein ausführbares Modell noch eine
Release-Freigabe. Der Inspector zeigt Model-Pack-Manifeste nur als QA-Eingabe;
er behauptet nie, dass dieses Modell auf einem Gerät aktiv ist.

Tastatur im TSR-Arbeitsbereich: `←`/`→` wechselt den Beleg, `1` markiert
plausibel, `2` als zu prüfen und `3` als zu verwerfen.

Die QA-Verarbeitung und Dateiimporte bleiben lokal im Browser. Beim direkten
Start mit `#tsr` werden noch keine OpenStreetMap-Kacheln geladen. Erst ein
bewusster Wechsel in den Map Matcher oder die Aktion `Way auf Karte prüfen
(OSM)` aktiviert den externen Kacheldienst. Vor dem Fokus auf eine exakte
Sample-Koordinate warnt der Inspector ausdrücklich vor der Übertragung der
Koordinatenumgebung und IP-Adresse.

## Annotierte Replay-Logs erzeugen

`scripts/iphone/collect_current_matcher_metrics.swift` schreibt standardmäßig annotierte NDJSON-Kopien nach:

`inspector/logs/replay_debug/`

Diese Dateien behalten die ursprünglichen Logzeilen und ergänzen pro Fix ein `replayDebug`-Objekt mit Replay-Ergebnis, Hindsight-Label und Fehlerklassifikation. Im Inspector können sie direkt per Dateiauswahl geladen werden.

## Starten

Vom Repo-Root starten (wichtig, damit der Default-Pfad auf die Seed-DB erreichbar ist):

```bash
cd /path/to/youspeed.de
python3 -m http.server 8080
```

Dann im Browser öffnen:

`http://localhost:8080/inspector/`

Hinweis: Geolocation benötigt einen sicheren Kontext (`https://` oder `localhost`).
