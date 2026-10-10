# YouSpeed Web Inspector

## Gespeicherte Backend-Crops (volz-db / VPN)

**Backend-Crops** (`/inspector/#crops`) zeigt die gespeicherten PNG-/JPEG-Bytes,
Zeichenklasse, Scores, Aufnahmezeit, App, Crop-Geometrie und zugehörige Beobachtung.
Die Details zeigen Fahrzeugposition, GPS-Kurs, Kurs-/Positionsgenauigkeit,
GPS-Fixzeit und den vorzeichenbehafteten Frame/Fix-Zeitabstand. Neue Crops nutzen
ihre eigene `vehicle_position`; ältere Crops ohne dieses Feld zeigen ausdrücklich
die Position der Beobachtung. Ein expliziter Nullwert übernimmt keine ältere
Position oder Fahrtrichtung. GPS-Kurs beschreibt die Fahrtrichtung, nicht die
kalibrierte Kameraausrichtung.
Die orange Box markiert das ursprüngliche Zeichen innerhalb des erweiterten
Ausschnitts. Filter: Gerät (Installations-ID), Land, Erfassungsart,
Klasse/Crop-/Beobachtungs-ID und UTC-Zeitraum. Die Geräteauswahl enthält alle
aktiven Crop-Quellen, unabhängig von der aktuellen Ergebnisseite, mit Plattform
und Crop-Anzahl. Jede Karte und die Detailansicht zeigen die Installations-ID.
Sie bleibt bei App-Updates erhalten; eine Neuinstallation kann eine neue ID
erzeugen. Es handelt sich nicht um eine Hardware-ID.
Die Liste lädt 50 Einträge pro Seite, neueste Aufnahmen zuerst.
Die Koordinaten unter **Fahrzeugposition** sind ein Link: ein Klick öffnet den
Map Matcher mit Positionsmarker; „In neuem Tab öffnen“ zeigt dieselbe Position
in einer separaten Inspector-Karte. Fehlende oder ungültige Koordinaten bleiben
ohne Link.

Dieser Modus benötigt den mitgelieferten Python-Server statt `http.server`:

```sh
python3 -m venv /tmp/youspeed-inspector-venv
/tmp/youspeed-inspector-venv/bin/python -m pip install -r inspector/requirements.txt
/tmp/youspeed-inspector-venv/bin/python inspector/server.py
```

Der Standardbenutzer ist **`youspeed_report`**, die Datenbank **`youspeed`**.
Es gibt keinen Browser-Login: ausschließlich der Server verwendet die bereits
eingerichteten Report-Zugangsdaten. Er sucht zuerst `YOUSPEED_DATABASE_URL_FILE`,
dann `/srv/woladen/config/youspeed/database-report.txt`,
`/run/secrets/youspeed/database.txt` und die vorhandene lokale Datei im
Geschwister-Repository `Woladen.de-analytics/secret/youspeed/database-report.txt`.
Die Datei muss privat sein (0600). Alternativ unterstützt der Server libpq-
Zugangsdaten (`PGHOST`, `PGPORT`, `PGPASSFILE`/`.pgpass`) und
`YOUSPEED_DATABASE_URL`. Ohne Datei/Hostkonfiguration ist der Host `volz-db`.
`--database-file`, `--db-host`, `--db-port` und `--db-user` erlauben explizite
Overrides. Passwörter gehören ausschließlich in private Dateien/Umgebungen.

Direkt **auf volz-db** mit erreichbarem privaten PostgreSQL-Endpunkt starten:

```sh
YOUSPEED_DATABASE_URL_FILE=/srv/woladen/config/youspeed/database-report.txt \
YOUSPEED_MANAGEMENT_MEDIA_ROOT=/path/to/read-only/management-media \
python3 inspector/server.py --bind PRIVATE_VPN_IP --allowed-host volz-db:8080
```

Dann über die VPN-Verbindung `http://volz-db:8080/inspector/#crops` öffnen.
volz-db hat die Adresse **141.47.91.52**. Falls der Kurzname im VPN nicht
aufgelöst wird, direkt `http://141.47.91.52:8080/inspector/#crops` öffnen;
beide Browser-Hostnamen sind bereits zugelassen. `--bind 141.47.91.52` bindet
an diese Serveradresse; Listener/Firewall müssen auf das genehmigte private
VPN-Netz beschränkt bleiben.
`PRIVATE_VPN_IP` muss die tatsächliche private Serveradresse sein. Der Default
bindet nur an `127.0.0.1`; es wird kein öffentlicher Listener eingerichtet.
Bei einem Reverse Proxy den genauen Inspector-Host inklusive Port mit
`--allowed-host` zulassen. Der Proxy muss ebenfalls auf das private Netz
beschränkt sein. Daten- und Bildantworten sind same-origin und `no-store`.

PostgreSQL und Bildablage sind getrennt: `YOUSPEED_MANAGEMENT_MEDIA_ROOT` muss
das **Management-Medienverzeichnis** bzw. seinen nur lesbaren Mount bezeichnen.
Der Backend-Container verwendet `/var/lib/woladen/youspeed-management-media`
(Compose-Volume `youspeed_management_media`). Der Server erstellt oder verändert
dieses Verzeichnis nicht. Mit passender Dateileseberechtigung ausführen; der
Backend-Dienst verwendet UID/GID 10001 und private Bilddateien (0600).
Der Container-DNS-Name `panoramax-backend-db-1` in der Produktions-DSN ist nur im
zugehörigen Docker-Netz erreichbar. Auf dem Host den bestätigten privaten
PostgreSQL-Endpunkt per `--db-host` wählen oder den Inspector mit dem bestehenden
Datenbanknetz und einem nur lesbaren Medienmount betreiben. Kein DB-Port muss
öffentlich geöffnet werden.

Die bisherige Report-Rolle darf `media` und die Lifecycle-Kontrolltabellen noch
nicht lesen. Ein Administrator muss nach Prüfung einmal
[`report-crops-grants.sql`](report-crops-grants.sql) in **youspeed** anwenden.
Das ergänzt ausschließlich SELECT auf `media`, `tombstones`, `authorizations`;
die vorhandenen SELECT-Rechte auf `events` werden weiterhin benötigt.
Das Backend-Grants-Skript entzieht Rechte vor seiner Neuvergabe; nach dessen
erneuter Anwendung diesen Inspector-Zusatz ebenfalls erneut anwenden.
Der Inspector führt selbst keine Grants/Migrationen aus. Die SQL-Verbindungen
und Transaktionen sind read-only. Listen- und Bildabfragen schließen abgelaufene,
gelöschte und ausdrücklich widerrufene Crops aus. Bilder werden bei jedem Abruf
erneut geprüft (Größe, SHA-256, Format, sicherer Dateipfad).

Für lokale Entwicklung mit bereits eingerichteter privater DB-Weiterleitung
kann die vorhandene Report-Datei weiter verwendet werden. Eine DB-Verbindung
allein transportiert keine Bilder: dafür ist ein nur lesbarer Medienmount oder
der direkt auf volz-db laufende Inspector nötig. VPN-/Tunnel-/Rechtefehler werden
in der Ansicht angezeigt; Zugangsdaten erscheinen weder im Browser noch in
Fehlermeldungen/Access-Logs.

Tests: `python3 -m unittest discover -s tests/inspector -p 'test_backend_crops.py'`
und `node --test tests/inspector/*.test.js`.

### Installation mit dem vorhandenen Backend-Image und SSH-Tunnel

`python3 scripts/inspector/package.py` erzeugt ein Paket mit Hash-Manifest in
der temporären Ablage. Es enthält ausschließlich Inspector-Code, synthetische
QA-Fixtures und gemeinsame Anzeigeassets, keine Zugangsdaten oder Drive-Logs.
Das Paket privat nach volz-db kopieren, SHA-256 prüfen und in einen eigenen
Staging-Ordner entpacken. Dort mit Administratorrechten ausführen:

```sh
sudo python3 scripts/inspector/install-volz-db.py
```

Der Installer prüft alle Paketbytes, verwendet das bereits laufende Reports-
Image unverändert und bindet dessen vorhandenes privates DB-Netz und Report-
Publikationsnetz an. Der neue Container `youspeed-inspector` läuft als UID/GID
10001, mit read-only Dateisystem, Report-Datei und Medienvolume. Er veröffentlicht
ausschließlich **127.0.0.1:8080** und startet nach einem Docker-Neustart wieder.
Vorhandene Backend-Container werden nicht ersetzt. Der Installer ergänzt die
benötigten SELECT-Grants und prüft Report-Identität, Galerie und, falls vorhanden,
die Bytes eines gespeicherten Crops. Ein vorhandener Inspector wird nicht
automatisch überschrieben.

Auf dem Mac den Tunnel starten und offen lassen:

```sh
ssh -i ~/.ssh/id_ed25519 -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:18080:127.0.0.1:8080 raphael@141.47.91.52
```

Danach `http://localhost:18080/inspector/#crops` öffnen. Die Standardports sind
bereits in der Host-Prüfung zugelassen; alternative Ports beim Installer über
`--port` und `--local-port` angeben.

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

### Spur- und Fahrpfad-Diagnose

Unter dem Video kann ein Log mit `tsr_path_evidence_v1` geladen werden; beim
TSR-Import werden diese Ereignisse automatisch übernommen. Android-NDJSON mit
`event: "tsr_path_evidence_v1"` und `evidence` (JSON-String; auch verschachtelt unter `details` akzeptiert) sowie
iPhone-Textzeilen mit `tsr_path_evidence_v1={...}` werden unterstützt.

1. UTC-Videostart unter **Zeitabgleich / Bildrate** prüfen. Optional den
   **Logversatz (ms)** einstellen; positive Werte wählen spätere Logzeiten.
2. Die passende **Kamerageometrie** wählen und bestätigen, dass Zeit und
   Bildausschnitt übereinstimmen. Gleiche Seitenverhältnisse allein beweisen
   keinen identischen Zuschnitt. Die Bestätigung wird bei Video-, Geometrie-,
   Startzeit- oder Offsetwechsel zurückgesetzt.
3. Gelbe Linien zeigen mögliche Markierungen, graue gestrichelte Linien reine
   Kanten. Konfidenz und unbestimmte Pfadhypothesen bleiben sichtbar. Zeichenboxen
   tragen die geloggte Zuordnung (`unknown` bleibt unbekannt). Eine vorhandene
   projizierte Trajektorie wird cyan gestrichelt gezeichnet. Weltkoordinaten
   werden nicht ohne Projektion in das Kamerabild eingezeichnet.
4. **Frame, Unsicherheit und Laufzeit** enthält Belichtungszeit, Frame-ID,
   Kalibrierung, Fahrzeugversatz, Trajektorie, Laufzeiten und Zuordnungsgründe.

Es wird nur ein Frame innerhalb von **80 ms** zur abgeglichenen Videozeit
gezeigt, ohne Vorhersage oder Übernahme älterer guter Geometrie. Fehlende
Belichtungsuhr, Deadline, Geometrie-/Formatwechsel, beschädigte Geometrie und
widersprüchliche Duplikate blenden das Overlay aus. Zwischen seltenen
Analyseframes bleibt es daher bewusst leer. Browser mit
`requestVideoFrameCallback` verwenden die tatsächlich präsentierte Medienzeit.

`tsr_path_recording_v1` liefert mit `timingQuality: "callback_anchor_estimated"`
nur geschätzte Start-/Stop-/Fortschrittsanker. Diese werden niemals als genaue
Video-PTS behandelt. Eine automatische Zuordnung ist erst für ausdrücklich
verifizierte, dateigebundene `dashcam`-Daten mit `videoFile`,
`videoTimeSeconds`, `geometryId` und `timingQuality: "exposure_pts_verified"`
vorgesehen. Die aktuellen nativen Aufnahme-Callbacks liefern diese Garantie
nicht; deshalb bleibt der manuelle Zeitabgleich erforderlich.

Die Darstellung verwendet ausschließlich geloggte Evidenz und führt keine
neue Erkennung aus. Sie belegt keine rechtliche Gültigkeit eines Zeichens.
Tests: `node --test tests/inspector/*.test.js`.

Eigenständiges Browser-Tool zum visuellen Prüfen von Ways auf OSM-Karte gegen lokale YouSpeed-SQLite.

Die Hintergrundkarte verwendet **Stadia Maps Alidade Smooth**, über den
EU-Endpunkt `https://tiles-eu.stadiamaps.com/tiles/alidade_smooth/{z}/{x}/{y}{r}.png`.
Stadia Maps, OpenMapTiles und OpenStreetMap werden auf der Karte attribuiert.
[Lokale Entwicklung](https://docs.stadiamaps.com/authentication/) unter
`localhost` oder `127.0.0.1` benötigt keinen API-Key, unterliegt aber Rate-Limits.
Andere Hosts (auch VPN-/Intranet-Hosts) benötigen eine passende Stadia-
Authentifizierung. Der lokale SSH-Tunnel unter `localhost:18080` kann direkt
verwendet werden. Nur Kachelbilder verwenden `referrerPolicy: "origin"`, damit
Stadia den lokalen Zugriff erkennt; Pfade, Suchparameter und Crop-Metadaten
werden dabei nicht als Referrer übertragen. Der sichtbare Kartenausschnitt und
die IP-Adresse werden an Stadia übertragen. Es gibt keinen Kachel-Prefetch.

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
Start mit `#tsr` werden noch keine Stadia-Maps-Kacheln geladen. Erst ein
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
Die Kartenansicht lädt Stadia-Maps-Kacheln (sichtbarer Kartenausschnitt wird
an Stadia übermittelt); `#tsr` bleibt ohne Kacheln, bis zur Karte gewechselt wird.
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

### Datenbank-Report pro gespeicherter Zeichenklasse

`scripts/inspector/sign_statistics.py` liest mit `youspeed_report` und dessen
vorhandener privater Passwort-/DSN-Datei dieselben Zugangsdaten wie der Inspector.
Der Report gruppiert nach Land und Zeichenklasse und zählt **alle gespeicherten Crops**, einschließlich noch gespeicherter
inaktiver/abgelaufener Einträge und Replay-Installationen. Die Klasse ist
`model_label`, ersatzweise `canonical_code`, sonst `(unclassified)`.
Die separate Spalte `country` übernimmt `classification.country`; fehlende Länder
erscheinen als `unknown`. Das ist die protokollierte Modelldomäne, kein geprüftes
Fahrtland. Gleiche Klassen verschiedener Länder erhalten getrennte Zeilen.
Mehrere Crops einer Sichtung zählen einzeln; die zusätzliche Spalte
`linked_sightings` zählt unterschiedliche verknüpfte Sichtungsidentitäten.
Diese gespeicherten Labels sind keine geprüfte Klassifikation und keine Zahl
physisch unterschiedlicher Schilder.

```sh
python3 scripts/inspector/sign_statistics.py --output-dir /tmp/youspeed-sign-statistics
```

Benötigt `inspector/requirements.txt`. Gibt eine Markdown-Tabelle auf stdout aus
und ersetzt lokal `sign-statistics.csv`, `sign-statistics.json` und
`sign-statistics.md`, jeweils nach Crop-Anzahl absteigend und bei Gleichstand
nach Land und Klassenname sortiert. JSON und Markdown enthalten den UTC-Snapshotzeitpunkt
und die Zähldefinition. Ohne `--output-dir` wird ein Unterordner
`youspeed-sign-statistics` im temporären Systemverzeichnis verwendet.
Alle Abfragen laufen in einer Read-only-/Repeatable-read-Transaktion; die Summe
der Klassen wird gegen die Gesamtzahl derselben Momentaufnahme geprüft.
`--database-file`, `--db-host` und `--db-port` unterstützen vorhandene private
Verbindungen/Tunnel. Der Report enthält keine Passwörter, Geräte-IDs oder GPS-Daten.
Es gibt keine automatische Veröffentlichung auf einem Server.

## Spurannotation für Lane-Detection-Datasets

Mit installiertem **FFmpeg und ffprobe** den lokalen Server starten:

```sh
python3 inspector/server.py --port 8080
```

`http://127.0.0.1:8080/inspector/` öffnen, unter **Dashcam** ein Video auswählen
und **Video annotieren** anklicken. Es gibt keinen Opt-in-Schalter für den
Decoder: der lokale Server aktiviert ihn automatisch, wenn FFmpeg startfähig
ist. SQLite, Drive-Log und TSR-Log sind zum Annotieren nicht erforderlich.
MOV/MP4, MKV, AVI und MPEG-TS werden unterstützt. Die Decoder-Endpunkte sind
nur auf Loopback verfügbar; die private volz-db-Galerie bleibt unverändert.
Ein statischer `http.server` bietet keine Frame-Dekodierung.

Der Browser überträgt die ausgewählte Datei als Datei-Body an den **lokalen**
Server, ohne sie komplett in JavaScript einzulesen. Der Server speichert eine
temporäre Kopie, hasht sie und indexiert die tatsächlich dekodierten Frames.
Bis 16 GiB pro Video, eine Million Frames und 36 Megapixel pro Frame; ausreichend
freier temporärer Speicher ist erforderlich. Indexierung großer Videos kann
dauern. Originaldateien werden nicht verändert. Die Videositzung wird beim
Entfernen/Wechseln des Videos und beim Schließen der Seite freigegeben;
liegengebliebene Sitzungen werden nach zwei Stunden beim nächsten Upload
bereinigt, alle temporären Daten beim Serverende. Bis zu vier Sitzungen sind
parallel möglich.

### Bearbeitung Frame für Frame

- **‹ Bild / Bild ›**, **← / →** im Editor oder die Frame-Nummer wechseln zwischen
  tatsächlichen dekodierten Frames. Frame-Nummern sind nullbasiert; der Zähler
  zeigt zusätzlich Position, Medienzeit und originalen PTS. Im Annotationsmodus
  ersetzen PNGs die Videoansicht. Nominale FPS werden dabei nicht verwendet.
- **Neue Kurve · 4 Punkte**: Startpunkt, zwei Kontrollpunkte und Endpunkt setzen.
  Es entsteht eine kubische Bézier-Kurve. Mehrere Markierungen sind unabhängig
  möglich. Kurve oder Kontrollpunkt anklicken, Punkte ziehen, Markierung als
  **Durchgezogen / Gestrichelt** einstellen. **Esc** bricht eine neue Kurve ab.
  **Entf**, **Rückgängig / Wiederholen** und **⌘/Ctrl+Z / Shift+⌘/Ctrl+Z** bearbeiten
  den aktuellen Frame. Undo/Redo wird pro Frame für die laufende Sitzung gehalten.
- **Vorherige Annotation als Entwurf** übernimmt die jüngste frühere Annotation
  desselben Videos; unter **Vorlage** kann ein anderer früherer Frame gewählt
  werden. Die Geometrie wird unabhängig kopiert, Track-IDs und Markierungsattribute
  bleiben erhalten. Aktuelle Arbeit wird nicht überschrieben: zuerst explizit
  **Frame leeren**, falls eine andere Vorlage gewünscht ist.
- **Track verknüpfen** ordnet eine Kurve derselben physischen Markierung in
  anderen Frames zu. **Neuer Track / Verbindung lösen** beginnt eine neue
  Identität. Pro Frame ist höchstens eine Kurve eines Tracks erlaubt. Eine
  verschwundene Markierung im nächsten Frame entfernen; ihre früheren Instanzen
  bleiben erhalten. Sichtbare Track-Spannen ergeben sich aus den vorhandenen
  Frame-Instanzen, ohne automatische Links aufgrund von links/rechts oder
  Kurvenreihenfolge.
- **Frame geprüft bestätigen** gibt die Annotation zur Nutzung frei, auch für
  einen Frame ohne sichtbare Markierungen. Neue Frames und kopierte oder erneut
  bearbeitete Annotationen sind **Entwürfe**. Jede Geometrie-, Attribut- oder
  Trackänderung setzt den Frame wieder auf Entwurf.
- **Drive-Gruppe / Split** bestimmt die gemeinsame Fahrtidentität und den
  Trainings-/Validierungs-/Test-Split. Clips derselben Fahrt **vor dem Export**
  derselben Gruppe zuordnen. Die Splitänderung gilt für sämtliche Quellen der
  Gruppe, damit benachbarte Frames und Clips nicht in mehreren Splits liegen.
  Standardgruppe ist die Video-SHA-256; FNV-1a über die Gruppen-ID modulo 10
  wählt standardmäßig 80/10/10. Das ist eine deterministische Gruppenzuordnung,
  keine Garantie für ausgeglichene kleine Datasets. Splitzuordnungen können
  bewusst geändert werden.

Geometrie bleibt bei Zoom, Resize und Letterboxing am dekodierten Bild gebunden.
Gestrichelte Kurven beschreiben den Verlauf **einer Markierung einschließlich
sichtbarer Lücken**; die dekorativen Striche entsprechen nicht den einzelnen
Lacksegmenten. v1 erzeugt deshalb Polylinien mit Markierungsklassen, keine
Pixelmasken und keine erfundenen Gap-Labels.

Annotationen und die angezeigten PNGs werden in IndexedDB lokal gesichert.
Beim Wiederöffnen können **Gespeicherte Frames** ohne Originalvideo bearbeitet
werden. Für weitere Frames das ursprüngliche Video erneut auswählen und
indexieren; SHA-256 und vollständiger Frame-Index müssen übereinstimmen.
Speicher-/Quotafehler erscheinen im Status. **Dataset exportieren (.zip)** ist
die portable Sicherung; **Dataset importieren** prüft Vertrag, Splits,
CRC32, PNG-Abmessungen und SHA-256, bevor das vorhandene Dataset ersetzt wird.
Import und Export funktionieren auch ohne ausgewähltes Video.
**Neues Dataset** beginnt nach expliziter Bestätigung einen neuen Bestand und
ersetzt die lokale Sicherung; bestehende Arbeit vorher als ZIP exportieren.

### Speichervertrag `youspeed-lane-dataset-v1`

Das ZIP verwendet unkomprimiertes STORE, UTF-8-Dateinamen und CRC32; PNGs sind
bereits komprimiert. Es enthält `manifest.json`, `images/<sample-id>.png` und
`splits/{train,validation,test}.json`. Grenze: 4 GiB oder 65.535 Dateien je ZIP;
größere Bestände in mehrere Datasets aufteilen. Die Originalvideos werden nicht
in das ZIP kopiert. Alle besuchten Frames bleiben im Manifest, auch leere
Entwürfe; nur **reviewed**-Samples erscheinen in den drei Split-Listen.

Der ausführbare Vertragsvalidator ist `lane-annotations-core.js::validate`:

| Feld | Bedeutung |
| --- | --- |
| `schema`, `id`, `coordinateConvention`, `curveSemantics` | Version, Dataset-ID, normalisierte Pixelzentrum-Koordinaten von links oben, Markierungspfad-Semantik |
| `sources[]` | Video-SHA-256/ID, Name, Byte-Länge, Drive-Gruppe, Split, Sequence-ID, dekodierte Bildgröße, ursprüngliche Rotation und vollständiger Frame-Index |
| `sources[].timeBase`, `startPts`, `frames[]` | Originale rationale PTS-Zeitbasis; PTS als Dezimalstrings; Index und Zeit in Sekunden relativ zum ersten dekodierten Frame |
| `samples[]` | ID `<source-sha256>-<frame-index>`, Quell-/Sequence-ID, exakter Frame/PTS/Zeit, Bildgröße, PNG-Pfad/Länge/SHA-256 |
| `status`, `revision`, `reviewedAt`, `updatedAt` | `draft` oder `reviewed`, monoton steigende Frame-Revision und Bearbeitungs-/Reviewzeit |
| `draftFrom` | Quell-Sample-ID und Quellrevision der übernommenen Vorlage, oder `null` |
| `curves[]` | Eigene Annotations-ID, dauerhafte Track-ID, `degree: 3`, vier `[x,y]`-Kontrollpunkte in `[0,1]`, `marking: solid\|dashed`, Kopierprovenienz |
| `curves[].copiedFrom` | Ursprüngliche Sample-/Annotations-ID und Quellrevision, oder `null`; bleibt nach unabhängigen Änderungen nachvollziehbar |

`(0,0)` ist das obere linke, `(1,1)` das untere rechte Pixelzentrum des
vollständigen PNGs. FFmpeg-Autorotation ist bereits angewendet; `transform` ist
`ffmpeg_autorotate_full_frame`. Keine Vorschau-Crops, kein Letterboxing und
keine Zoomtransformation werden im PNG gespeichert. PTS stammt vom Decoder,
nicht von einer geschätzten Browser-Seekposition. Doppelte/nicht aufsteigende
PTS, Geometriewechsel oder eine nicht unterstützte Ausrichtung führen zum
Fehler, statt ein anderes Frame-Bild als Annotationsträger zu verwenden.

### Nutzung für Training, Test und Evaluation

Der dependency-freie Node-Loader prüft denselben Vertrag wie der Browser,
prüft sämtliche Split-Listen und Bildbytes und gibt für jeden Frame Bild,
Track-IDs, Klassen und deterministisch abgetastete Polylinien aus:

```sh
node scripts/inspector/lane_dataset_loader.mjs /path/to/dataset.zip \
  --split train --points 65 --output /path/to/training
node scripts/inspector/lane_dataset_loader.mjs /path/to/dataset.zip \
  --split validation --output /path/to/validation
node scripts/inspector/lane_dataset_loader.mjs /path/to/dataset.zip \
  --split test --output /path/to/test
```

Jedes Ausgabeziel enthält `images/` und `labels.jsonl`; Originalvideos sind
nicht erforderlich. Ein extrahiertes Dataset-Verzeichnis wird ebenfalls
unterstützt. Ohne `--output` wird JSONL nach stdout geschrieben. Entwürfe werden
nur mit ausdrücklichem `--include-drafts` geladen und tragen ihren Status.
Programmatic API: `loadDataset(input, {split, points, includeDrafts})` aus der
`.mjs`-Datei; Ergebnisse enthalten zusätzlich `imageBytes` als Node-Buffer.

Klassen: `solid = 0`, `dashed = 1`. Für N Punkte wird die kubische Kurve bei
`t=i/(N-1)` ausgewertet und nach `x*(width-1), y*(height-1)` in Pixelkoordinaten
transformiert. Keine Resize-/Croptransformation wird implizit angewendet. Für
Modelle mit anderer Eingabegröße dieselbe explizite affine Transformation auf
Bild und Punkte anwenden; keine erneute Autorotation. Leere geprüfte Frames
liefern eine leere Kurvenliste und können als negative Beispiele genutzt werden.

Das kleine synthetische Beispiel unter `tests/inspector/fixtures/lane-dataset-v1/`
enthält für jeden Split zwei geprüfte Frames (Markierungen und leerer Frame),
einen kopierten Entwurf sowie die drei winzigen Quellvideos zum Wiederöffnen.
Es enthält keine echten Fahrten und ist kein Genauigkeitsnachweis. Regenerieren:

```sh
python3 scripts/inspector/make_lane_example.py
```

Tests: `node --test tests/inspector/*.test.js` und
`python3 -m unittest discover -s tests/inspector -p 'test_*.py'`.
Die Decodertests benötigen FFmpeg/ffprobe und vergleichen echte synthetische
VFR-/B-Frame-, Rotations- und PTS-Offset-Frames bytegenau mit vollständiger
FFmpeg-Dekodierung.
