# Panoramax-Daten auf den KI-Server herunterladen

Diese Anleitung verwendet den öffentlichen Datensatz [loffenauer/ws26_hspf_imo](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo). Sie benötigen dafür weder ein Hugging-Face-Konto noch einen Token. Sie laden die Daten direkt im Terminal Ihres KI-Server-Zugangs herunter; ein vorheriger Download auf Ihren eigenen Rechner ist nicht erforderlich.

Alle Befehle verwenden den festgelegten Datensatzstand **`e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8`**. Damit beziehen alle Kursteilnehmenden dieselben Dateien. Die Pakete enthalten **ungeprüfte Beispiele und Vorschläge, keine menschlich freigegebene Ground Truth**. Der Modellcheckpoint und der kuratierte Korpus der 134 Bestandsklassen werden zusätzlich vom Dozenten bereitgestellt.

## 1. Vollständige Lernsammlung und Arbeitsordner

| Paket | Inhalt | Verwendung |
| --- | --- | --- |
| `panoramax-studenten-2026-10-19.zip` | 100 Vollbilder, 214 Schild-Crops, 27 Sequenzen | Lernsammlung: herunterladen, prüfen und einsortieren; anschließend mit dem bereitgestellten Bestandskorpus zusammenführen. |
| `panoramax-mobidata-bw-review-2026-10-20-v2.zip` | 57 Original-Vollbilder, 57 Crops, 53 Sequenzen; 37 DE:310- und 20 DE:311-Vorschläge | **Zweiter Lerndatensatz: MobiData BW.** Getrennte Sichtung und manueller Review; vor dem Import ist ein passender Export nötig. |
| `panoramax-mobidata-bw-review-2026-10-20-additions.zip` | 63 weitere Original-Vollbilder und 63 Crops aus 63 neuen Sequenzen; 58 DE:310- und 5 DE:311-Vorschläge | **Ergänzung zu Datensatz 2.** Ebenfalls herunterladen; eigener Sichtungsordner und manueller Review vor dem Kurs-Export. |
| `panoramax-beispiele-v6.zip` | 2 Vollbilder und 6 Crops; Teilmenge der Lernsammlung | Kleiner technischer Einstieg. Die Ortstafel-Crops sind nur 27 × 22 beziehungsweise 27 × 17 Pixel groß. |
| `panoramax-testkandidaten-2026-10-20.zip` | 39 HD-Vollbilder, 77 Crops; außerdem 246 SD-Bilder derselben acht Sequenzen | Für den Dozenten und einen späteren gesonderten Abschlusstest reserviert. Die 39 HD-Bilder sind eine Teilmenge der 246 SD-Bilder. |
| `panoramax-externe-testkandidaten-2026-10-20.zip` | 15 Zielansichten: 2 Ortseingangs- und 13 Ortsausgangsvorschläge; 13 Standortkandidaten, 12 konservative Gruppen | Ebenfalls reserviert. 11 native 2D-Ansichten und 4 Perspektivansichten aus Panoramen; keine bestätigten unabhängigen Testfälle. |

Die **vollständige Lernsammlung besteht aus drei Archiven**: Datensatz 1 sowie MobiData BW v2 und die zusätzliche 63er-Sammlung. Zusammen sind das **220 Vollbilder und 334 unterschiedliche Crop-Dateien**. **190 Ortstafel-Kandidaten** tragen Quell-Tags beziehungsweise visuelle Vorschläge: **144 DE:310 und 46 DE:311**. Dies sind keine bestätigten Klassenlabels oder unabhängigen Standorte. Fünf Ortstafel-Crops in Datensatz 1 besitzen gemischte Quell-Tags und benötigen besondere Prüfung.

[LEARNING_COLLECTION.json](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8/LEARNING_COLLECTION.json) benennt die drei Lernarchive samt Prüfsummen und Archivwurzeln. Laden Sie alle drei gemäß Abschnitt 3 herunter. Entpacken Sie Datensatz 1 nach Abschnitt 5 und beide MobiData-Archive getrennt nach Abschnitt 5a. Die Lernarchive benötigen zusammen etwa **1,49 GB**; alle sechs ZIP-Dateien einschließlich Demo und reservierter Pakete etwa **2,54 GB**. Entpackte Daten und Arbeitskopien benötigen weiteren Speicherplatz.

Die beiden reservierten Pakete gehören nicht in Training, Validierung, Epochenwahl oder den normalen 70/15/15-Import. Das kleine Demo ist bereits Teil von Datensatz 1 und wird nicht zusätzlich gezählt.

Wechseln Sie im KI-Server-Terminal vom Repository-Hauptordner in das Praktikum:

```sh
cd lectures/tsr-sgblur-de-2026-10-26/praktikum
mkdir -p data/downloads/packages
tsr_dataset_revision='e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8'
```

Führen Sie die weiteren Befehle im selben Terminal und in diesem Ordner aus. Für Download, Prüfsummen und Entpacken wird keine GPU benötigt.

## 2. Die Download-CLI getrennt installieren

Die folgende zusätzliche Python-Umgebung ist ausschließlich für den Download vorgesehen. Sie benötigt **Python 3.10 oder neuer**; die Lehrumgebung verwendet Python 3.12. Die direkte Verwendung ihrer Programme verändert die aktivierte Trainingsumgebung nicht:

```sh
python3 -m venv .venv-hf
.venv-hf/bin/python -m pip install 'huggingface_hub==1.10.2' \
  'typer==0.24.1' 'click==8.3.2'
.venv-hf/bin/hf download --help
```

Die CLI heißt `hf`. Installieren Sie die drei festgelegten Versionen gemeinsam. Damit steht auch die von dieser CLI benötigte `click`-Abhängigkeit bereit. Aktivieren Sie diese Download-Umgebung nicht anstelle der vom Dozenten vorbereiteten Trainingsumgebung. Hintergrund: [offizielle Hugging-Face-CLI-Dokumentation](https://huggingface.co/docs/huggingface_hub/guides/cli).

## 3. Alle drei Lernarchive herunterladen

```sh
.venv-hf/bin/hf download loffenauer/ws26_hspf_imo \
  packages/panoramax-studenten-2026-10-19.zip \
  packages/panoramax-mobidata-bw-review-2026-10-20-v2.zip \
  packages/panoramax-mobidata-bw-review-2026-10-20-additions.zip \
  LEARNING_COLLECTION.json SHA256SUMS.txt \
  --type dataset --revision "$tsr_dataset_revision" \
  --local-dir data/downloads
```

Die drei ZIP-Dateien liegen anschließend unter `data/downloads/packages/`; Index und Prüfsummenliste unter `data/downloads/`. `--revision` legt den festen Stand fest. Wenn Sie schon ältere Pakete besitzen, laden Sie Index und Prüfsummenliste aus dieser Revision erneut und ergänzen Sie fehlende Archive. Erhalten Sie bereits bearbeitete Sichtungsordner.

Falls Sie die CLI nicht verwenden können, laden diese HTTPS-Befehle dieselben Dateien. Fahren Sie anschließend mit Abschnitt 4 fort:

```sh
tsr_dataset_base="https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/$tsr_dataset_revision"
curl --fail --location --retry 3 \
  --output data/downloads/SHA256SUMS.txt \
  "$tsr_dataset_base/SHA256SUMS.txt" &&
curl --fail --location --retry 3 \
  --output data/downloads/LEARNING_COLLECTION.json \
  "$tsr_dataset_base/LEARNING_COLLECTION.json" &&
curl --fail --location --retry 3 \
  --output data/downloads/packages/panoramax-studenten-2026-10-19.zip \
  "$tsr_dataset_base/packages/panoramax-studenten-2026-10-19.zip" &&
curl --fail --location --retry 3 \
  --output data/downloads/packages/panoramax-mobidata-bw-review-2026-10-20-v2.zip \
  "$tsr_dataset_base/packages/panoramax-mobidata-bw-review-2026-10-20-v2.zip" &&
curl --fail --location --retry 3 \
  --output data/downloads/packages/panoramax-mobidata-bw-review-2026-10-20-additions.zip \
  "$tsr_dataset_base/packages/panoramax-mobidata-bw-review-2026-10-20-additions.zip"
```

## 4. Prüfsumme vor dem Entpacken vergleichen

Die veröffentlichte Liste enthält auch Dateien für Demo und reservierte Tests. Der folgende Befehl wählt **genau die drei Lernarchive und den Sammlungsindex** aus. Jede erwartete Zeile muss genau einmal vorhanden sein:

```sh
awk '
BEGIN {
  expected["packages/panoramax-studenten-2026-10-19.zip"] = 1
  expected["packages/panoramax-mobidata-bw-review-2026-10-20-v2.zip"] = 1
  expected["packages/panoramax-mobidata-bw-review-2026-10-20-additions.zip"] = 1
  expected["LEARNING_COLLECTION.json"] = 1
}
$2 in expected {print; seen[$2]++}
END {for (path in expected) if (seen[path] != 1) exit 1}
' data/downloads/SHA256SUMS.txt > data/downloads/SHA256SUMS-lern.txt &&
  (cd data/downloads && sha256sum --strict -c SHA256SUMS-lern.txt)
```

Erwartet werden **vier Meldungen mit `OK`**: drei ZIP-Dateien und `LEARNING_COLLECTION.json`. Nur dann dürfen Sie entpacken. Bei einer Abweichung oder einem Downloadfehler stoppen Sie und klären die Ursache mit dem Dozenten. Fehlermeldungen werden nicht mit `--ignore-missing` oder ähnlichen Optionen unterdrückt.

## 5. Die Lernsammlung nach `data/collection/` entpacken

Das Archiv enthält einen obersten Ordner **`panoramax-studenten-2026-10-19/`**. Er muss als Ganzes übernommen werden, damit Manifest, Metadaten, Crops und Vollbilder zusammenbleiben. Die folgende Befehlsfolge bricht vor dem Entpacken ab, wenn `data/collection/` oder der temporäre Entpackordner bereits existiert:

```sh
test ! -e data/collection &&
  test ! -e data/entpackt-lern &&
  python3 -m zipfile -e \
    data/downloads/packages/panoramax-studenten-2026-10-19.zip \
    data/entpackt-lern &&
  mv data/entpackt-lern/panoramax-studenten-2026-10-19 data/collection
```

Wenn ein Zielordner schon existiert, verwenden Sie nach Rücksprache einen neuen Arbeitsordner. Überschreiben oder vermischen Sie keine ältere Sammlung. Prüfen Sie danach die tatsächlichen Pfade:

```sh
ls data/collection/manifest.json
ls data/collection/inbox/classifier
ls data/collection/inbox/detector
```

Lesen Sie `data/collection/BITTE_ZUERST_LESEN.txt`. Setzen Sie anschließend bei [„Schild-Crops ansehen und einer Klasse zuordnen“](SAMMELN_UND_SORTIEREN.md#2-schild-crops-ansehen-und-einer-klasse-zuordnen) fort. Ein zusätzlicher Crawl ist für diese bereits heruntergeladene Lernsammlung nicht nötig. Für eine spätere neue Sammlung wählen Sie einen anderen Crawler-Ausgabeordner.

Nach menschlicher Prüfung und Sortierung importieren Sie die Lernsammlung gemeinsam mit dem bereitgestellten Bestandskorpus:

```sh
python import_sorted_folders.py \
  --source data/collection --output data/reviewed \
  --include-annotations data/annotations.csv \
  --include-images data/raw/images
```

Die beiden Bestandskorpuspfade stammen vom Dozenten, nicht aus den ZIP-Paketen. Ergänzen Sie `--groups data/groups.csv`, wenn zusammengehörende Sequenzen festgelegt wurden. Unter den ursprünglichen Sequenzgruppen und dem unveränderten Seed `20261026` hat die Lernsammlung **keine Ortstafel-Testabdeckung**. Vor dem Modellversuch sind daher zusätzlich geeignete unabhängige Gruppen und die Abdeckung aller 134 Bestandsklassen zu klären. Ein erfolgreicher Download ist keine Trainings- oder Testfreigabe.

## 5a. Zweiter Lerndatensatz: MobiData BW

Zu Datensatz 2 gehören **beide** bereits in Abschnitt 3 geladenen MobiData-Archive:

| Archiv | Umfang | SHA-256 |
| --- | --- | --- |
| [MobiData BW · v2](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8/packages/panoramax-mobidata-bw-review-2026-10-20-v2.zip?download=true) | 114.226.639 Byte; 57 Vollbilder und 57 Crops | `935e5aeceff8b55764fa5ff076777e391ad330a3ed6af74c1111b59c89626729` |
| [MobiData BW · zusätzliche 63 Paare](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8/packages/panoramax-mobidata-bw-review-2026-10-20-additions.zip?download=true) | 119.848.545 Byte; 63 Vollbilder und 63 Crops | `88be269f7c0d06111a5e5822252a40744140c722ff2c211396aef4876501da64` |

Zusammen enthalten sie **120 Crop-/Vollbildpaare** mit **95 DE:310- und 25 DE:311-Vorschlägen**. Entpacken Sie erst nach der erfolgreichen Prüfung in Abschnitt 4. Verwenden Sie getrennte Ordner, damit bestehende Reviews erhalten bleiben.

Für v2:

```sh
test ! -e data/collection-mobidata-bw &&
  test ! -e data/entpackt-mobidata-bw &&
  python3 -m zipfile -e \
    data/downloads/packages/panoramax-mobidata-bw-review-2026-10-20-v2.zip \
    data/entpackt-mobidata-bw &&
  mv data/entpackt-mobidata-bw/panoramax-mobidata-bw-review-2026-10-20 \
    data/collection-mobidata-bw
```

Für die zusätzliche 63er-Sammlung:

```sh
test ! -e data/collection-mobidata-bw-additions &&
  test ! -e data/entpackt-mobidata-bw-additions &&
  python3 -m zipfile -e \
    data/downloads/packages/panoramax-mobidata-bw-review-2026-10-20-additions.zip \
    data/entpackt-mobidata-bw-additions &&
  mv data/entpackt-mobidata-bw-additions/panoramax-mobidata-bw-review-2026-10-20-additions \
    data/collection-mobidata-bw-additions
```

Wenn v2 schon entpackt und bearbeitet ist, erhalten Sie diesen Ordner und führen nur den Ergänzungsblock aus. Entpacken Sie kein Archiv über einen vorhandenen Review.

Öffnen Sie in einer lokalen Arbeitskopie **beide** `SICHTUNG.html`-Dateien:

- `data/collection-mobidata-bw/SICHTUNG.html`
- `data/collection-mobidata-bw-additions/SICHTUNG.html`

Die Ansichten verlinken Crops, unveränderte Vollbilder und Boxüberlagerungen. Dokumentieren Sie Ihre Prüfung in den jeweiligen `SICHTUNG_CROPS.csv` (`reviewed_class`, `reviewer`, `review_note`, `approved`) und `SICHTUNG_VOLLBILDER.csv`. Lassen Sie Klasse und Box zusätzlich von einer zweiten Person prüfen. Unsichere Beispiele bleiben ungeprüft; der Registercode ist keine bestätigte Bildklasse.

**Beide MobiData-Pakete benötigen einen geprüften Kurs-Export.** Jedes Manifest setzt `normal_course_importer_compatible=false`. Vollbilder enthalten `image.jpg` und `box-proposals.json` mit einzelnen Zielboxen; die vollständigen Drei-Klassen-Labels des normalen Detektorimports fehlen. Benennen Sie Dateien nicht lediglich um und übergeben Sie diesen Ordner nicht unverändert an `import_sorted_folders.py`.

Übernehmen Sie nach abgeschlossener Prüfung nur bestätigte Klassifikator-Crops in einen gesonderten Kurs-Export. Erstellen Sie dafür die in `prepare_dataset.py` erwartete CSV mit `image_path,label,group_id`, erhalten Sie die Zuordnung zu Quelle, Vollbild, Autor, Lizenz und Hash und führen Sie die Auswahl erst dann mit den bereitgestellten Bestandsklassen zusammen. Für den Detektor ergänzen und prüfen Sie **alle** sichtbaren Schilder, Kennzeichen und Gesichter und exportieren Sie vollständige Bild-/Label-/Metadatenpakete im Kursformat. Stimmen Sie diesen Export mit dem Dozenten ab.

Gleiche Tafeln, nahe Ansichten und mögliche gemeinsame Fahrten müssen in derselben Gruppe bleiben, auch über alle drei Lernarchive hinweg. Die enthaltenen Gruppen sind Vorschläge. Legen Sie geeignete Validierungs- und Testgruppen für **beide** Ortstafelklassen vor dem Training fest. Das gezielt zusammengestellte Sichtungsmaterial ist kein blinder Abschlusstest. Berechnen Sie Ihre Modellresultate selbst; die Pakete enthalten keine trainierten Modellkandidaten oder fertige Musterlösung.

## 6. Optional: das kleine Demo getrennt öffnen

Laden Sie das Demo und die Prüfsummenliste herunter:

```sh
.venv-hf/bin/hf download loffenauer/ws26_hspf_imo \
  packages/panoramax-beispiele-v6.zip SHA256SUMS.txt \
  --type dataset --revision "$tsr_dataset_revision" \
  --local-dir data/downloads
awk '$2 == "packages/panoramax-beispiele-v6.zip" {print; n++} END {if (n != 1) exit 1}' \
  data/downloads/SHA256SUMS.txt > data/downloads/SHA256SUMS-demo.txt &&
  (cd data/downloads && sha256sum --strict -c SHA256SUMS-demo.txt)
```

Entpacken Sie erst nach `OK` in einen neuen Ordner:

```sh
test ! -e data/demo &&
  python3 -m zipfile -e \
    data/downloads/packages/panoramax-beispiele-v6.zip data/demo
```

Die Sammlung liegt tatsächlich unter **`data/demo/collection-demo/`**; daneben liegt `BEISPIELE_LESEN.txt`. Für einen getrennten technischen Ordnerimport nach erfolgter Prüfung lautet der Quellpfad daher `--source data/demo/collection-demo` und beispielsweise der neue Ausgabepfad `--output data/reviewed-demo`. Die beiden Demo-Bilder sind bereits Teil der großen Lernsammlung. Übernehmen Sie sie nicht ein zweites Mal in denselben Versuch.

## 7. Nur für den Dozenten: Testkandidaten getrennt reservieren

Die folgenden Befehle laden die zwei Testkandidatenpakete. Verwenden Sie dafür ausschließlich den hier benannten reservierten Ordner; er wird nicht als Quelle an den normalen Importer übergeben:

```sh
.venv-hf/bin/hf download loffenauer/ws26_hspf_imo \
  packages/panoramax-testkandidaten-2026-10-20.zip \
  packages/panoramax-externe-testkandidaten-2026-10-20.zip SHA256SUMS.txt \
  --type dataset --revision "$tsr_dataset_revision" \
  --local-dir data/downloads
awk '$2 == "packages/panoramax-testkandidaten-2026-10-20.zip" || $2 == "packages/panoramax-externe-testkandidaten-2026-10-20.zip" {print; seen[$2]++} END {if (seen["packages/panoramax-testkandidaten-2026-10-20.zip"] != 1 || seen["packages/panoramax-externe-testkandidaten-2026-10-20.zip"] != 1) exit 1}' \
  data/downloads/SHA256SUMS.txt > data/downloads/SHA256SUMS-testkandidaten.txt &&
  (cd data/downloads && sha256sum --strict -c SHA256SUMS-testkandidaten.txt)
```

Entpacken Sie nur, wenn **beide** Dateien mit `OK` bestätigt wurden:

```sh
test ! -e data/teacher-reserved &&
  mkdir data/teacher-reserved &&
  python3 -m zipfile -e \
    data/downloads/packages/panoramax-testkandidaten-2026-10-20.zip \
    data/teacher-reserved &&
  python3 -m zipfile -e \
    data/downloads/packages/panoramax-externe-testkandidaten-2026-10-20.zip \
    data/teacher-reserved
```

Darunter liegen die separaten Archivordner `panoramax-testkandidaten-2026-10-20/` und `panoramax-externe-testkandidaten-2026-10-20/`. Lesen Sie deren `BITTE_ZUERST_LESEN.txt`, `STATUS.json` und Herkunftsmanifeste. Es gibt **0 menschlich freigegebene Testfälle**. Originaltags wie `FR:EB20` und `yes` bleiben erhalten; lokale DE:310-/DE:311-Vorschläge sind getrennt dokumentiert.

Reservieren Sie alle Ansichten derselben Tafel und mögliche zusammengehörige Fahrten gemeinsam. Prüfen Sie Boxen, Klassen, Eignung und Unabhängigkeit gegen den vollständigen späteren Trainingsbestand. Die vier zielzentrierten Perspektivbilder sind getrennt von den elf nativen 2D-Ansichten auszuwerten. Ein eigener eingefrorener Testexport und ein passender Evaluationsmodus fehlen noch; der vorhandene Kursevaluator ist an das ursprüngliche Trainingsmanifest gebunden. Umgehen Sie diese Bindung nicht durch geänderte Checkpoint-Metadaten. Das unabhängige Regressionsgate aller 134 Bestandsklassen bleibt zusätzlich erforderlich.

## Herkunft aufbewahren

Bewahren Sie Archive, heruntergeladene Prüfsummenliste, festen Revisionswert und die enthaltenen bildbezogenen Herkunftsangaben auf. Bild-/Annotationsdaten stehen gemäß Quellen unter **CC BY-SA 4.0**; beigefügter Projektcode bleibt unter **AGPLv3**. Lesen Sie die [Dataset Card am festgelegten Stand](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/blob/e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8/README.md) und die beiliegenden Lizenzangaben. Verändern Sie beim Einsortieren keine Quellmanifeste oder Originaldateien.
