# YouSpeed Web Inspector

## Dashcam zum Drive-Log

In **Karte & TSR** Drive-Log und TSR-Log laden, dann unter der Karte **Dashcam**
auswählen. Das Video bleibt lokal und wird als Blob-URL abgespielt; auch mehr als
4 GB werden nicht vollständig in JavaScript eingelesen.

- Klick auf Zeichen (Karte oder Liste) bzw. GPS-Fix springt zur Aufnahmezeit.
  Bei geladenem Video bringt ein Zeichenklick den passenden Frame in Sicht
  und setzt den Tastaturfokus auf das Video. Filteränderungen scrollen nicht.
  Der blaue Punkt folgt dem nächsten GPS-Fix innerhalb von zwei Sekunden.
- Kleine Tasten bieten ±5 Sekunden, ±1 Bild, Play/Pause und schrittweisen
  Rücklauf ohne Ton; Tempo ist zwischen 0,25× und 2× wählbar.
- Unter **Zeitabgleich / Bildrate** den UTC-Start kontrollieren. Die automatisch
  gelesene QuickTime-Erstellungszeit hat nur Sekundengenauigkeit und kann bei
  exportierten Videos ungeeignet sein. Manuelle ISO-Zeitstempel brauchen eine
  Zeitzone, etwa `2026-09-24T11:53:07Z`. Die Bildrate ist zunächst 30; Schritte
  sind nominelle 1/fps-Zeitsprünge, keine Garantie auf exakt einen dekodierten
  Frame bei variabler Bildrate.
- Alternative Zeitdatei: `{"schema":"youspeed-dashcam-alignment-v1","videoFile":"drive.mov","startUTC":"2026-09-24T11:53:07Z","frameRate":30,"source":"Geprüfter Aufnahmebeginn"}`.
  Der Dateiname muss zum ausgewählten Video passen.
- Außerhalb der Laufzeit wird das alte Bild ausgeblendet und die fehlende
  Abdeckung angezeigt. Keine Zuordnung zum ersten/letzten Frame durch Clamping.
- HEVC/MOV benötigt Decoder-Unterstützung des Browsers. Bei lokaler
  H.264-Konvertierung den ursprünglichen Zeitabgleich manuell übernehmen.
- Dateien nach einem Reload erneut auswählen. Eine Video-Auswahl ersetzt nur
  das vorherige Video, nicht die geladenen Logs.

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

## Verkehrszeichen entlang einer aufgezeichneten Fahrt

`http://localhost:8080/inspector/#track` öffnet **Karte & TSR**, ohne ein
SQLite-Bundle oder den Beispiel-Drive automatisch zu laden. Den Server wie oben
vom Repository-Root starten; die nationalen Piktogramme und Modell-Manifeste
werden von dort gelesen.

1. Unter **Drive-Log** die `*_drive_match_log.ndjson` der Fahrt öffnen.
2. Unter **Verkehrszeichen auf der Fahrt** die zugehörige
   `*_tsr_log.ndjson` öffnen. Beide Importe dürfen in beliebiger Reihenfolge
   erfolgen und können unabhängig ersetzt werden.
3. Auf ein Piktogramm oder einen Eintrag in der chronologischen Liste klicken.
   Die Karte zeigt die Fahrzeugposition; die Detailansicht zeigt Zeit, Land,
   Erkennungsscore, Kartenlimit, wirksames Limit, Drive-Status und Quellzeile.
   Gleichzeitig wird der entsprechende GPS-Fix im bestehenden Matcher ausgewählt.
4. Mit **Ereignisse** zwischen Detektionen, angewendeten Änderungen und
   abgelehnten Änderungen filtern. **Fahrt anzeigen** stellt die Übersicht wieder
   her; **TSR entfernen** entfernt die Zeichen, ohne den Drive zu löschen.

Orange Marker sind beobachtete Kandidaten (auch unterhalb der Erkennungsschwelle),
grüne Marker explizit protokollierte `passage_activation=applied`-Ereignisse,
rote Marker abgelehnte Aktivierungen. Aktivierungen sind separate Ereignisse:
Sie werden nicht anhand ähnlicher Zeiten einem vermeintlich identischen
physischen Schild zugeschrieben. `UNKNOWN` in der Applicability-Diagnose ist
kein Beleg für eine tatsächliche Ablehnung durch den aktiven Resolver.

Unterstützt werden die gemischten iPhone-Textlogs mit eingebetteten
`tsr_applicability_v1`-JSON-Frames, reine Diagnose-JSON/NDJSON-Dateien bzw.
`frames`-Arrays und Android-`tsr_applicability_v1`-Evidence-Envelopes. Ältere
Textlogs ohne Diagnose-Frames können ihre protokollierten numerischen
provisional/confirmed-Zustände darstellen; ein bestätigter Zustand gilt dabei
nicht automatisch als angewendet. Fehlerhafte Zeilen werden mit Zeilennummer
gezählt; identische doppelte Frames nur einmal verarbeitet.

Die Zuordnung verwendet den zeitlich nächsten gültigen GPS-Fix mit maximal
**2 Sekunden** Abstand, ohne interpolierte Koordinaten. Ereignisse ohne solchen
Fix bleiben in der Liste. Wiederholungen derselben Semantik werden innerhalb
von **3 Sekunden** je Land, Modell, Track und vollständigem Laufzeit-Scope zu
Sichtungsgruppen zusammengefasst. Diese Gruppierung behauptet keine physische
Schildidentität über Track-/Scope-Wechsel hinweg. Der Marker liegt beim ersten
Auftreten; der höchste Score und die Anzahl der Sichtungen stehen im Detail.

Das Land stammt aus dem Log bzw. der protokollierten Modell-Auswahl; ohne diese
Information kann es manuell ergänzt werden. Alle fünf Kataloge (DE, FR, BE, NL,
CH) verwenden die vorhandenen gemeinsamen PNG-Dateien unverändert. Ohne genaue
Klassen-ID wird nur eine eindeutige semantische Katalog-Zuordnung verwendet und
als **Symbol aus Semantik** gekennzeichnet. Fehlende/nicht eindeutige oder nicht
anzeigbare Klassen erhalten einen Platzhalter. Für Streckenlimit-Enden wird bei
fehlender Variante das nationale Endsymbol mit entsprechendem Hinweis gezeigt;
Zonenenden erhalten niemals ersatzweise dieses Symbol. Illustrative Ortsnamen
in den Piktogrammen sind keine aus dem Log erkannten Ortsnamen. Ältere Logs mit
`unknown::` ohne Klassen-ID können keine konkreten Warn-/Gebotszeichen belegen;
**Auch nicht identifizierbare Kandidaten** macht diese Einträge sichtbar.

Dateien bleiben im Browser und werden nicht hochgeladen oder gespeichert.
Die Kartenansicht lädt wie bisher OSM-Kacheln (sichtbarer Kartenausschnitt wird
an OSM übermittelt); `#tsr` bleibt ohne Kacheln, bis zur Karte gewechselt wird.
Private Fahrdaten gehören nicht in das Repository. Kein neuer Bundle-Build und
keine Änderung an der mobilen Erkennungs- oder Geschwindigkeitslogik ist nötig.

Tests: `node --test tests/inspector/*test.js`

### Sekundäre Verkehrszeichen

**Auch sekundäre Zeichen (z. B. Vorfahrt, Warnungen)** blendet zusätzlich
Kandidaten mit einer konkreten nationalen Klassen-ID und freigegebenem
Piktogramm in Karte und Liste ein. Die Option ist zunächst aus und unabhängig
von **Auch nicht identifizierbare Kandidaten**. Filter wie **Angewendet** gelten
weiterhin: Ein sekundärer Kandidat wird nicht als angewendetes Tempolimit
behandelt. Bezeichnungen stammen aus dem jeweiligen Länderkatalog.

Die optionalen `rawClassId`-Felder in neuen iPhone- und Android-
Applicability-Aufzeichnungen erhalten die Originalklasse auch bei
`semanticKey=unknown::` (keine Geschwindigkeitsemantik). Es handelt sich um
Detektionen, nicht um den Nachweis, dass das Zeichen im sekundären Feld der App
angezeigt wurde. Das Additivfeld ändert keine Erkennungs- oder Geschwindigkeits-
Entscheidung und benötigt keinen neuen Karten-Bundle.

Ältere Logs ohne diese Klassen-IDs können nicht rückwirkend konkrete sekundäre
Zeichen liefern. Der Inspector nennt die Anzahl solcher nicht identifizierbaren
Gruppen ausdrücklich; der Schalter erfindet dafür keine Piktogramme.

Neue Frames enthalten außerdem `batch.country` aus dem verwendeten Modell-Pack.
Damit funktioniert die nationale Zuordnung auch in Android-
`runtime_diagnostics.ndjson` und in Log-Ausschnitten ohne Lifecycle-Zeilen.
Das Feld hat Vorrang vor einem vorher protokollierten Modellwechsel.

### Häufigkeiten pro Zeichenklasse

**Zeichenstatistik · gesamtes TSR-Log** zählt pro Land und protokollierter
YOLO-/Klassifikator-Klasse. Das zugehörige Piktogramm stammt aus dem gemeinsamen
Länderkatalog. Die Tabelle ist standardmäßig nach **Vorkommen** absteigend
sortiert; **Einzeldetektionen** kann alternativ als Sortiermaß gewählt werden.

- **Vorkommen**: Anzahl der bereits gebildeten Sichtungsgruppen (gleiche Klasse,
  Land, Modell, Semantik und Track/Scope, höchstens 3 Sekunden zwischen Frames).
  Das ist keine garantierte Zahl physisch unterschiedlicher Schilder.
- **Einzeldetektionen**: Summe der Kandidaten in diesen Gruppen. Identische
  doppelte Frames werden bereits beim Import entfernt.
- Alle Detektionsgruppen zählen, auch unterhalb der Erkennungsschwelle, ohne
  GPS und bei ausgeschalteten sekundären Zeichen. Kartenfilter beeinflussen die
  Statistik nicht; angewendete/abgelehnte Aktivierungen zählen nicht zusätzlich.
- Alte Logs ohne Klassen-ID bekommen separat nach Land/Semantik gezählte
  **Klasse fehlt**-Zeilen. Eine Klasse wird nicht aus einem Piktogramm oder
  Tempowert abgeleitet. Auch diese Zeilen fließen in die ausgewiesene Summe ein.

Die Statistik benötigt nur das TSR-Log, keinen Drive-Log oder Karten-Bundle.
