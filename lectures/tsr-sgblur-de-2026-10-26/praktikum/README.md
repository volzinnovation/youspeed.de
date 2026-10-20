# Bildklassifikation mit KI

## Wie verbessere ich ein vorhandenes KI-Modell?

**Für Studierende im 3. Semester · Einstieg ohne ML-Vorkenntnisse**

Sie erweitern einen vorhandenen Bildklassifikator um **Ortseingang** und **Ortsausgang**. Sie verwenden dafür geprüfte Schildbilder aus Panoramax, starten einen Trainingslauf und vergleichen das Ergebnis mit dem unveränderten Ausgangsmodell.

Ein **Klassifikator** bekommt ein ausgeschnittenes Schildbild und ordnet ihm eine Klasse zu. Er sucht hier keine Schilder im vollständigen Straßenfoto. Diese Aufgabe übernimmt vorher der Detektor. Sie laden die bereitgestellte Panoramax-Lernsammlung herunter, prüfen deren **Bildausschnitte (Crops)** mit jeweils einem Schild und sortieren sie in Klassenordner. Ein optionaler neuer Crawl kann weitere vorhandene Annotationen ergänzen. Vollbilder und Boxen bilden einen getrennten Beispielsatz für den Detektor.

## Was vor Beginn bereitstehen muss

Der Dozent stellt eine eingerichtete Python-/GPU-Arbeitsumgebung auf dem KI-Server bereit. Die Skripte erwarten darin Ultralytics 8.4.56 und die passenden PyTorch-Abhängigkeiten. Sie erhalten außerdem:

- `models/baseline.pt`: das geprüfte deutsche Ausgangsmodell mit 134 Klassen;
- geprüfte Crops und Klassenangaben für diese 134 Bestandsklassen;
- eine Zuordnung zusammengehörender Bilder zu Gruppen;
- einen Arbeitsordner mit den bereitgestellten Sammel-, Import- und Trainingsskripten.

Sie ergänzen geprüfte Beispiele für die zwei neuen Klassen. Der Code und die feste Klassentabelle sind enthalten. Die ungeprüften Panoramax-Pakete sind öffentlich unter [loffenauer/ws26_hspf_imo](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo) verfügbar. **Der Modellcheckpoint und der vollständige geprüfte Korpus der 134 Bestandsklassen werden weiterhin separat vom Dozenten bereitgestellt.** Ohne sie ist kein vollständiger Trainingslauf möglich.

Der Crawler ergänzt den bereitgestellten Korpus; er garantiert weder Beispiele aller 134 Bestandsklassen noch ausreichend unabhängige Ortstafeln. Sein begrenzter Suchlauf ist kein vollständiges Inventar der Instanz.

Die Bestandsklassen bleiben erhalten: Das neue Modell soll 136 Klassen unterscheiden. Die bisherigen Zeichen dürfen im vereinbarten Vergleich nicht schlechter werden. Dafür brauchen Sie geeignete Bestandsbeispiele im Training, in der Validierung und im unabhängigen Test. Wenn Sie nur Ortstafeln prüfen, können Sie diese Bedingung nicht beurteilen.

## 1. Den Arbeitsordner öffnen

Öffnen Sie im vorbereiteten Kurszugang ein Terminal. Wechseln Sie vom Repository-Hauptordner in das Praktikum:

```sh
cd lectures/tsr-sgblur-de-2026-10-26/praktikum
```

Die folgenden Befehle setzen voraus, dass Sie in diesem Ordner bleiben. Der Dozent aktiviert die passende Python-Umgebung; die Beispiele verwenden darin den Befehl `python`.

```text
praktikum/
  crawl_panoramax.py
  import_sorted_folders.py
  prepare_dataset.py
  train.py
  evaluate.py
  class-index.json
  models/baseline.pt
  data/annotations.csv
  data/raw/images/          # geprüfte Schild-Crops
```

`class-index.json` legt fest, welcher Modellausgang zu welcher Klasse gehört. Ändern oder sortieren Sie diese Datei nicht. Die Skripte verwenden diese feste Reihenfolge.

## 2. Die Lernsammlung herunterladen, prüfen und einsortieren

Folgen Sie zuerst der [Downloadanleitung für den KI-Server](DATEN_HERUNTERLADEN.md). Sie enthält die isolierte Installation von `huggingface_hub==1.10.2` mit den festgelegten CLI-Abhängigkeiten `typer==0.24.1` und `click==8.3.2`, einen HTTPS-Alternativweg und die Prüfsummenprüfung **vor** dem Entpacken. Ein Hugging-Face-Login ist nicht nötig. Der feste Datensatzstand lautet `6837ae4fae0d1d216612afa739c9dfefd6b277ab`.

Die Lernsammlung mit **100 Vollbildern und 214 Crops** wird nach `data/collection/` übernommen. Das kleine Demo enthält zwei bereits darin enthaltene Bilder und wird getrennt unter `data/demo/` geöffnet. Die beiden anderen Pakete sind **reservierte Testkandidaten für den Dozenten**; sie gehören nicht in den nachfolgenden Import, in Training oder Validierung. Die ursprünglichen Gruppen der Lernsammlung haben keine Ortstafel-Testabdeckung. Klären Sie deshalb vor dem Modellversuch zusätzliche unabhängige Prüfgruppen und die Bestandsabdeckung mit dem Dozenten.

Für die heruntergeladene Lernsammlung ist kein erneuter Crawl nötig. Wenn Sie später zusätzlich neue Annotationen sammeln, wählen Sie einen neuen Ausgabeordner:

```sh
python crawl_panoramax.py --max-images 100 --output data/collection-neu
```

Dieser optionale Aufruf liest vorhandene Annotationen und öffentliche HD-Bildableitungen aus `panoramax.youspeed.de` nach `data/collection-neu/`. Er schreibt nichts auf den Server. Die folgenden Standardpfade und Importbefehle beziehen sich auf die bereits heruntergeladene Lernsammlung unter `data/collection/`; einen anderen Sammelordner geben Sie beim Import mit `--source` an.

Öffnen und prüfen Sie die Bilder mit ihren Quellmetadaten. Lassen Sie Box und Klasse zusätzlich von einer zweiten Person prüfen. Verschieben Sie richtige Schild-Crops im Dateimanager in die angelegten Klassenordner unter `data/collection/approved/classifier/`:

| Panoramax-Annotation | Modellklasse | Klassenordner |
| --- | --- | --- |
| `osm\|traffic_sign=DE:310` – Ortseingang | `city:start` | `city__start` |
| `osm\|traffic_sign=DE:311` – Ortsausgang | `city:end` | `city__end` |

Der Zielordner bestätigt die Klasse; der gespeicherte Modellvorschlag kann falsch sein. Unklare Bilder bleiben in `inbox` und werden nicht importiert. Verschieben Sie Detektorbeispiele nur als vollständiges Paket aus `image.png`, `labels.txt` und `metadata.json`, nachdem **alle** Schild-, Kennzeichen- und Gesichtsboxen geprüft wurden. Fehlende oder falsche Boxen korrigieren Sie in Panoramax und exportieren den korrigierten Stand erneut.

Die ausführliche [Anleitung zum Sammeln und Sortieren](SAMMELN_UND_SORTIEREN.md) zeigt die Ordner, konkrete Verschiebebefehle, die vollständige Boxprüfung und die Gruppenfestlegung. Lesen Sie sie vor der Freigabe. Öffentliche Bilder sind häufig bereits verwischt; sie belegen keine Detektionsqualität unverpixelter Gesichter und Kennzeichen.

Importieren Sie anschließend die geprüfte Auswahl zusammen mit dem bereitgestellten Bestandskorpus:

```sh
python import_sorted_folders.py \
  --include-annotations data/annotations.csv \
  --include-images data/raw/images
```

Der Importer erzeugt `data/reviewed/classifier/annotations.csv` und `data/reviewed/classifier/images/`. Er verwendet ganze Sequenzen als Gruppen; zugehörige Vollbilder und Crops bleiben zusammen. Gleiche physische Tafeln, Fahrten und Nahe-Duplikate über mehrere Sequenzen müssen Sie mit dem Dozenten vorher zusammenfassen. Geben Sie dafür zusätzlich `--groups data/groups.csv` an; das Format steht in der Sammelanleitung. Das Skript erkennt diese Beziehungen nicht selbst. `data/reviewed/` muss für den Import ein neuer Ausgabeordner sein.

## 3. Trainings-, Validierungs- und Testdaten erzeugen

```sh
python prepare_dataset.py \
  --annotations data/reviewed/classifier/annotations.csv \
  --images data/reviewed/classifier/images
```

Das Skript prüft die Liste und erzeugt den Ordner `data/dataset/`:

```text
data/dataset/
  train/<klasse>/...        # daraus lernt das Modell
  val/<klasse>/...          # damit wählen Sie den Kandidaten
  test/<klasse>/...         # unabhängiger Abschlusstest
  class-index.json
  manifest.json
```

Die Zielaufteilung beträgt **70 % Training, 15 % Validierung und 15 % Test**. Sie wird mit einem festen Seed auf ganze Gruppen angewandt. Deshalb können die tatsächlichen Bildanteile abweichen. Ein Crop wird nicht in mehrere Teile kopiert, um die Prozentwerte zu erreichen.

`manifest.json` dokumentiert Bilder, Klassen, Gruppen, Aufteilung und Prüfsummen. Alle 136 Klassen müssen im Training vertreten sein; die Validierungs- und Testpartition dürfen insgesamt nicht leer sein. Ein Fehler stoppt den Ablauf. Fehlende Beispiele einzelner Klassen in `val` oder `test` werden als Warnung sichtbar. Das bedeutet noch keine Freigabe: Für den vollständigen Bestandsvergleich benötigt jede der 134 alten Klassen geeignete unabhängige Prüfbeispiele. Klären Sie fehlende Abdeckung mit dem Dozenten. Verschieben Sie nicht nachträglich Testbilder ins Training.

## 4. Das Modell trainieren

```sh
python train.py --epochs 20
```

Eine **Epoche** ist ein Durchlauf durch die Trainingsbilder. Beim Training werden die Gewichte des Netzes anhand der bekannten Klassen angepasst. Der Klassifikationskopf erhält zwei zusätzliche Ausgänge. Die vorhandenen Klassen und ihre Reihenfolge bleiben dokumentiert.

Das Skript verwendet standardmäßig `models/baseline.pt`, `data/dataset/`, Batchgröße 16 und das im Kurs zugewiesene CUDA-Gerät. Es skaliert jeden vollständigen RGB-Crop auf 224 × 224 Pixel und teilt die Pixelwerte durch 255. Ein zufälliger Ausschnitt oder CenterCrop soll den wichtigen Diagonalstrich einer Ausgangstafel nicht entfernen.

Fortschrittsmeldungen erscheinen im Terminal. Der Versuch wird unter `runs/versuch-01/` gespeichert. `progress.csv` enthält pro Epoche den Trainingsfehler (`train_loss`), den Anteil richtiger Validierungsvorhersagen (`val_accuracy`) und den mittleren F1-Wert der unterstützten Validierungsklassen (`val_macro_f1`). Das ausgewählte Modell liegt hier:

```text
runs/versuch-01/weights/best.pt
```

Diese Datei enthält die trainierten Gewichte und Metadaten im Format dieses Praktikums. Verwenden Sie zum Laden und Vergleichen das zugehörige `evaluate.py`; sie ist kein gewöhnlicher Ultralytics-CLI-Checkpoint.

Die Validierungsdaten helfen bei der Auswahl. Die Testdaten bleiben dabei unangetastet. 20 Epochen sind ein einfacher Startwert für den Kurs, keine Garantie für ein gutes Modell. Wenn die GPU oder eine Quelldatei fehlt, lesen Sie die Fehlermeldung und prüfen Sie den Kurszugang mit dem Dozenten.

## 5. Mit dem Ausgangsmodell vergleichen

### Precision, Recall und F1 verstehen

Das folgende **frei erfundene Rechenbeispiel** entspricht Folie 22. Es zeigt keine Ergebnisse unseres Trainings. Jeder der zehn Bildausschnitte enthält genau eine Ortstafel. Die Box ist bereits vorgegeben; wir bewerten ausschließlich die zugeordnete Klasse. Das Beispielmodell unterscheidet nur **DE:310 = Ortseingang** und **DE:311 = Ortsausgang**.

Die Zeilen nennen die tatsächliche Klasse, die Spalten die Vorhersage des Modells:

| Tatsächliche Klasse | Vorhersage DE:310 | Vorhersage DE:311 | Anzahl echter Beispiele |
| --- | ---: | ---: | ---: |
| DE:310 Ortseingang | 4 | 2 | 6 |
| DE:311 Ortsausgang | 1 | 3 | 4 |
| Anzahl Vorhersagen | 5 | 5 | 10 |

Betrachten Sie zunächst DE:310. Vier Ortseingänge sind richtig zugeordnet. Ein Ortsausgang wurde fälschlich als Ortseingang gemeldet. Zwei echte Ortseingänge wurden als Ortsausgang eingeordnet.

- **Precision (P): Wie viele Vorhersagen dieser Klasse stimmen?** Teilen Sie die richtigen Zuordnungen durch alle Vorhersagen dieser Klasse. Für DE:310: `4 / (4 + 1) = 4/5 = 80 %`.
- **Recall (R): Wie viele tatsächlich vorhandene Beispiele dieser Klasse werden richtig zugeordnet?** Teilen Sie die richtigen Zuordnungen durch alle echten Beispiele dieser Klasse. Für DE:310: `4 / (4 + 2) = 4/6 ≈ 66,7 %`.
- **F1 verbindet Precision und Recall.** Das harmonische Mittel lautet `F1 = 2 × P × R / (P + R)`. Verwenden Sie P und R als ungerundete Anteile zwischen 0 und 1. F1 ist nur hoch, wenn beide Werte hoch sind; es ist nicht das einfache arithmetische Mittel.

Mit Anzahlen können Sie F1 direkt berechnen:

```text
F1 = 2 × richtig / (2 × richtig + falsch als diese Klasse gemeldet
                  + echte Beispiele als andere Klasse eingeordnet)
```

Für DE:310 ergibt das `2 × 4 / (2 × 4 + 1 + 2) = 8/11 ≈ 72,7 %`. Wechseln Sie nun den Blick auf DE:311: drei richtige Zuordnungen, zwei fälschlich als DE:311 gemeldete Ortseingänge und ein als DE:310 eingeordneter Ortsausgang.

| Betrachtete Klasse | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| DE:310 | 4/5 = 80 % | 4/6 ≈ 66,7 % | 8/11 ≈ 72,7 % |
| DE:311 | 3/5 = 60 % | 3/4 = 75 % | 6/9 ≈ 66,7 % |

Die Kennzahlen werden **je Klasse** berechnet. Beim tatsächlichen Modell mit 136 Klassen zählen alle anderen Klassen als Gegenklassen der gerade betrachteten Klasse. Ein F1-Wert von `0,80` im Auswertungsbericht bedeutet `80 %`. Auf Folie 22 sind die Prozentwerte auf ganze Zahlen gerundet; hier sehen Sie eine Nachkommastelle. Die Definitionen finden Sie auch in der [scikit-learn-Dokumentation](https://scikit-learn.org/stable/modules/model_evaluation.html#precision-recall-f-measure-metrics).

### Kleine Übung: ein weiterer Modellstand

**Dauer: etwa 5–8 Minuten.** Ein zweites, ebenfalls erfundenes Modell klassifiziert dieselben zehn Bildausschnitte so:

| Tatsächliche Klasse | Vorhersage DE:310 | Vorhersage DE:311 | Anzahl echter Beispiele |
| --- | ---: | ---: | ---: |
| DE:310 Ortseingang | 5 | 1 | 6 |
| DE:311 Ortsausgang | 2 | 2 | 4 |

1. Notieren Sie für jede Klasse die Anzahl richtiger Zuordnungen, falscher Meldungen und als andere Klasse eingeordneter echter Beispiele.
2. Berechnen Sie Precision, Recall und F1 für beide Klassen. Geben Sie jeweils einen Bruch und einen Prozentwert mit einer Nachkommastelle an. Runden Sie erst am Ende.
3. Vergleichen Sie die F1-Werte mit dem ersten Beispiel. Beide Modelle ordnen insgesamt 7 von 10 Bildern richtig zu. Erklären Sie, warum diese Gesamtzahl die Veränderung nicht ausreichend beschreibt.
4. Reichen diese zehn Bildausschnitte für eine Freigabe des tatsächlichen Kursmodells mit 136 Klassen? Begründen Sie Ihre Antwort anhand der bisherigen 134 Klassen und der getrennten Detektoraufgabe.

| Klasse | Richtige Zuordnungen | Falsche Meldungen | Echte Beispiele als andere Klasse | Precision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DE:310 | … | … | … | … | … | … |
| DE:311 | … | … | … | … | … | … |

Halten Sie die ausgefüllte Tabelle und Ihre kurze Begründung als Teil Ihrer Abgabe fest. Der Dozent bespricht die Lösung anschließend mit Ihnen.

### Die Modellberichte lesen

Zuerst vergleichen Sie beide Modelle auf der **Validierung**:

```sh
python evaluate.py --candidate runs/versuch-01/weights/best.pt
```

Die Berichte entstehen standardmäßig unter `reports/versuch-01/`. Öffnen Sie zuerst **`BERICHT.md`**. `metrics.json` enthält die Messwerte, `regression-gate.json` das Ergebnis der Bestandsprüfung und `old-only-per-class.csv` deren Klassenvergleich. Weitere CSV-Dateien dokumentieren Verwechslungen und einzelne Vorhersagen. Das alte Modell hat keine eigenen Ortstafelklassen. Seine Ergebnisse werden anhand der Klassennamen verglichen; die zwei neuen Klassen werden nicht durch Umdeuten von `bad` vorgetäuscht.

Lesen Sie insbesondere:

- **Recall:** Wie viele echte Ortseingangs- beziehungsweise Ortsausgangstafeln wurden richtig klassifiziert?
- **Precision:** Wie viele als Ortseingang beziehungsweise Ortsausgang klassifizierte Bilder waren tatsächlich solche Tafeln?
- **F1:** Wie gut sind Precision und Recall gemeinsam? Vergleichen Sie den Wert für jede Klasse getrennt.
- **Verwechslungen:** Welche falschen Klassen wurden vorhergesagt? Verwechselt das Modell die beiden Ortstafeln oder gelbe Wegweiser?
- **Bestandsklassen:** Welche bisherigen Zeichen erkennt der Kandidat schlechter als das Ausgangsmodell?

Für den Bestandsvergleich verwendet das Auswerteskript bei beiden Modellen **dieselben zurückgehaltenen Bilder alter Klassen**. Es prüft Recall und F1 für jede einzelne der 134 Bestandsklassen. Mehr richtige Ortstafeln gleichen einen Rückgang bei bisherigen Zeichen nicht aus.

- **REGRESSION:** Mindestens eine alte Klasse wird nach dem festgelegten Recall-/F1-Vergleich schlechter. Der Kandidat besteht die Prüfung nicht; die Berichte bleiben zur Fehleranalyse erhalten.
- **UNVOLLSTAENDIG:** Für mindestens eine alte Klasse fehlen Prüfbeispiele. Dann ist eine vollständige Aussage zur Bestandsqualität nicht möglich; der Kandidat besteht diese Prüfung ebenfalls nicht.
- **BESTANDEN:** Alle alten Klassen sind im Vergleich vertreten, und keine fällt unter die festgelegten Recall-/F1-Werte der Baseline. Die Qualität der beiden neuen Klassen ist zusätzlich im Bericht zu beurteilen.

Bei `REGRESSION` oder `UNVOLLSTAENDIG` endet das Programm mit Rückgabecode 3, nachdem es alle Berichte geschrieben hat. Ein Vergleich ohne gemessenen Rückgang gilt für diesen dokumentierten Testsatz. Er garantiert keine Fehlerfreiheit auf allen zukünftigen Straßenbildern. Zeigen Sie deshalb auch die Beispielzahlen und konkrete Fehlbilder. Der Dozent legt die erforderliche Datenabdeckung vor dem Training fest.

Wenn Sie eine weitere Variante erproben, wählen Sie einen neuen Ausgabeordner und dokumentieren Sie die Änderung. Wählen Sie den endgültigen Kandidaten anhand der Validierung. Führen Sie erst danach den Abschlusstest aus:

```sh
python evaluate.py --candidate runs/versuch-01/weights/best.pt \
  --split test --output reports/abschluss
```

Dieser Test beantwortet, wie der gewählte Kandidat auf den zurückgehaltenen Schildgruppen abschneidet. Nutzen Sie sein Ergebnis nicht zur nächsten Epochenwahl. Ein guter Crop-Test belegt noch nicht, dass die komplette App auf einer neuen Strecke alle Schilder findet.

## Ihre Abgabe

Geben Sie den dokumentierten Datensatzstand, den Versuch unter `runs/versuch-01/`, den Abschlussbericht und eine kurze Erklärung ab: **Was wurde besser? Was wurde schlechter? Welche Fehlbilder erklären das?** Nennen Sie die Anzahl verschiedener physischer Ortstafeln, nicht nur die Zahl der Fotos.

Der Modellkandidat wird hier offline geprüft. Seine Konvertierung nach Core ML und LiteRT und die Integration in beide Apps sind nachfolgende Projektschritte. Prolix führt Modelle aus und verarbeitet Annotationen; die Trainingsskripte dieses Praktikums übernehmen Datenaufteilung, Training und Qualitätsvergleich. Bewahren Sie zusätzlich die Sammel- und Importmanifeste mit Quellen, Lizenzen und Gruppen als Teil Ihrer Abgabe auf.
