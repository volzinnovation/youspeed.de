# Bildklassifikation mit KI

## Wie verbessere ich ein vorhandenes KI-Modell?

**Montag, 26. Oktober 2026 · Für das 3. Semester ohne ML-Vorkenntnisse**

Sie erweitern den deutschen Klassifikator von **134 auf 136 Klassen**: **Ortseingang `DE:310`** und **Ortsausgang `DE:311`** kommen hinzu. Sie arbeiten mit geprüften Schild-Crops. Die Suche nach Schildern im vollständigen Straßenbild ist eine getrennte Aufgabe des Detektors.

Beginnen Sie mit der [Schritt-für-Schritt-Anleitung im Praktikumsordner](praktikum/README.md). Die [Downloadanleitung für den KI-Server](praktikum/DATEN_HERUNTERLADEN.md) zeigt die konkreten Befehle für den öffentlichen Datensatz [loffenauer/ws26_hspf_imo](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo), die Prüfsummenprüfung und das Entpacken. Die [Anleitung zum Sammeln und Sortieren](praktikum/SAMMELN_UND_SORTIEREN.md) erklärt anschließend die Klassenordner, die vollständige Boxprüfung und einen optionalen neuen Crawl. Der Ordner enthält ausführbare Skripte und eine feste [Klassenliste](praktikum/class-index.json).

Vor dem Modellvergleich bearbeiten Sie das [Rechenbeispiel und die kurze Übung zu Precision, Recall und F1](praktikum/README.md#precision-recall-und-f1-verstehen). Sie berechnen die Werte für DE:310 und DE:311 und untersuchen, warum dieselbe Gesamtzahl richtiger Vorhersagen unterschiedliche Klassenqualität verdecken kann. Die Zahlen sind erfunden und von den tatsächlichen Trainingsmessungen getrennt.

## Was der Dozent vorher bereitstellt

Benötigt werden die eingerichtete Kursumgebung, eine zugewiesene GPU, das geprüfte Ausgangsmodell unter `praktikum/models/baseline.pt` sowie kuratierte Crops, Labels und Gruppenkennungen der **134 Bestandsklassen**. Sie ergänzen menschlich geprüfte Beispiele für die zwei Ortstafelklassen. Die öffentlichen Panoramax-Pakete sind jetzt herunterladbar; Modellcheckpoint und vollständiger geprüfter Bestandskorpus werden weiterhin separat vom Dozenten bereitgestellt. Ihre Zusammenstellung ist Teil der [Lehrvorbereitung](LEHRVORBEREITUNG.md).

Der bereitgestellte Bestandskorpus liegt als `data/annotations.csv` und geprüfte Schild-Crops unter `data/raw/images/` vor. Der Crawler ergänzt diesen Bestand; er garantiert keine Abdeckung aller Klassen. `group_id` hält dieselbe physische Tafel, zusammengehörende Fahrten und geprüfte Nahe-Duplikate gemeinsam. Sequenzen bleiben beim Import zusammen; Beziehungen über mehrere Sequenzen legen Sie vorher mit dem Dozenten fest. Die Skripte erkennen diese Beziehungen nicht selbst.

## Der konkrete Ablauf

Wechseln Sie vom Repository-Hauptordner in den vorbereiteten Arbeitsordner:

```sh
cd lectures/tsr-sgblur-de-2026-10-26/praktikum
```

Laden Sie nach der [Downloadanleitung](praktikum/DATEN_HERUNTERLADEN.md) die Lernsammlung mit **100 Vollbildern und 214 Crops** auf den KI-Server. Verwenden Sie den festgelegten Datensatzstand `6837ae4fae0d1d216612afa739c9dfefd6b277ab`, prüfen Sie die ZIP-Prüfsumme und übernehmen Sie den tatsächlichen Archivordner nach `data/collection/`. Der Download benötigt keinen Hugging-Face-Login. Alle Beispiele bleiben zunächst ungeprüft.

Die dort getrennt beschriebenen Pakete mit eigenen und externen **Testkandidaten sind für den Dozenten reserviert**. Geben Sie diese nicht an den normalen Importer und verwenden Sie sie nicht für Training oder Validierung. Auch die Lernsammlung benötigt zusätzliche unabhängige Ortstafel-Testgruppen; unter ihren ursprünglichen Sequenzgruppen besteht keine Ortstafel-Testabdeckung.

Wenn Sie später zusätzlich neue vorhandene Annotationen sammeln, verwenden Sie einen **neuen** Ausgabeordner:

```sh
python crawl_panoramax.py --max-images 100 --output data/collection-neu
```

Die folgenden Standardpfade beziehen sich auf die heruntergeladene Lernsammlung. Prüfen Sie deren Bilder und Metadaten. Verschieben Sie geeignete Crops nach `data/collection/approved/classifier/<klassenordner>/`; beispielsweise nach `city__start/` für Ortseingang oder `city__end/` für Ortsausgang. Unklare Bilder bleiben ausgeschlossen. Detektorbeispiele verschieben Sie nur als ganzes Drei-Dateien-Paket nach `approved/detector/`, nachdem alle Schild-, Kennzeichen- und Gesichtsboxen geprüft wurden. Fehlende oder falsche Boxen müssen in Panoramax korrigiert und neu exportiert werden. Der optionale Crawler führt nur Lesezugriffe aus und macht einen begrenzten Lauf, kein vollständiges Inventar. Für `data/collection-neu/` geben Sie beim Import ausdrücklich den passenden `--source` an.

Importieren Sie die geprüfte Auswahl gemeinsam mit dem Bestandskorpus und starten Sie anschließend den Klassifikatorversuch:

```sh
python import_sorted_folders.py \
  --include-annotations data/annotations.csv \
  --include-images data/raw/images
python prepare_dataset.py \
  --annotations data/reviewed/classifier/annotations.csv \
  --images data/reviewed/classifier/images
python train.py --epochs 20
python evaluate.py --candidate runs/versuch-01/weights/best.pt
```

Ergänzen Sie beim Import `--groups data/groups.csv`, wenn zusammengehörende Sequenzen festgelegt wurden. Die Sammelanleitung erklärt die Datei und die Ordnerfreigabe. Für einen weiteren Import muss ein neuer Ausgabeordner gewählt werden.

[prepare_dataset.py](praktikum/prepare_dataset.py) erzeugt den eingefrorenen Datensatz mit einer gruppierten Zielaufteilung von **70 % Training, 15 % Validierung und 15 % Test** und dem festen Seed `20261026`. Alle 136 Trainingsklassen müssen vertreten sein. Fehlende Daten ergeben eine konkrete Fehlermeldung; Testbilder werden nicht nachträglich ins Training verschoben.

[train.py](praktikum/train.py) trainiert mit vollständigem RGB-Resize auf **224 × 224 Pixel** und Pixelwerten geteilt durch **255**. Es dokumentiert die Klassenreihenfolge, schreibt Fortschritt und Checkpoints und verwendet die Validierung zur Kandidatenwahl. Die Testbilder werden dabei nicht ausgewertet. 20 Epochen sind ein Startwert, keine Qualitätsgarantie.

[evaluate.py](praktikum/evaluate.py) vergleicht Ausgangsmodell und Kandidat auf denselben Bildern. Öffnen Sie anschließend `reports/versuch-01/BERICHT.md`. Neben Precision, Recall, F1 und Fehlbildern prüft es **jede der 134 Bestandsklassen** auf Rückgänge bei Recall und F1. Eine Regression oder fehlende Bestandsabdeckung ergibt einen nicht bestandenen Vergleich und Rückgabecode **3**; die Berichte bleiben erhalten. Ein Gewinn bei Ortstafeln gleicht einen Rückgang bei bestehenden Zeichen nicht aus.

Wählen Sie den endgültigen Kandidaten anhand der Validierung. Erst danach führen Sie den Abschlusstest aus:

```sh
python evaluate.py --candidate runs/versuch-01/weights/best.pt \
  --split test --output reports/abschluss
```

Verwenden Sie für eine weitere Variante einen neuen Versuchsordner. Die vollständigen Erläuterungen zu Eingaben, Ausgaben und Fehlerfällen stehen in der [Praktikumsanleitung](praktikum/README.md).

## Getrennter Versuch für fehlende Detektorboxen

Der Importer erzeugt außerdem `data/reviewed/detector/data.yaml` mit Vollbildern, Boxdateien und der festen Belegung `0=sign`, `1=plate`, `2=face`. Ein optionales Detektortraining verwendet den vom Dozenten bereitgestellten Drei-Klassen-Checkpoint `models/detector-baseline.pt`, nicht das Klassifikator-Ausgangsmodell. Die [Sammelanleitung](praktikum/SAMMELN_UND_SORTIEREN.md) enthält die konkreten YOLO-Befehle und den unabhängigen Vergleich aller drei Klassen. Öffentliche Bilder sind häufig bereits verwischt und belegen keine Gesichts-/Kennzeichendetektion auf unverpixelten Bildern.

## Was bereits geprüft wurde

Ein echter GPU-Versuch vom **20. Oktober 2026** ergänzt die technischen Probeläufe: TSR wurde 20 Epochen trainiert und erkennt 14/15 zurückgehaltene Ortstafel-Crops richtig. Der Kandidat besteht den Vergleich der 134 alten Klassen wegen Rückgängen einzelner Klassen nicht. Ein begrenzter SGBlur-Anpassungslauf und ein zusätzlicher Test der tatsächlichen Box→Crop→Klasse-Kette sind ebenfalls abgeschlossen. Die [Trainings- und Testergebnisse](TRAININGSERGEBNISSE-2026-10-20.md) trennen diese Messungen, Datenqualitätsgrenzen und die noch fehlende Prüfung unverpixelter Gesichter/Kennzeichen. Das ersetzt den vor dem Kurs benötigten menschlich geprüften, nach Standorten/Fahrten gruppierten Bestandskorpus nicht.

**27 automatisierte Tests** und ein **synthetischer CPU-Probelauf der tatsächlichen Trainings- und Auswertungsbefehle mit Ultralytics 8.4.56** haben Datenvertrag, Kopfänderung, Optimizer-Schritte, Speichern/Laden und Berichtserzeugung geprüft. Die unvollständige Bestandsabdeckung der synthetischen Prüfpartitionen wurde korrekt mit Rückgabecode 3 gemeldet. [Prüfbeleg](source/praktikum-exact-cli-smoke.json).

Diese Prüfung ist keine Qualitätsbewertung echter Verkehrszeichen und kein Nachweis mobiler Erkennung. Ein guter Cropvergleich belegt außerdem nicht, dass der Detektor im Vollbild alle Schilder findet. Server-/Geräteintegration und Konvertierung nach Core ML und LiteRT folgen erst nach dem dokumentierten Modellvergleich.

## Ihre Abgabe

Geben Sie den Datensatzstand mit Sammel-/Importmanifesten, Quellen, Lizenzen und Gruppen, den Trainingsversuch, den Abschlussbericht und eine kurze Erklärung ab: **Was wurde besser, was wurde schlechter und welche Fehlbilder erklären das?** Nennen Sie die Anzahl unterschiedlicher physischer Ortstafeln zusätzlich zur Bildanzahl. Der Modellkandidat verändert keine produktive App und keine geschützte Geschwindigkeitsreferenz-Policy.

Die erweiterte Sammlung und Ordnerprüfung sind mit **70 lokalen Tests** sowie einem begrenzten Live-Crawl mit zwei Vollbildern und sechs ungeprüften Crops geprüft. Der zusätzliche synthetische Ablauf verwendet alle 136 Klassen und hält Vollbild und Crops im gleichen Split. [Prüfbeleg](source/collection-smoke-evidence.json). Die kleine Live-Sammlung ist eine Übungsreserve für die Prüfung und das Einsortieren; sie ersetzt keinen vollständigen Kursdatensatz.
