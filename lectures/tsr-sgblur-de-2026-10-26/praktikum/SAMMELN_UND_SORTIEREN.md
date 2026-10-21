# Bilder aus Panoramax sammeln und prüfen

## Zwei Beispielsätze für Detektion und Klassifikation

Sie können vorhandene Panoramax-Annotationen für zwei unterschiedliche Aufgaben verwenden: Ein **Detektor** sucht Objekte im vollständigen Straßenbild und zeichnet Boxen. Ein **Klassifikator** erhält einen ausgeschnittenen Schildbereich und bestimmt die Zeichenklasse. Der Crawler erzeugt beide Beispielsätze. Durch Prüfen und Verschieben entscheiden Sie anschließend, welche Beispiele übernommen werden.

**Eine vorhandene Annotation ist zunächst ein Vorschlag.** Auch eine sehr hohe gespeicherte Modellbewertung kann falsch sein. Das Herunterladen oder Verschieben trainiert noch kein Modell. Die Gewichte ändern sich erst beim späteren Training.

Diese Anleitung setzt den vorbereiteten Kurszugang voraus. Öffnen Sie ein Terminal im Ordner `lectures/tsr-sgblur-de-2026-10-26/praktikum/`. Verwenden Sie die aktivierte Python-Umgebung des Dozenten. Sie benötigen für das Sammeln keine GPU und keinen selbst geschriebenen Trainingscode.

## 1. Mit der veröffentlichten Lernsammlung beginnen

Die acht Straßenbildpakete sind im öffentlichen Datensatz [loffenauer/ws26_hspf_imo](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo) verfügbar. Verwenden Sie die [Downloadanleitung für den KI-Server](DATEN_HERUNTERLADEN.md): Sie enthält die konkreten CLI-/HTTPS-Befehle ohne Login, die SHA-256-Prüfung und die tatsächlichen Archivordner. Der Kurs verwendet fest die Revision **`c02d4163a58a7fcc6e97b0195abc22ae0b0dd249`**. Die Download-CLI wird getrennt von der Trainingsumgebung installiert.

Übernehmen Sie **Datensatz 1 mit 100 Vollbildern und 214 Crops nach `data/collection/`**. Alle Beispiele sind ungeprüft. Lesen Sie deren `BITTE_ZUERST_LESEN.txt` und setzen Sie anschließend direkt bei Abschnitt 2 dieser Anleitung fort. Die folgenden Standardpfade und Importbefehle passen zu dieser Sammlung. Das kleine Demo liegt getrennt unter `data/demo/collection-demo/` und enthält zwei bereits in der Lernsammlung enthaltene Bilder.

Die zwei weiteren Pakete sind **Testkandidaten für den Dozenten**. Sie bleiben unter `data/teacher-reserved/` und werden nicht in den normalen Import, ins Training oder in die Validierung übernommen. Kein Paket enthält bereits menschlich freigegebene Ground Truth. Die ursprünglichen Gruppen der Lernsammlung haben außerdem keine Ortstafel-Testabdeckung. Zusätzliche geeignete unabhängige Gruppen und der kuratierte Korpus der 134 Bestandsklassen müssen vor dem Modellversuch mit dem Dozenten bereitgestellt werden.

**Datensatz 2: MobiData BW** umfasst [v2 mit 57 Paaren](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/c02d4163a58a7fcc6e97b0195abc22ae0b0dd249/packages/panoramax-mobidata-bw-review-2026-10-20-v2.zip?download=true) und die [zusätzlichen 63 Crop-/Vollbildpaare](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/c02d4163a58a7fcc6e97b0195abc22ae0b0dd249/packages/panoramax-mobidata-bw-review-2026-10-20-additions.zip?download=true). Laden Sie beide Archive gemäß [Abschnitt 5a der Downloadanleitung](DATEN_HERUNTERLADEN.md#5a-zweiter-lerndatensatz-mobidata-bw) und entpacken Sie sie in getrennte Sichtungsordner. Zusammen mit Datensatz 1 stehen **220 Vollbilder und 334 Crops**, darunter **190 Ortstafel-Kandidaten (144 DE:310, 46 DE:311)**, zur Prüfung bereit. Die beiden MobiData-Pakete ergeben 120 Paare mit 95 DE:310- und 25 DE:311-Vorschlägen. Öffnen Sie jeweils `SICHTUNG.html`; prüfen Sie Klassen und vollständige Vollbildannotation vor einem passenden Kurs-Export. Der Standardimport übernimmt die Teilannotation nicht direkt. Seine bisherigen Pfade beziehen sich auf Datensatz 1.

### Optional: einen neuen begrenzten Bestand crawlen

Wenn Sie zusätzlich neue vorhandene Annotationen sammeln, verwenden Sie einen neuen Ausgabeordner:

```sh
python crawl_panoramax.py --max-images 100 --output data/collection-neu
```

Die Standardinstanz ist `https://panoramax.youspeed.de`. Der Parameter `--instance` erwartet diese Stammadresse **ohne `/api`**; die API-Pfade ergänzt das Skript selbst. Ohne `--output` wäre der Ausgabeordner `data/collection/`; hier hält `--output data/collection-neu` den zusätzlichen Crawl von Ihrer Lernsammlung getrennt. Das Skript liest vorhandene Metadaten und öffentlich erreichbare HD-Bildableitungen. Es führt ausschließlich Lesezugriffe aus; es lädt keine Bilder oder Annotationen zum Server hoch.

`--max-images 100` begrenzt die Bildabrufversuche. Ein Vollbild kann mehrere Schild-Crops liefern. Zusätzlich gelten standardmäßig höchstens 2000 betrachtete Bildobjekte und 100 API-Seiten. Ein beendeter begrenzter Lauf ist deshalb **kein vollständiges Inventar der Instanz**. Die tatsächlich gefundenen, ausgelassenen und heruntergeladenen Beispiele stehen im Laufprotokoll beziehungsweise Manifest. Es können auch keine passenden Beispiele vorhanden sein. 360°-Bilder werden ausgelassen, weil dieser Einstieg keine eigene Perspektivprojektion durchführt.

Für eine gezielte Auswahl können Sie eine bekannte vollständige Item-URL mit `--item-url` angeben. Der Parameter ist wiederholbar. Das folgende Beispiel verwendet ein tatsächlich vorhandenes Bild mit einer gespeicherten Ortseingangsannotation und einen eigenen Ausgabeordner:

```sh
python crawl_panoramax.py --max-images 1 \
  --item-url 'https://panoramax.youspeed.de/api/collections/b23c42f0-217d-4a50-96ad-0ed96ab0dbab/items/0bf296e2-938e-4e80-a89c-5da2112e8ccc' \
  --output data/collection-beispiel
```

Die gespeicherte Ortstafelbox dieses Beispiels misst nur 27 × 22 Pixel. Das eignet sich zum Prüfen des technischen Ablaufs, ist aber kein automatisch geeignetes Trainingsbeispiel. Beurteilen Sie die Lesbarkeit selbst. Die folgenden Standardpfade beziehen sich weiterhin auf `data/collection/`; für einen anderen Sammelordner müssen Sie beim Import den passenden `--source` angeben. Ein neuer Crawl benötigt einen neuen Ausgabeordner.

Der Crawler lädt nur Bilder mit mindestens einer verwendbaren vorhandenen Schild-, Kennzeichen- oder Gesichtsannotation herunter. Bilder ohne solche Annotationen werden mit einer Begründung ausgelassen; sie werden nicht als vermeintlich objektfreie Negativbeispiele exportiert. Eine Ortstafel, zu der noch keine Box gespeichert ist, wird dadurch nicht automatisch zu einem gelabelten Beispiel. Ergänzen beziehungsweise korrigieren Sie solche Annotationen gezielt in Panoramax und exportieren Sie den korrigierten Stand erneut. Das spätere Verschieben einer Datei repariert keine Box.

Die Ausgabe ist so aufgebaut:

```text
data/collection/
  manifest.json                       # Herkunft und unveränderte Ausgangsdaten
  inbox/
    classifier/<crop-id>.png           # ungeprüfter Schild-Crop
    detector/<picture-id>/
      image.png                       # vollständiges Straßenbild
      labels.txt                      # alle exportierten Objektboxen
      metadata.json                   # Annotationen und Bildherkunft
  approved/
    classifier/<klassenordner>/        # 136 vorbereitete Klassenordner
    detector/                         # vollständig geprüfte Bildpakete
  rejected/                           # ausgeschlossene Beispiele
```

Die tatsächlichen Kennungen in den Dateinamen identifizieren Bild und Annotation. Benennen Sie Dateien und Bildpakete nicht um. Bewahren Sie `manifest.json` und die Metadaten zusammen mit der Sammlung auf. Sie enthalten unter anderem Quell-IDs, Autor, Lizenz, Boxen und Prüfsummen. **Die Ordner `inbox` und `rejected` werden beim Import nicht als freigegebene Trainingsbeispiele übernommen.** Unklare Fälle können in `inbox` bleiben.

## 2. Schild-Crops ansehen und einer Klasse zuordnen

Öffnen Sie einen Crop aus `inbox/classifier/` in der Bildanzeige. Vergleichen Sie ihn bei Bedarf mit dem vollständigen Quellbild und dem zugehörigen Eintrag im Manifest. Die gespeicherten Panoramax-Tags sind eine Hilfe für die Prüfung. Sie ersetzen Ihre Entscheidung nicht.

Prüfen Sie, ob der Ausschnitt tatsächlich ein einzelnes bestimmbares Schild zeigt und vollständig genug ist. Achten Sie bei Ortstafeln besonders auf den roten Diagonalstrich: Ein abgeschnittener Strich kann Ortseingang und Ortsausgang verwechselbar machen. Stark verdeckte, falsch ausgeschnittene oder nicht sicher bestimmbare Bilder geben Sie nicht frei. Lassen Sie Box und Klasse zusätzlich von einer zweiten Person prüfen.

| Sichtbares Zeichen | Panoramax-Code | Modellklasse | Zielordner |
| --- | --- | --- | --- |
| Ortseingang | `osm\|traffic_sign=DE:310` | `city:start` | `approved/classifier/city__start/` |
| Ortsausgang | `osm\|traffic_sign=DE:311` | `city:end` | `approved/classifier/city__end/` |

Die Doppelpunkte der Modellklassen werden im Sortierordner als **zwei Unterstriche** geschrieben. Beispielsweise wird `city:start` zu `city__start`. Verwenden Sie die angelegten Ordner; verändern Sie weder deren Schreibweise noch [class-index.json](class-index.json). Der Importer übersetzt den Ordnernamen wieder in die richtige Modellklasse und erhält deren feste Reihenfolge.

Verschieben Sie den geprüften Crop im Dateimanager in den passenden Klassenordner. **Der gewählte Ordner legt die bestätigte Klasse fest**, auch wenn die ursprüngliche Modellannotation eine andere Klasse vorgeschlagen hat. Sie können dadurch beispielsweise einen irrtümlich als Ortseingang vorgeschlagenen Crop korrekt nach `city__end` sortieren.

Alternativ können Sie im Linux-Terminal `mv` verwenden. Ersetzen Sie `BEISPIEL-CROP-ID.png` durch den tatsächlichen Dateinamen; die einfachen Anführungszeichen gehören zum Befehl:

```sh
mv 'data/collection/inbox/classifier/BEISPIEL-CROP-ID.png' \
  'data/collection/approved/classifier/city__start/'
```

Verschieben Sie die Datei, statt sie in mehrere Klassen zu kopieren. Ein ungeeigneter Crop kann aus der Eingangsablage nach `rejected/classifier/` verschoben werden. Entfernen Sie keinen Quellnachweis aus dem Manifest. Wenn Sie sich bei einem Bild noch nicht sicher sind, lassen Sie es zunächst in `inbox` und besprechen Sie es mit dem Dozenten.

## 3. Vollbilder und Boxen als zusammengehörendes Paket prüfen

Für die Detektion reicht die richtige Klasse eines einzelnen Crops nicht aus. Öffnen Sie `inbox/detector/<picture-id>/image.png` und prüfen Sie **alle** exportierten Boxen anhand von `labels.txt`, `metadata.json` und der Panoramax-Ansicht. Die Klassenbelegung des vorhandenen SGBlur-Detektors lautet unverändert:

| Zahl in `labels.txt` | Klasse | Bedeutung |
| --- | --- | --- |
| `0` | `sign` | Schild, einschließlich Ortseingang und Ortsausgang |
| `1` | `plate` | Kennzeichen |
| `2` | `face` | Gesicht |

Eine Zeile in `labels.txt` enthält `klasse mitte_x mitte_y breite höhe`. Die vier Koordinaten sind auf Bildbreite beziehungsweise Bildhöhe normiert: Ein Wert von `0.5` bezeichnet die Hälfte der entsprechenden Bildabmessung. Diese Werte erzeugt das Skript aus den Pixelboxen. Sie müssen sie für den normalen Ablauf nicht von Hand berechnen.

Prüfen Sie, ob jedes relevante Objekt der drei Klassen eine richtige Box hat, ob die Boxen das richtige Objekt umschließen und ob keine falschen zusätzlichen Boxen vorhanden sind. Ein Bild mit einem korrekt eingerahmten Ortseingangsschild kann trotzdem ungeeignet sein, wenn weitere sichtbare Schilder oder Kennzeichen keine Box haben. Beim Training könnten solche Objekte sonst als Hintergrund behandelt werden.

**Verschieben Sie ein Detektor-Paket erst nach vollständiger Prüfung aller drei Klassen.** Dabei bleiben `image.png`, `labels.txt` und `metadata.json` zusammen. Ein bestätigtes Paket verschieben Sie als ganzen Ordner nach `approved/detector/`. Ersetzen Sie die Beispielkennung:

```sh
mv 'data/collection/inbox/detector/BEISPIEL-BILD-ID' \
  'data/collection/approved/detector/'
```

Verschieben Sie keine einzelne Bild- oder Labeldatei. Erzeugen Sie keine leeren Labeldateien aus einem Bild ohne gespeicherte Annotationen: Fehlende Annotationen belegen nicht, dass keine Objekte sichtbar sind.

Sind Boxen falsch oder fehlen sie, geben Sie das Paket nicht frei. Korrigieren Sie den Quellstand in Panoramax und lassen Sie einen neuen Export erstellen. Bewahren Sie ältere Sammlungen getrennt auf. Die vorhandene Sammlung dient als unveränderter Herkunftsbeleg; der Importer akzeptiert keine still veränderten Bild- oder Boxdateien.

Die öffentlich verfügbaren HD-Bilder sind häufig bereits an Gesichtern und Kennzeichen verwischt. Boxen können dort noch geprüft werden. Eine solche Sammlung belegt jedoch **keine Detektionsqualität auf unverpixelten Gesichtern und Kennzeichen**. Für einen aussagekräftigen SGBlur-Vergleich muss der Dozent einen geeigneten unabhängigen Prüfbestand und dessen Grenzen festlegen.

## 4. Zusammengehörende Bilder in derselben Gruppe halten

Mehrere Ansichten derselben Tafel sind keine unabhängigen Testfälle. Alle Bilder einer Panoramax-Sequenz und sämtliche daraus erzeugten Crops bleiben deshalb standardmäßig in derselben Gruppe. Detektor und Klassifikator verwenden für diese Gruppe denselben Seed `20261026` und dieselbe Zielaufteilung von ungefähr **70 % Training, 15 % Validierung und 15 % Test**.

Dieselbe physische Tafel oder dieselbe Fahrt kann trotzdem in mehreren Sequenzen vorkommen. Prüfen Sie diese Beziehungen gemeinsam mit dem Dozenten, **bevor Sie importieren oder trainieren**. In `data/groups.csv` können zusammengehörende Sequenzen dieselbe Gruppenkennung erhalten:

```csv
sequence_id,group_id
SEQUENZ-ID-A,gemeinsame-fahrt-01
SEQUENZ-ID-B,gemeinsame-fahrt-01
```

Die IDs sind Beispiele und müssen durch die tatsächlichen Panoramax-Sequenzkennungen ersetzt werden. Diese Datei wird beim Import mit `--groups data/groups.csv` angegeben. Der Crawler erkennt gleiche physische Tafeln oder Nahe-Duplikate über verschiedene Sequenzen nicht automatisch. Stimmen Sie die Gruppen auch mit dem bereitgestellten Bestandskorpus ab. Verschieben Sie keine Beispiele zwischen Training und Test, um anschließend bessere Zahlen zu erhalten.

## 5. Die geprüfte Auswahl importieren

Nach dem Sortieren erzeugt der Importer die maschinenlesbaren Beispielsätze. Er übernimmt nur die freigegebenen Ordner und prüft die Zuordnung zu den ursprünglichen Dateien:

```sh
python import_sorted_folders.py
```

Die Vorgaben sind `--source data/collection` und `--output data/reviewed`. Wenn zusammengeführte Sequenzgruppen festgelegt wurden, lautet der Aufruf:

```sh
python import_sorted_folders.py --groups data/groups.csv
```

`data/reviewed/` muss ein neuer Ausgabeordner sein. Falls Sie später erneut sortieren oder Annotationen neu exportieren, verwenden Sie für den nächsten Import einen anderen Ausgabeordner. Der Importer friert den geprüften Stand ein, statt ein früheres Experiment still zu verändern.

Eine kleine Ortstafelsammlung ersetzt **nicht** die Beispiele der 134 Bestandsklassen. Für den vollständigen Klassifikatorversuch verbinden Sie Ihre Auswahl mit dem vom Dozenten bereitgestellten geprüften Korpus:

```sh
python import_sorted_folders.py \
  --include-annotations data/annotations.csv \
  --include-images data/raw/images
```

Die beiden `--include-…`-Angaben werden gemeinsam verwendet. Ergänzen Sie bei Bedarf auch hier `--groups data/groups.csv`. Bildpfade der bereitgestellten CSV gelten relativ zu `data/raw/images/`. Ändern Sie deren geprüfte Klassen nicht beim Zusammenführen.

Die Ausgabe enthält:

```text
data/reviewed/
  manifest.json
  classifier/
    annotations.csv
    images/
  detector/
    images/train/   images/val/   images/test/
    labels/train/   labels/val/   labels/test/
    data.yaml
    manifest.json
```

Der Klassifikator erhält eine Tabelle mit den Spalten `sample_id,image_path,label,group_id`. Der Detektor erhält Vollbilder, zugehörige YOLO-Boxdateien und die feste Drei-Klassen-Beschreibung `data.yaml`. Die Manifeste dokumentieren Herkunft, Prüfung, Gruppen, Aufteilung und Klassenabdeckung. Der Import erzeugt noch keinen Modellkandidaten.

Die Detektor-Datei `data.yaml` verweist auf den absoluten Ausgabeordner. Verschieben Sie den fertigen Datensatz deshalb nicht nachträglich. Soll er an einem anderen Ort liegen, importieren Sie die geprüfte Sammlung erneut mit einem neuen `--output`; dadurch wird der Pfad passend geschrieben. Der gemeinsame Split-Seed ist fest auf `20261026` gesetzt.

## 6. Mit dem passenden Modellversuch fortfahren

Für den Klassifikator übergeben Sie die importierte Tabelle und deren Bilder an die vorhandene Datenvorbereitung:

```sh
python prepare_dataset.py \
  --annotations data/reviewed/classifier/annotations.csv \
  --images data/reviewed/classifier/images
python train.py --epochs 20
python evaluate.py --candidate runs/versuch-01/weights/best.pt
```

Fehlen nach dem Import Bestandsklassen, ist die Sammlung noch nicht vollständig. `prepare_dataset.py` verlangt alle 136 Klassen im Training. Außerdem benötigen Sie geeignete unabhängige Validierungs- und Testbeispiele. Leere Ordner oder viele nahezu gleiche Fotos derselben Tafel ersetzen diese Abdeckung nicht. Lesen Sie die Warnungen zur Klassenverteilung und ergänzen Sie die fehlenden Daten mit dem Dozenten.

Die weiteren Schritte für Kandidatenwahl, Bestandsvergleich, Abschlusstest und Abgabe stehen in der [Praktikumsanleitung](README.md).

## 7. Bei fehlenden Boxen einen getrennten Detektorversuch starten

Ein zusätzliches Detektortraining ist sinnvoll, wenn Boxen fehlen. **`train.py` aus diesem Praktikum trainiert den Crop-Klassifikator, keinen Detektor.** Für den Detektor verwenden Sie die Ultralytics-Befehle und vollständig geprüfte Vollbilder. Nur Ortstafel-Crops an das Detektortraining zu übergeben ist kein Ersatz dafür.

Der Dozent stellt `models/detector-baseline.pt` bereit: den ursprünglichen SGBlur-YOLO11n mit der Belegung `0=sign`, `1=plate`, `2=face`. Dieser Checkpoint ist eine andere Datei als `models/baseline.pt` für die deutsche Klassifikation. Verwechseln Sie die beiden Modelle nicht.

Prüfen Sie vor dem Start mit dem Dozenten die Verteilung der freigegebenen Vollbilder. Training, Validierung und Test müssen geeignete unabhängige Gruppen enthalten. Alle drei Klassen benötigen eine ausreichende Abdeckung, damit bestehende Fähigkeiten beurteilt werden können. Sind `val` oder `test` leer oder unvollständig, ergänzen Sie weitere unabhängige, vollständig annotierte Bilder. Würfeln Sie den Split nicht mit anderen Seeds neu aus und verschieben Sie keine Testbilder ins Training.

Der Trainingsaufruf in der vorbereiteten GPU-Umgebung lautet:

```sh
yolo detect train model=models/detector-baseline.pt \
  data=data/reviewed/detector/data.yaml \
  epochs=20 imgsz=1280 device=0 seed=20261026
```

`imgsz=1280` legt die Eingabegröße des Detektors fest; der Klassifikator arbeitet dagegen mit 224 × 224 Pixeln. `device=0` bezeichnet das im Kurszugang sichtbare CUDA-Gerät. Verwenden Sie nur das vom Dozenten zugewiesene Gerät. Die Epochenzahl ist ein Startwert und keine Qualitätsgarantie.

Die Trainingsausgabe nennt den tatsächlichen Versuchsordner und den Kandidaten `weights/best.pt`. Beim ersten Standardlauf ist dies gewöhnlich `runs/detect/train/weights/best.pt`; bei weiteren Läufen kann der Ordnername abweichen. Wählen Sie den Kandidaten anhand der Validierung. Öffnen Sie erst danach den Test und bewerten Sie **Ausgangsmodell und Kandidat auf denselben zurückgehaltenen Vollbildern**:

```sh
yolo detect val model=models/detector-baseline.pt \
  data=data/reviewed/detector/data.yaml split=test imgsz=1280 device=0
yolo detect val model=runs/detect/train/weights/best.pt \
  data=data/reviewed/detector/data.yaml split=test imgsz=1280 device=0
```

Passen Sie im zweiten Befehl den Kandidatenpfad an den tatsächlich erzeugten Ordner an. Vergleichen Sie die Werte je Klasse, insbesondere Recall, Precision und mAP. Zeigen Sie zusätzlich übersehene und falsch erkannte Boxen. Eine Verbesserung bei Schildern gleicht einen Verlust bei Gesicht oder Kennzeichen nicht aus. Die YOLO-Befehle erzeugen Messwerte; sie führen nicht automatisch das Bestandsklassen-Gate des separaten Crop-Auswerteskripts aus.

Ein Vergleich auf bereits verwischten öffentlichen Bildern gilt nur für diesen Bildbestand. Er beweist keine Leistung auf unverpixelten Gesichtern und Kennzeichen und ersetzt keine spätere Prüfung der vollständigen Datenschutzverarbeitung. Bewahren Sie Sammlung, Gruppenfestlegung, Importmanifeste, beide Modellstände und die Bewertungsberichte als Teil Ihrer Ergebnisdokumentation auf.

## Mapillary-Ergänzung mit MobiData BW

Die [Downloadanleitung](DATEN_HERUNTERLADEN.md#5b-dritter-lerndatensatz-mapillary-anhand-mobidata-bw) beschreibt beide Mapillary-Archive mit insgesamt 75 Crop-/Vollbildpaaren (56 DE:310, 19 DE:311). Öffnen Sie beide `SICHTUNG.html`-Dateien in getrennten Ordnern und bearbeiten Sie die dortigen Arbeitslisten. Der Katastercode kann die andere Schildseite beschreiben. Prüfen Sie Klasse und alle relevanten Vollbildboxen vor einem passenden Kurs-Export; der Standardimport übernimmt die Teilannotation nicht direkt. Gleiche Tafeln und Fahrten bleiben auch über Panoramax und Mapillary hinweg zusammen. Beachten Sie die paketübergreifenden Gruppenvorschläge und die gekennzeichnete Panorama-Perspektive. Bewahren Sie Urheber, Bild-ID, Quelllink, CC-BY-SA-4.0-Lizenz und Änderungshinweise auf. Die vollständige Lernsammlung umfasst fünf Archive mit 295 Vollbildern und 409 Crops; alle Klassen bleiben bis zum Review Vorschläge.
