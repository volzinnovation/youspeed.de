# KI für intelligente Mobilität

**Profilprojekt IMo WS27-28 HSPF**  
**Prof. Dr. Raphael Volz**  
Begleitmaterial zur Einführung am 19. Oktober 2026 · 42 Folien · 90 Minuten

Vier Teams bearbeiten zwei Themen: **A1 und A2 verbessern die Erkennung von Ortstafeln**, **B1 und B2 verbessern die Spurerkennung**. Beide Projekte beginnen mit eigenen Aufnahmen und sorgfältig geprüften menschlichen Annotationen. Anschließend folgen überwachtes Lernen, unabhängige Evaluation und ein überprüfbarer Modellkandidat.

## Termine und gemeinsame Abstimmung

| Termin | Anlass |
| --- | --- |
| 19.10.2026 | Projekt Kick-Off |
| Montags 11:30–13:00 | Status Standup + Fragen |
| 21.12.2026 | Projektabschluss |
| 11.1.2027 | Interne Präsentation |
| 18.1.2027 | Öffentliche Präsentation (WI-TAG) |

## 1. YouSpeed und das Projektziel

[YouSpeed.de](https://youspeed.de/) verbindet offene Geodaten mit Kameraerkennung auf dem Smartphone. Die Apps für iPhone und Android nutzen drei Informationsquellen. Für diese Lehrveranstaltung gilt die vom Projektverantwortlichen vorgegebene Reihenfolge:

1. **Nutzerkorrekturen:** bewusst gesprochene Korrekturen; iPhone verwendet Apple Speech, Android die gebündelte Vosk-Spracherkennung.
2. **Kamera und Vision:** erkannte und der eigenen Fahrt zugeordnete Verkehrszeichen.
3. **Datenbank:** heruntergeladene, aus OSM abgeleitete Straßen- und Tempolimitdaten.

Straße, Fahrtrichtung, Zeitpunkt und Gültigkeit bleiben für die Interpretation relevant. Bei einem **bestätigten Übergang In-Stadt ↔ Außer-Stadt** wird die bisherige visuelle Zeichenreferenz ungültig; das Tempolimit wird im neuen Kontext bestimmt. Ein kurz unbekannter oder schwach belegter Kontextwechsel reicht dafür nicht aus. Auch eine an den alten Straßen-/Ortskontext gebundene Sprachkorrektur kann an der bestätigten Grenze enden. Priorität bedeutet keine unbegrenzte Gültigkeit. Diese Erläuterung verändert keine geschützte Laufzeitlogik.

GitHub Actions bereitet regionale Datenbank-Bundles vor. Modelle aus dem Prolix-/Panoramax-Umfeld liefern die Grundlage für die Erkennung auf dem Gerät. Die Apps erzeugen Beobachtungen, Bildausschnitte und optional Straßenfotos. Panoramax, die Crops-/Sichtungsdatenbank und der Inspector dienen der Sammlung und Prüfung. Das übergeordnete Ziel ist ein Rückfluss geprüfter Beobachtungen nach **OpenStreetMap**. Den abschließenden Karten-Upload prüft und veranlasst ein Mensch.

### Fünf KI-Aufgaben in YouSpeed

- **Bildsegmentierung und Lokalisierung:** Verkehrszeichen im Kamerabild finden; Boxen und präzise Masken sind unterschiedliche Annotationen.
- **Verkehrszeichenklassifikation:** Bildausschnitte mit einem passenden Landesmodell einer Zeichenklasse zuordnen.
- **Spurerkennung:** Fahrbahnmarkierungen und Fahrkorridore aus Straßenbildern ableiten.
- **OCR:** Text auf Verkehrszeichen und Zusatztafeln lesen.
- **Spracherkennung:** gesprochene Nutzerkorrekturen mit **Apple Speech auf dem iPhone** beziehungsweise **Vosk unter Android** in eine erkannte Zahl umsetzen.

Die Spracherkennung unterstützt die bewusste Nutzerkorrektur als erstes Orakel. Modelle für die Kamerafunktionen und serverseitige Verarbeitung werden getrennt bewertet; für die mobile Ausführung zählt zusätzlich das Zeitbudget auf dem jeweiligen Gerät.

Nützliche Einstiege:

- [YouSpeed-Webseite](https://youspeed.de/) und [GitHub-Repository](https://github.com/volzinnovation/youspeed.de)
- [OSM-Verkehrszeichen und zugehörige Tags](https://trafficsigns.osm-verkehrswende.org/DE)
- [Deutsche Bedienungsanleitung](../docs/USER_GUIDE_DE.md) und [Ersteinrichtung](../docs/FIRST_RUN_WALKTHROUGH.md)
- [Inspector und Spurannotation](../inspector/README.md)
- [TSR-Trainingskreislauf](../docs/TSR_TRAINING_ROUND_TRIP.md), [bestehende Spurerkennung](../docs/LANE_DETECTION.md) und [Repository-Regeln](../AGENTS.md)

Store-Version und Quellcode können voneinander abweichen. Haltet für jedes Experiment App-Version, Build, Modellpaket und Code-Revision fest.

## 2. Konten, Geräte und Zugänge

Jedes Team benötigt eigene GitHub-Konten und **eigene Forks beider Repositories**:

- [volzinnovation/youspeed.de](https://github.com/volzinnovation/youspeed.de)
- [volzinnovation/Woladen.de-analytics](https://github.com/volzinnovation/Woladen.de-analytics) – privat; Zugang und private Forks müssen freigeschaltet sein.

Für Straßenbilder verwendet ihr ein eigenes freigeschaltetes Konto auf [panoramax.youspeed.de](https://panoramax.youspeed.de/). Dies ist ein Alias derselben Instanz wie [panoramax.woladen.de](https://panoramax.woladen.de/). Prüft die Sichtbarkeit je Upload und Kurskonto ausdrücklich und wendet die vereinbarte Kursvorgabe an; dokumentierte Voreinstellungen können von der aktuellen Oberfläche abweichen. Klärt vor der Erhebung, wie Team und Lehrende die ausgewählten Bilder lesen können. Die öffentliche französische Panoramax-Instanz ist ein eigener Dienst mit eigenen Konten und Regeln.

Ihr braucht ein Smartphone, eine stabile Halterung und freien Speicher. Bedient Aufnahmefunktionen vor der Fahrt, im sicheren Stand oder als mitfahrende Person. Für lokale Spurannotation benötigt ihr Python 3, Node.js, **FFmpeg und ffprobe**. Die Apps werden zunächst installiert; eine eigene App-Entwicklungsumgebung ist für den Einstieg nicht nötig.

GitHub-, Panoramax- und OSM-Konten sind getrennt. Für spätere öffentliche Kartenbeiträge verwendet ihr eigene OSM-Konten. Zugangsdaten, private Schlüssel und Datenbankpasswörter gehören weder in Repositories noch in Datensatzabgaben.

## 3. Projektmanagement mit Git und GitHub-Repositories

Ein **Repository** enthält Dateien und ihre Änderungsgeschichte. Ein **Fork** ist eure GitHub-Kopie; ein **Clone** die lokale Arbeitskopie. Ein **Commit** speichert einen benannten Stand. Ein **Branch** bezeichnet eine Entwicklungslinie. Ein **Pull Request** schlägt eine Änderung zur Prüfung vor. **GitHub Actions** führt definierte Abläufe aus, beispielsweise Tests und Bundle-Erzeugung.

Öffnet beide Originale und wählt **Fork** unter eurem Team- oder persönlichen Konto. Falls ein privater Fork nicht angeboten wird, lasst einen zulässigen privaten Teamarbeitsbereich bereitstellen. Erstellt keine öffentliche Kopie des privaten Backends.

Ersetzt `TEAM` durch den tatsächlichen Eigentümer eures Forks:

```sh
git clone https://github.com/TEAM/youspeed.de.git
git clone https://github.com/TEAM/Woladen.de-analytics.git
```

Im YouSpeed-Clone:

```sh
git remote add upstream https://github.com/volzinnovation/youspeed.de.git
git remote -v
git ls-remote --symref upstream HEAD
git status --short
git branch --show-current
```

Im Analytics-Clone:

```sh
git remote add upstream https://github.com/volzinnovation/Woladen.de-analytics.git
git remote -v
git ls-remote --symref upstream HEAD
git status --short
git branch --show-current
```

`origin` ist euer Fork, `upstream` das Original. Die Zeile `ref: refs/heads/... HEAD` zeigt den Standardbranch. Beide Originale verwendeten bei der Vorbereitung `main`; prüft die Einstellung selbst.

Lest die jeweils nächstgelegene `AGENTS.md`. Die aktuelle Analytics-Regel sieht Arbeit auf dem Standardbranch vor und verlangt ausdrückliche Anweisungen für andere Branches beziehungsweise Pull Requests. Übertragt keine Branch-Gewohnheit ungeprüft auf beide Repositories.

Beschreibt Aufgabe, Datensatz und Erfolgskriterium zunächst in einem Issue. Prüft die Änderungen und fügt nur beabsichtigte Dateien hinzu:

```sh
git status --short
git diff
git add pfad/zur/geaenderten-datei pfad/zum/experiment.json
git diff --cached
git commit -m "Experiment und zugehöriges Issue beschreiben"
git push -u origin HEAD
```

Die Pfade sind Platzhalter. Große Videos, private Fahrtprotokolle und Modellgewichte liegen im vereinbarten Datenspeicher. Ins Repository gehören Code, kleine Manifeste, Prüfsummen und Konfigurationen. Gebt zunächst einen überprüfbaren Stand im Team-Fork ab; Beiträge zum Original stimmt ihr mit der Lehrveranstaltung ab. Merge und produktiver Rollout sind gesonderte Schritte.

Weiterführend: [Forks](https://docs.github.com/en/get-started/quickstart/fork-a-repo) und [Pull Requests](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests).

## 4. Apps installieren und einrichten

Für die **1.4-alpha-Testfahrten** verwendet ihr die [signierten Android-APKs](https://github.com/volzinnovation/youspeed.de/releases/tag/android-v1.4-alpha) oder den [TestFlight-Einladungslink fürs iPhone](https://testflight.apple.com/join/k3a1pgce). Zielstände: Android **1.4-alpha** (Basisbuild 10052), iPhone **1.4 (10052)**. Die externe TestFlight-Freigabe muss Apple bestätigen; bis dahin kann der Link den bisherigen freigegebenen Build anbieten. Die [Release Notes mit Testfahrten-Checkliste](../docs/release/RELEASE_NOTES_1.4_ALPHA.md) beschreiben den Umfang und die noch offenen Prüfungen.

Die Lehrperson teilt die persönlichen Kurszugänge `student01` bis `student08` für Panoramax separat zu. Ändert euer temporäres Passwort bei der ersten Anmeldung. Zugangsdaten nicht untereinander teilen und nicht in Git speichern.

Verwendet den ausgewählten vorhandenen App-Build:

- [iPhone im App Store](https://apps.apple.com/de/app/youspeed-de/id6787469256)
- [Android bei Google Play](https://play.google.com/store/apps/details?id=de.youspeed.android)
- [Signierter Android-Release mit Prüfsummen](https://github.com/volzinnovation/youspeed.de/releases/tag/android-v1.3)

Die dokumentierte Android-Version setzt Android 14 oder neuer voraus. Der direkte Release bietet mehrere Gerätearchitekturen; häufig passt `arm64-v8a`. Prüft die installierte Version. Öffentliche 1.3-Versionen und integrierte 1.4-Entwicklungsstände unterscheiden sich.

Richtet die App im Stand ein:

1. Ladet die passende Region herunter und aktiviert sie, etwa Baden-Württemberg.
2. Erlaubt den genauen Standort und konfiguriert Warnhinweise.
3. Prüft Dashcam-Einstellungen und freien Speicher.
4. Aktiviert benötigte Kamera- und Sprachfunktionen. Zeichenerkennung kann ohne gespeichertes Video laufen.
5. Prüft Panoramax-Fotoaufnahme, Bildauswahl, Kontoverbindung und ausdrücklichen Upload.

Kontrolliert Halterung, Bildausschnitt, Linse, Standort und eine kurze Probeaufnahme. Projekt A braucht Straßenfotos, Projekt B lokale Dashcam-Videos. Es sind getrennte Ausgaben derselben Kamerasitzung.

### Nutzerkorrektur und Rückfluss nach OSM

Die dokumentierte Bedienung startet eine gesprochene Korrektur durch einen Doppeltipp auf das große Tempolimit-Schild. Bei **Jetzt sprechen** sprecht ihr die neue Zahl, etwa „30“. Erlaubt die angeforderten Mikrofon-/Sprachberechtigungen. Das iPhone verwendet Apple Speech, Android Vosk; Berechtigungen und Ablauf stehen in der jeweiligen Plattformanleitung.

Prüft danach Zeitpunkt, Straße, OSM-Weg-ID sowie alten und neuen Wert. Löscht falsche Zuordnungen oder falsch verstandene Zahlen. Die lokale Korrektur ändert OSM noch nicht.

Ein exportierter `changes.osc`-Vorschlag ist eine Prüfliste und enthält nicht zwingend vollständige aktuelle Geometrie und Objektversion. Ladet in JOSM die aktuellen betroffenen OSM-Objekte und die nötige Umgebung herunter, prüft die Beobachtung und übertragt nur bestätigte Änderungen. Kontrolliert den Änderungssatz vor dem Upload und verwendet euer eigenes OSM-Konto. Der abschließende Upload veröffentlicht echte Kartendaten.

## 5. Panoramax: Bilder und Verkehrszeichen annotieren

1. Aktiviert Fotoaufnahme und erfasst die geplante Strecke. Georeferenzierte Fotos kommen in die lokale Prüfliste; Dashcam-Videos sind getrennt.
2. Beendet die Aufnahme, öffnet die lokale Fotoprüfung **in der App**, prüft die Fotos und wählt den Lehrdatensatz aus.
3. Verbindet in der App das eigene zugewiesene Panoramax-Konto und startet dort den Upload ausdrücklich.
4. Wartet die Verarbeitung ab und notiert Sequenz-/Sammlungs-ID, Bild-ID, Quelle und Lizenz.
5. Prüft die Sichtbarkeit der verarbeiteten Bilder für Team und Begutachtung.

Fahrtende oder Netzwerk-Rückkehr starten den Panoramax-Fotoupload nicht von selbst. Die automatische Sichtungs-/Crop-Übertragung in 1.4 ist ein anderer Datenweg. Der dokumentierte Panoramax-Betrieb verwendet eine Verpixelungsverarbeitung.

Wechselt nach dem App-Upload zum Panoramax-Webviewer. Öffnet dort ein verarbeitetes Bild und meldet euch an. Wählt eine vorhandene Verkehrszeichenannotation oder zeichnet eine enge Box um ein Schild. Ergänzt die Semantik am **markierten Objekt**:

| Objekt | Panoramax-Schlüssel | Wert |
| --- | --- | --- |
| Ortseingang | `osm|traffic_sign` | `DE:310` |
| Ortsausgang | `osm|traffic_sign` | `DE:311` |

Ein Tag am gesamten Bild lokalisiert das Schild nicht. Behandelt einzelne Tafeln separat und ratet bei Unlesbarkeit oder unklarer Vorder-/Rückseite nicht. Speichert die Annotation, öffnet sie erneut und lasst Box, Klasse und Identität von einer zweiten Person prüfen. Bewahrt Bild-, Annotations- und Sequenz-IDs sowie vorhandene Autoren- und Modellherkunft im Datensatz. Eine vorhandene Modellannotation ist kein nachträglich erzeugtes menschliches Label. Die Oberfläche hängt von Viewer-Version und Kontorechten ab.

Die [Panoramax-Tag-Anleitung](https://docs.panoramax.fr/tags/) beschreibt die Bearbeitung. Falls erforderlich, verwendet den vereinbarten Helfer mit der [offiziellen Semantik-API](https://docs.panoramax.fr/backend/install/deep_dive/semantics/):

```text
POST /api/collections/{collectionId}/items/{pictureId}/annotations
```

Beispiel; die Koordinaten müsst ihr im tatsächlichen Quellbild messen:

```json
{
  "shape": [100, 250, 600, 900],
  "semantics": [
    {"action": "add", "key": "osm|traffic_sign", "value": "DE:310"}
  ]
}
```

Koordinaten sind Pixel ab der linken oberen Bildecke. Beispielzahlen sind keine gültigen Labels eurer Aufnahme. Semantik lässt sich ändern; Geometrieänderungen benötigen nach dem beschriebenen API-Vertrag eine Ersatzannotation. Bewahrt die Herkunft alter und neuer IDs. Boxen eignen sich für Detektion und Ausschnittklassifikation. Pixelgenaue Segmentierung braucht zusätzliche geprüfte Polygone oder Masken.

## 6. Inspector und Spurannotation

- **Karte & TSR:** Straßenzuordnung, Logs, Videos und Fahrpfade prüfen.
- **TSR QA:** Modellvorhersagen mit getrennten Annotationen vergleichen und Prüfberichte exportieren.
- **Backend-Crops:** Sichtungen/Ausschnitte nach Quelle, Land und Klasse durchsuchen; vereinbarter Serverzugang nötig.
- **Video annotieren:** lokale Spurmarkierungen beschriften, ohne produktive Datenbank, Kartendownload oder Fahrtlog.

Zeichenboxen werden in Panoramax erstellt. Die TSR-Prüfansicht und Crop-Galerie ersetzen diesen Annotationsschritt nicht.

Im YouSpeed-Verzeichnis:

```sh
python3 -m venv /tmp/youspeed-inspector-venv
/tmp/youspeed-inspector-venv/bin/python -m pip install -r inspector/requirements.txt
ffmpeg -version
ffprobe -version
/tmp/youspeed-inspector-venv/bin/python inspector/server.py --port 8080
```

Öffnet [den lokalen Inspector](http://127.0.0.1:8080/inspector/). Ein statischer `http.server` stellt keine Decoder-Endpunkte bereit. Videos werden zum lokalen Server zur temporären Indizierung übertragen; dadurch findet kein Panoramax-Upload statt.

**Vorabtest:** Am 18. Oktober startete das lokale FFmpeg zunächst wegen fehlender `libx265.216` nicht. Prüft, dass beide Programme wirklich laufen. Alternativ öffnet ihr das [synthetische Beispieldataset](assets/lane-demo.zip) über **Dataset importieren**. Gespeicherte Frames lassen sich ohne neue Videodekodierung bearbeiten. Das Beispiel erklärt den Ablauf und ist kein echter Trainings- oder Genauigkeitsnachweis.

### Markierungen Bild für Bild beschriften

1. Unter **Dashcam** Video wählen und **Video annotieren** starten; temporären Speicher einplanen.
2. Mit **‹ Bild / Bild ›**, Pfeiltasten oder Frame-Index tatsächliche dekodierte Frames und originale PTS-Zeitstempel prüfen.
3. **Neue Kurve · 4 Punkte** wählen: Start, zwei Kontrollpunkte und Ende für eine sichtbare Markierung setzen. Weitere Markierungen separat zeichnen.
4. **Durchgezogen / Gestrichelt** wählen. Gestrichelte Kurven beschreiben den Verlauf einschließlich sichtbarer Lücken, nicht einzelne Farbsegmente.
5. Über **Track verknüpfen** dieselbe physische Markierung verfolgen. Kopierte Vorlagen bleiben Entwürfe und müssen angepasst und neu geprüft werden.
6. **Frame geprüft bestätigen** wählen, auch bei wirklich leeren Negativbildern. Spätere Änderungen setzen den Frame zurück auf Entwurf.
7. Unter **Drive-Gruppe / Split** Clips derselben Fahrt vor Export derselben Gruppe und Partition zuweisen. Voreingestellte 80/10/10-Zuordnung garantiert bei kleinen Beständen keine ausgewogenen Klassen.
8. Mit **Dataset exportieren (.zip)** versioniert sichern. IndexedDB ist eine lokale Arbeitskopie; ZIP ist die portable Abgabe. Vor einem Import vorhandene Arbeit exportieren.

Schatten, Fugen oder Leitplanken sind keine Straßenmarkierungen. Erfindet hinter Verdeckungen keinen sichtbaren Verlauf. Dokumentiert unklare Fälle und gleicht Stichproben zwischen mehreren Personen ab.

Das Format `youspeed-lane-dataset-v1` enthält `manifest.json`, `images/<sample-id>.png` und `splits/{train,validation,test}.json`. Es bindet Quellhash, Frame/PTS, Geometrie, Fahrgruppe, Split und Prüfstatus zusammen. Originalvideos sind nicht enthalten. Nur geprüfte Samples stehen in den Split-Listen. Die vier normalisierten Kontrollpunkte beziehen sich auf das vollständig orientierte PNG. Das sind Kurven-/Polylinienlabels, keine Pixelmasken. Bild und Labels müssen dieselben Größen-/Ausschnitttransformationen erhalten.

Der vorhandene Loader prüft Vertrag und Bildbytes und erzeugt PNGs sowie `labels.jsonl`:

```sh
node scripts/inspector/lane_dataset_loader.mjs /pfad/dataset.zip \
  --split train --points 65 --output /pfad/training
node scripts/inspector/lane_dataset_loader.mjs /pfad/dataset.zip \
  --split validation --output /pfad/validierung
node scripts/inspector/lane_dataset_loader.mjs /pfad/dataset.zip \
  --split test --output /pfad/test
```

Ersetzt die Pfade. Klassen: `solid=0`, `dashed=1`. Verwendet keine ungeprüften Entwürfe als Trainings-/Testlabels. Vorhandene Regressionsbilder und farbige Ergebnis-Overlays behalten ihre ursprüngliche Quellen- und Labelbedeutung; sie sind keine neu erstellten menschlichen Segmentierungsmasken. Details: [Speichervertrag](../inspector/README.md#speichervertrag-youspeed-lane-dataset-v1).

## 7. Überwachtes Lernen und unabhängige Bewertung

Menschliche Labels beschreiben das gewünschte Ergebnis. Auf **Trainingsdaten** lernt das Modell Parameter. **Validierungsdaten** helfen bei Modell-, Hyperparameter- und Schwellwertwahl. **Testdaten** bleiben für die abschließende unabhängige Bewertung eingefroren. Wer nach jedem Testwert weiter auf diesen Bestand optimiert, verwendet ihn faktisch als Validierung.

Gruppiert zusammengehörige Frames vor Training und Augmentation. Wiederholte Ansichten desselben Schildes und überlappende Orte dürfen nicht zwischen Training und Abschlusstest verteilt werden. Eine Modellvorhersage ist erst nach Prüfung ein belastbares menschliches Label.

Dokumentiert Code-Revision, Ausgangsmodell, Datensatzversion, Lizenzen, Hashes, vollständige Split-Gruppen, Klassenanzahlen, Vorverarbeitung, Augmentation, Seed und Trainingskonfiguration. Vergleicht bestehende Lösung und Kandidat auf denselben unabhängigen Testdaten. Zeigt Fehlbeispiele und nicht nur einen Genauigkeitswert.

Servermodelle können asynchron rechnen. Liefert ein dort ausführbares Modellartefakt sowie vorgesehene Core-ML-/LiteRT-Exporte. Für mobile Kandidaten messt ihr Ende-zu-Ende-Verzögerung, p50/p95, Aktualisierungsrate, verworfene Frames, Speicher und thermisches Verhalten. **10 Hz = 100 ms**, **2 Hz = 500 ms** pro Aktualisierung. Bei **50 km/h** fährt ein Fahrzeug in **250 ms etwa 3,47 m**. Modelllaufzeit, Erfassungsintervall und Ergebnisalter sind verschiedene Größen.

Modellarbeit ändert nicht automatisch die [geschützte Geschwindigkeitsreferenz-Policy](../shared/speed-limit-reference/AGENTS.md). Produktiver Rollout und öffentliche Veröffentlichung folgen der vereinbarten Prüfung und ausdrücklichen Freigabe.

## 8. Projekt A: Ortstafeln erkennen – Teams A1 und A2

**Fragestellung:** Wie lassen sich Ortseingang (`osm|traffic_sign=DE:310`) und Ortsausgang (`osm|traffic_sign=DE:311`) aus eigenen Aufnahmen zuverlässig erkennen?

Der geprüfte deutsche Klassifikator mit 134 Ausgaben besitzt diese Ortstafelklassen nicht als echte Modellausgänge. Katalogeinträge und Piktogramme schaffen keine erlernte Fähigkeit. Im [Bernbach-Experiment](../docs/TSR_PROLIX_ALIGNMENT_2026-09-10.md#bernbach-zeichen-310-experiment) fand die Lokalisierung das Schild, die Klassifikation lieferte `bad`.

**Phase 1 – menschliche Labels:** Beide Teams erheben vielfältige Ein-/Ausfahrtsbilder, annotieren Boxen und genaue Tags in Panoramax und prüfen Labels gegenseitig. Erfasst Blickrichtungen, Verdeckungen und Gegenbeispiele wie gelbe Wegweiser. Bewahrt Schildidentität, Bild-/Annotations-IDs, Lizenz und Splits. Ein gemeinsames Protokoll macht Teamlösungen vergleichbar; Datensatz und Experiment bleiben je Team nachvollziehbar.

**Phase 2 – Lernen und Testen:** Reproduziert den Ausgangsstand. Erweitert und trainiert den DE-Klassifikator mit tatsächlichen Ein-/Ausgangsklassen. Untersucht getrennt übersehene Zeichen, Ausschnittfehler und Klassifikationsfehler. Eine spätere Segmentierung erfordert geprüfte Masken/Polygone. Bewertet Recall, Präzision, Verwechslungen und Regressionen bestehender Klassen auf ungesehenen Schildern und Strecken.

**Phase 3 – Modellkandidat:** Liefert ein serverseitiges Modell und vorgesehene mobile Exporte beziehungsweise überprüfbare Integrationsartefakte. Vergleicht Vorverarbeitung, Labelreihenfolge und Ergebnisse beider Plattformen. Ein Ortsausgang bedeutet nicht pauschal 100 km/h; die Laufzeitinterpretation bleibt außerhalb dieser Modellaufgabe.

**Abgabe:** Team-Issue, Datenkarte, Label-/Quellreferenzen, eingefrorene Splits, Trainings-/Evaluationscode, Ausgangsvergleich, Modellversionen/Prüfsummen und kurze Demonstration mit Erfolgen und Fehlern. Ziel ist ein geprüfter Beitrag zur Erkennung und zur späteren nutzergesteuerten OSM-Verbesserung.

## 9. Projekt B: Spurerkennung verbessern – Teams B1 und B2

**Fragestellung:** Verbessert überwachtes Lernen die Geometrie sichtbarer Markierungen auf unabhängigen Fahrten innerhalb des Laufzeitbudgets?

**Phase 1 – menschliche Labels:** Beide Teams filmen eigene Strecken und erstellen im Inspector geprüfte Kurven, Klassen und Track-IDs. Berücksichtigt Kurven, abgenutzte Markierungen, Stadtstraßen, Schatten, Gegenlicht und leere Negativbeispiele. Prüft schwierige Fälle doppelt. Haltet Fahrten und überlappende Orte in einem Split. Gemeinsame Labelregeln ermöglichen einen fairen Teamvergleich.

**Phase 2 – Lernen und Testen:** Reproduziert die vorhandene native Spurerkennung und wählt einen messbaren Fehler. Die bestehende Lösung verwendet klassische Bildverarbeitung und Tracking. Trainiert einen Kandidaten aus geprüften Labels und dokumentiert die Zielrepräsentation: Kurven, Stützpunkte oder abgeleitete Masken. Vergleicht Geometriefehler, übersehene Markierungen, Klassen und zeitliche Stabilität auf unangetasteten Testfahrten.

**Phase 3 – Modellkandidat:** Erstellt serverseitig ausführbare Artefakte und passende mobile Kandidaten. Prüft Geometrietransformationen, fehlende Evidenz, Ein-/Ausschalten, alte Frames und dauerhafte Kameralast. Liefert Messwerte sowie Rückfall-/Rollback-Vorschlag. Der Einstieg setzt keine eigene App-Entwicklung voraus; spätere Integration wird mit den Lehrenden abgestimmt.

**Abgabe:** Annotierte ZIP, Datenkarte, unabhängige Splits, reproduzierbarer Trainingscode, Vergleichsbericht, Modelle/Prüfsummen, Laufzeitnachweise und kurze Demonstration erkannter Markierungen einschließlich Unsicherheiten.
