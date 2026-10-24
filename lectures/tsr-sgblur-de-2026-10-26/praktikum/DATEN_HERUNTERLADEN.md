# Straßenbilddaten auf den KI-Server herunterladen

Diese Anleitung verwendet den öffentlichen Datensatz [loffenauer/ws26_hspf_imo](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo). Sie benötigen dafür weder ein Hugging-Face-Konto noch einen Token. Sie laden die Daten direkt im Terminal Ihres KI-Server-Zugangs herunter; ein vorheriger Download auf Ihren eigenen Rechner ist nicht erforderlich.

Alle Befehle verwenden den festgelegten Datensatzstand **`42ed75dd292a56a83b5736f940ca4ce5ab80eef8`**. Damit beziehen alle Kursteilnehmenden dieselben Dateien. Die Pakete enthalten **ungeprüfte Beispiele und Vorschläge, keine menschlich freigegebene Ground Truth**. Der Modellcheckpoint und der kuratierte Korpus der 134 Bestandsklassen werden zusätzlich vom Dozenten bereitgestellt.

## 1. Vollständige Lernsammlung und Arbeitsordner

| Paket | Inhalt | Verwendung |
| --- | --- | --- |
| `panoramax-studenten-2026-10-19.zip` | 100 Vollbilder, 214 Schild-Crops, 27 Sequenzen | Lernsammlung: herunterladen, prüfen und einsortieren; anschließend mit dem bereitgestellten Bestandskorpus zusammenführen. |
| `panoramax-mobidata-bw-review-2026-10-20-v2.zip` | 57 Original-Vollbilder, 57 Crops, 53 Sequenzen; 37 DE:310- und 20 DE:311-Vorschläge | **Zweiter Lerndatensatz: MobiData BW.** Getrennte Sichtung und manueller Review; vor dem Import ist ein passender Export nötig. |
| `panoramax-mobidata-bw-review-2026-10-20-additions.zip` | 63 weitere Original-Vollbilder und 63 Crops aus 63 neuen Sequenzen; 58 DE:310- und 5 DE:311-Vorschläge | **Ergänzung zu Datensatz 2.** Ebenfalls herunterladen; eigener Sichtungsordner und manueller Review vor dem Kurs-Export. |
| `mapillary-mobidata-bw-review-2026-10-21.zip` | 5 zusätzliche Vollbilder und 5 native Crops; 4 DE:310- und 1 DE:311-Vorschlag, 4 Sequenzen | **Dritter Lerndatensatz: Mapillary anhand MobiData BW.** Eigener Sichtungsordner; vollständige 2048-Pixel-Downloads und Teilannotation, kein fertiger Trainingssatz. |
| `mapillary-mobidata-bw-review-2026-10-21-additions.zip` | 70 weitere Crop-/Vollbildpaare: 52 DE:310, 18 DE:311; 70 Sequenzen, 66 Gemeinden | **Ergänzung zu Datensatz 3.** 69 native Originalauflösungs-JPEGs und eine gekennzeichnete Panorama-Perspektive mit erhaltenem Original; getrennte Sichtung. |
| `panoramax-mobidata-sign-review-2026-10-23.zip` | 85 Katasterzuordnungen, 84 Originalfotos und 85 native Prüfausschnitte; 42 Zielcrop-Vorschläge, 16 andere Schilder, 27 Kontextbereiche | **Zusätzliche Multiklassen-Review-Galerie.** Getrennt unter `data/review-mobidata-signs/`; kein fertiger Trainings-/Testexport. |
| `panoramax-beispiele-v6.zip` | 2 Vollbilder und 6 Crops; Teilmenge der Lernsammlung | Kleiner technischer Einstieg. Die Ortstafel-Crops sind nur 27 × 22 beziehungsweise 27 × 17 Pixel groß. |
| `panoramax-testkandidaten-2026-10-20.zip` | 39 HD-Vollbilder, 77 Crops; außerdem 246 SD-Bilder derselben acht Sequenzen | Für den Dozenten und einen späteren gesonderten Abschlusstest reserviert. Die 39 HD-Bilder sind eine Teilmenge der 246 SD-Bilder. |
| `panoramax-externe-testkandidaten-2026-10-20.zip` | 15 Zielansichten: 2 Ortseingangs- und 13 Ortsausgangsvorschläge; 13 Standortkandidaten, 12 konservative Gruppen | Ebenfalls reserviert. 11 native 2D-Ansichten und 4 Perspektivansichten aus Panoramen; keine bestätigten unabhängigen Testfälle. |

Die **Ortstafel-Lernsammlung besteht weiterhin aus fünf Archiven**: Datensatz 1, MobiData BW v2, die zusätzliche 63er-Sammlung und beide Mapillary-Archive. Zusammen sind das **295 Vollbilder und 409 unterschiedliche Crop-Dateien**. **265 Ortstafel-Kandidaten** tragen Quell-Tags beziehungsweise visuelle Vorschläge: **200 DE:310 und 65 DE:311**. Dies sind keine bestätigten Klassenlabels oder unabhängigen Standorte. Fünf Ortstafel-Crops in Datensatz 1 besitzen gemischte Quell-Tags und benötigen besondere Prüfung.

[LEARNING_COLLECTION.json](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/42ed75dd292a56a83b5736f940ca4ce5ab80eef8/LEARNING_COLLECTION.json) benennt die fünf Lernarchive samt Prüfsummen und Archivwurzeln. Laden Sie diese fünf Archive und zusätzlich die 85-Kandidaten-Review-Galerie gemäß Abschnitt 3 herunter. Entpacken Sie Datensatz 1 nach Abschnitt 5 und beide MobiData-Archive getrennt nach Abschnitt 5a sowie beide Mapillary-Archive nach den Abschnitten 5b und 5c. Die fünf Lernarchive benötigen zusammen etwa **1,64 GB**, mit Review-Galerie etwa **1,91 GB**. Alle neun ZIP-Dateien einschließlich Demo und reservierter Pakete benötigen etwa **2,95 GB**. Entpackte Daten und Arbeitskopien benötigen weiteren Speicherplatz.

Die neue Galerie ist unter `review_supplements` verzeichnet und wird getrennt nach [Abschnitt 5d](#5d-review-galerie-85-weitere-verkehrszeichen) entpackt. Ihre 85 Zuordnungen werden nicht zu den bisherigen 295 Vollbildern und 409 Crops addiert.

Die beiden reservierten Pakete gehören nicht in Training, Validierung, Epochenwahl oder den normalen 70/15/15-Import. Das kleine Demo ist bereits Teil von Datensatz 1 und wird nicht zusätzlich gezählt.

Wechseln Sie im KI-Server-Terminal vom Repository-Hauptordner in das Praktikum:

```sh
cd lectures/tsr-sgblur-de-2026-10-26/praktikum
mkdir -p data/downloads/packages
tsr_dataset_revision='42ed75dd292a56a83b5736f940ca4ce5ab80eef8'
```

Wenn Sie das Praktikums-ZIP verwenden, arbeiten Sie direkt im vollständig entpackten Ordner `praktikum/`; der obige `cd`-Befehl gilt für die Repository-Ordnerstruktur. Führen Sie die weiteren Befehle im selben Terminal und in diesem Ordner aus. Für Download, Prüfsummen und Entpacken wird keine GPU benötigt.

## 2. Die Download-CLI getrennt installieren

Die folgende zusätzliche Python-Umgebung ist ausschließlich für den Download vorgesehen. Sie benötigt **Python 3.10 oder neuer**; die Lehrumgebung verwendet Python 3.12. Die direkte Verwendung ihrer Programme verändert die aktivierte Trainingsumgebung nicht:

```sh
python3 -m venv .venv-hf
.venv-hf/bin/python -m pip install 'huggingface_hub==1.10.2' \
  'typer==0.24.1' 'click==8.3.2'
.venv-hf/bin/hf download --help
```

Die CLI heißt `hf`. Installieren Sie die drei festgelegten Versionen gemeinsam. Damit steht auch die von dieser CLI benötigte `click`-Abhängigkeit bereit. Aktivieren Sie diese Download-Umgebung nicht anstelle der vom Dozenten vorbereiteten Trainingsumgebung. Hintergrund: [offizielle Hugging-Face-CLI-Dokumentation](https://huggingface.co/docs/huggingface_hub/guides/cli).

## 3. Die fünf Lernarchive und die Review-Galerie herunterladen

```sh
.venv-hf/bin/hf download loffenauer/ws26_hspf_imo \
  packages/panoramax-studenten-2026-10-19.zip \
  packages/panoramax-mobidata-bw-review-2026-10-20-v2.zip \
  packages/panoramax-mobidata-bw-review-2026-10-20-additions.zip \
  packages/mapillary-mobidata-bw-review-2026-10-21.zip \
  packages/mapillary-mobidata-bw-review-2026-10-21-additions.zip \
  packages/panoramax-mobidata-sign-review-2026-10-23.zip \
  LEARNING_COLLECTION.json SHA256SUMS.txt \
  --type dataset --revision "$tsr_dataset_revision" \
  --local-dir data/downloads
```

Die sechs ZIP-Dateien liegen anschließend unter `data/downloads/packages/`; Index und Prüfsummenliste unter `data/downloads/`. `--revision` legt den festen Stand fest. Wenn Sie schon ältere Pakete besitzen, laden Sie Index und Prüfsummenliste aus dieser Revision erneut und ergänzen Sie fehlende Archive. Erhalten Sie bereits bearbeitete Sichtungsordner.

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
  "$tsr_dataset_base/packages/panoramax-mobidata-bw-review-2026-10-20-additions.zip" &&
curl --fail --location --retry 3 \
  --output data/downloads/packages/mapillary-mobidata-bw-review-2026-10-21.zip \
  "$tsr_dataset_base/packages/mapillary-mobidata-bw-review-2026-10-21.zip" &&
curl --fail --location --retry 3 \
  --output data/downloads/packages/mapillary-mobidata-bw-review-2026-10-21-additions.zip \
  "$tsr_dataset_base/packages/mapillary-mobidata-bw-review-2026-10-21-additions.zip" &&
curl --fail --location --retry 3 \
  --output data/downloads/packages/panoramax-mobidata-sign-review-2026-10-23.zip \
  "$tsr_dataset_base/packages/panoramax-mobidata-sign-review-2026-10-23.zip"
```

## 4. Prüfsumme vor dem Entpacken vergleichen

Die veröffentlichte Liste enthält auch Dateien für Demo und reservierte Tests. Der folgende Befehl wählt **genau die fünf Lernarchive, die zusätzliche Review-Galerie und den Sammlungsindex** aus. Jede erwartete Zeile muss genau einmal vorhanden sein:

```sh
awk '
BEGIN {
  expected["packages/panoramax-studenten-2026-10-19.zip"] = 1
  expected["packages/panoramax-mobidata-bw-review-2026-10-20-v2.zip"] = 1
  expected["packages/panoramax-mobidata-bw-review-2026-10-20-additions.zip"] = 1
  expected["packages/mapillary-mobidata-bw-review-2026-10-21.zip"] = 1
  expected["packages/mapillary-mobidata-bw-review-2026-10-21-additions.zip"] = 1
  expected["packages/panoramax-mobidata-sign-review-2026-10-23.zip"] = 1
  expected["LEARNING_COLLECTION.json"] = 1
}
$2 in expected {print; seen[$2]++}
END {for (path in expected) if (seen[path] != 1) exit 1}
' data/downloads/SHA256SUMS.txt > data/downloads/SHA256SUMS-lern.txt &&
  (cd data/downloads && sha256sum --strict -c SHA256SUMS-lern.txt)
```

Erwartet werden **sieben Meldungen mit `OK`**: sechs ZIP-Dateien und `LEARNING_COLLECTION.json`. Nur dann dürfen Sie entpacken. Bei einer Abweichung oder einem Downloadfehler stoppen Sie und klären die Ursache mit dem Dozenten. Fehlermeldungen werden nicht mit `--ignore-missing` oder ähnlichen Optionen unterdrückt.

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
| [MobiData BW · v2](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/42ed75dd292a56a83b5736f940ca4ce5ab80eef8/packages/panoramax-mobidata-bw-review-2026-10-20-v2.zip?download=true) | 114.226.639 Byte; 57 Vollbilder und 57 Crops | `935e5aeceff8b55764fa5ff076777e391ad330a3ed6af74c1111b59c89626729` |
| [MobiData BW · zusätzliche 63 Paare](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/42ed75dd292a56a83b5736f940ca4ce5ab80eef8/packages/panoramax-mobidata-bw-review-2026-10-20-additions.zip?download=true) | 119.848.545 Byte; 63 Vollbilder und 63 Crops | `88be269f7c0d06111a5e5822252a40744140c722ff2c211396aef4876501da64` |

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

Gleiche Tafeln, nahe Ansichten und mögliche gemeinsame Fahrten müssen in derselben Gruppe bleiben, auch über alle fünf Lernarchive und beide Bildplattformen hinweg. Die enthaltenen Gruppen sind Vorschläge. Legen Sie geeignete Validierungs- und Testgruppen für **beide** Ortstafelklassen vor dem Training fest. Das gezielt zusammengestellte Sichtungsmaterial ist kein blinder Abschlusstest. Berechnen Sie Ihre Modellresultate selbst; die Pakete enthalten keine trainierten Modellkandidaten oder fertige Musterlösung.

## 5b. Dritter Lerndatensatz: Mapillary anhand MobiData BW

Die [Mapillary-Ergänzung](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/42ed75dd292a56a83b5736f940ca4ce5ab80eef8/packages/mapillary-mobidata-bw-review-2026-10-21.zip?download=true) umfasst **5 native Perspektiv-Vollbilder und 5 Crops**: **4 DE:310- und 1 DE:311-Vorschlag** aus vier Gemeinden und vier Sequenzen. Die vollständigen JPEG-Downloads sind von Mapillary auf **2048 Pixel Breite** skaliert; sie wurden lokal nicht verändert. Die Crops enthalten exakt die dokumentierten Pixel ohne Vergrößerung. Das Archiv ist **3.129.044 Byte** groß; SHA-256: `4c04a802d5e0a53a3a31eaf0884a1307460fd68ae52a71abe444b899bc6071a9`.

Das bereits in Abschnitt 3 geladene Archiv wird nach erfolgreicher Prüfung in Abschnitt 4 getrennt entpackt:

```sh
test ! -e data/collection-mapillary-mobidata-bw &&
  test ! -e data/entpackt-mapillary-mobidata-bw &&
  python3 -m zipfile -e \
    data/downloads/packages/mapillary-mobidata-bw-review-2026-10-21.zip \
    data/entpackt-mapillary-mobidata-bw &&
  mv data/entpackt-mapillary-mobidata-bw/mapillary-mobidata-bw-review-2026-10-21 \
    data/collection-mapillary-mobidata-bw
```

Öffnen Sie `data/collection-mapillary-mobidata-bw/SICHTUNG.html`. Prüfen Sie die sichtbare Schildseite: Ein DE:310-Vorschlag in Schwendi liegt neben einem DE:311-Katastereintrag. Der Registercode bestätigt weder die Bildklasse noch die physische Identität. Dokumentieren Sie Ihren Review in `SICHTUNG_CROPS.csv` und `SICHTUNG_VOLLBILDER.csv`. Alle Freigaben bleiben zunächst `NEIN`.

Wie die beiden anderen MobiData-Pakete benötigt diese Teilannotation einen geprüften Kurs-Export. Prüfen Sie für den Detektor alle relevanten Vollbildboxen; erhalten Sie vorhandene Unkenntlichmachungen. Aus bereits verwischten Gesichtern und Kennzeichen folgt keine vollständige Ground Truth für ursprünglich sichtbare Objekte. Zwei Aufnahmen stammen aus derselben Fahrt; erhalten Sie die vier vorgeschlagenen Fahrtgruppen und gleichen Sie Standorte und Fahrten auch plattformübergreifend mit Panoramax ab. Der ausgewählte Bestand ist kein Blindtest und keine Messung der gesamten Mapillary-Abdeckung Baden-Württembergs.

Bewahren Sie **Urheber, Bild-ID, Mapillary-Quelllink, Lizenz und Änderungshinweis** aus `HERKUNFT.csv` beziehungsweise `manifest.json` bei jedem Export auf. Bilder und abgeleitete Crops stehen unter **CC BY-SA 4.0**. `source=Mapillary` allein ersetzt die Bildattribution nicht. Die HTML-Sichtung enthält das offizielle Mapillary-Logo und die bildbezogenen Quellen. Für diese Hugging-Face-Downloads benötigen Sie **keinen Mapillary-Token**; ein eigener Mapillary-Crawl ist nicht Teil des Downloads.

## 5c. Weitere 70 Mapillary-Paare aus der MobiData-Suche

Die [API-Ergänzung](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/42ed75dd292a56a83b5736f940ca4ce5ab80eef8/packages/mapillary-mobidata-bw-review-2026-10-21-additions.zip?download=true) liefert **70 weitere Crop-/Vollbildpaare**: **52 DE:310- und 18 DE:311-Vorschläge** aus **70 Sequenzen und 66 Gemeinden**. Das Archiv enthält 69 unveränderte JPEGs in der über die API verfügbaren Originalauflösung und eine geometrische 1920 × 1080-Perspektivansicht aus einem 5760 × 2880-Panorama. Das unveränderte Panorama und die Projektionsparameter bleiben beigefügt; es zählt nicht als zusätzliches Lernbeispiel. Archivgröße: **144.587.464 Byte**; SHA-256: `8eaf4e62db93cd0fcb2ccf695da57fec9ec34b04b216212a3a2bb8e32df7e4d7`.

Die eingefrorene Suche verwendete 1.001 MobiData-Punkte in 511 Gemeinden mit einem Kameraradius von 50 Metern. An 656 Punkten gab es eine Kameraposition innerhalb von 10 Metern, an 756 Punkten innerhalb von 50 Metern. Das belegt keine Sichtbarkeit des Schildes. Aus 2.158 nach Richtung und Ranking ausgewählten Bildkandidaten wurden 280 Vorschauen gesichtet und 88 Originalauflösungen geprüft; davon wurden 69 übernommen. Hinzu kommt das separat benannte Panorama. Das ist keine Vollerhebung Baden-Württembergs und keine vollständige Sichtung der früheren 2.730 Panoramax-Treffer.

Entpacken Sie das in Abschnitt 3 heruntergeladene und in Abschnitt 4 geprüfte Archiv in einen neuen Ordner:

```sh
test ! -e data/collection-mapillary-mobidata-bw-additions &&
  test ! -e data/entpackt-mapillary-mobidata-bw-additions &&
  python3 -m zipfile -e \
    data/downloads/packages/mapillary-mobidata-bw-review-2026-10-21-additions.zip \
    data/entpackt-mapillary-mobidata-bw-additions &&
  mv data/entpackt-mapillary-mobidata-bw-additions/mapillary-mobidata-bw-review-2026-10-21-additions \
    data/collection-mapillary-mobidata-bw-additions
```

Öffnen Sie `data/collection-mapillary-mobidata-bw-additions/SICHTUNG.html`. Bearbeiten Sie `SICHTUNG_CROPS.csv` und `SICHTUNG_VOLLBILDER.csv`; lassen Sie Klasse und Boxen zusätzlich durch eine zweite Person prüfen. **42 visuelle Vorschläge unterscheiden sich vom nahen Katastercode.** Das ist kein SGBlur-Fehlernachweis: Es wurden keine SGBlur-Vorhersagen berechnet. Ein Beispiel ist Bad Herrenalb: Register und Mapillary-Hinweis zeigen einen Ortsausgang an, die sichtbare Tafel ohne roten Diagonalstrich ergibt einen DE:310-Vorschlag. Erhalten Sie Quelllabels und Ihren Review getrennt.

Die **68 konservativen Gruppenvorschläge** verbinden gleiche Urheber/Aufnahmetage und Registerpunkte innerhalb von 100 Metern. Zwei neue Bilder besitzen zusätzlich Querverweise zum älteren Mapillary-Paket. Führen Sie die unter `cross_package_group_merge_proposals` genannten Gruppen vor einer Aufteilung zusammen und gleichen Sie Tafeln und Fahrten auch mit Panoramax sowie dem bereitgestellten Bestandskorpus ab. Die anhand der Zielbox ausgerichtete Panoramaansicht ist kein blinder Detektortest; behandeln Sie sie bei einer späteren Auswertung gesondert. Projektionen erzeugen keine neuen Bilddetails.

Alle Freigaben stehen zunächst auf `NEIN`. Für den Klassifikator exportieren Sie nur bestätigte Crops mit Herkunft und Gruppe. Für den Detektor müssen Sie alle relevanten Schilder, Kennzeichen und Gesichter im Vollbild prüfen und vollständig annotieren. Die einzelne Zielbox reicht dafür nicht. Native Ansichten heißen `image.jpg`, die projizierte Ansicht `image.png`; `box-proposals.json` enthält Teilannotation. Der normale Kursimport übernimmt diese Ordner nicht unverändert. Erhalten Sie Quellenanonymisierung, `HERKUNFT.csv`, Urheber, Bild-ID, Quelllink, CC-BY-SA-4.0-Lizenz und Änderungshinweise. Die Downloadbefehle benötigen weiterhin keinen Mapillary-Token. Trainings- und Modellresultate erarbeiten Sie selbst.

## 5d. Review-Galerie: 85 weitere Verkehrszeichen

Die [Online-Galerie](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/blob/42ed75dd292a56a83b5736f940ca4ce5ab80eef8/reviews/panoramax-mobidata-sign-review-2026-10-23/README.md) und das [Offline-ZIP](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/42ed75dd292a56a83b5736f940ca4ce5ab80eef8/packages/panoramax-mobidata-sign-review-2026-10-23.zip?download=true) enthalten **85 Katasterzuordnungen, 84 unveränderte Originalfotos und 85 native Prüfausschnitte**. Das Archiv ist **265.110.968 Byte** groß. Seine SHA-256 lautet:

```text
4d56b962a81b7b6476e31a2e03005540ec731c562d6d07a5d78e0ec9accb536d
```

Die Galerie ergänzt die Sichtung weiterer Verkehrszeichen; sie ersetzt keinen der fünf Ortstafel-Lernbestände. `LEARNING_COLLECTION.json` führt sie unter `review_supplements`. Verwenden Sie die Archive und ihre Manifeste: Automatisch aus Ordnernamen erzeugte Hugging-Face-Klassen oder Splits sind keine geprüften Verkehrszeichenlabels.

**Wenn Sie Abschnitt 3 und 4 bereits mit dem neuen Stand ausgeführt haben, fahren Sie direkt mit dem Entpacken fort.** Wenn Sie bisher nur die ältere Lernsammlung geladen haben, ergänzen Sie ausschließlich das neue Archiv und die aktualisierten Begleitdateien; erhalten Sie Ihre bisherigen Reviews:

```sh
tsr_dataset_revision='42ed75dd292a56a83b5736f940ca4ce5ab80eef8'
.venv-hf/bin/hf download loffenauer/ws26_hspf_imo \
  packages/panoramax-mobidata-sign-review-2026-10-23.zip \
  LEARNING_COLLECTION.json SHA256SUMS.txt \
  --type dataset --revision "$tsr_dataset_revision" \
  --local-dir data/downloads
awk '
$2 == "packages/panoramax-mobidata-sign-review-2026-10-23.zip" || $2 == "LEARNING_COLLECTION.json" {print; seen[$2]++}
END {if (seen["packages/panoramax-mobidata-sign-review-2026-10-23.zip"] != 1 || seen["LEARNING_COLLECTION.json"] != 1) exit 1}
' data/downloads/SHA256SUMS.txt > data/downloads/SHA256SUMS-galerie.txt &&
  (cd data/downloads && sha256sum --strict -c SHA256SUMS-galerie.txt)
```

Erwartet werden hier **zwei Meldungen mit `OK`**: die Galerie und der Sammlungsindex. Ohne CLI können Sie den Galerie-Download und die beiden Begleitdateien mit den HTTPS-Befehlen aus Abschnitt 3 einzeln laden. Verwenden Sie auch dabei die hier festgelegte Revision. Entpacken Sie erst nach erfolgreicher Prüfsummenprüfung in einen neuen Ordner:

```sh
test ! -e data/review-mobidata-signs &&
  test ! -e data/entpackt-mobidata-signs &&
  python3 -m zipfile -e \
    data/downloads/packages/panoramax-mobidata-sign-review-2026-10-23.zip \
    data/entpackt-mobidata-signs &&
  mv data/entpackt-mobidata-signs/panoramax-mobidata-sign-review-2026-10-23 \
    data/review-mobidata-signs
```

Öffnen Sie **`data/review-mobidata-signs/SICHTUNG.html`** in einer lokalen Arbeitskopie im Browser. Wenn Sie am KI-Server ohne grafische Oberfläche arbeiten, laden Sie für die Sichtung dasselbe ZIP über den obigen Browserlink auf Ihren Rechner und entpacken Sie es dort vollständig. Kopieren Sie nicht nur die HTML-Datei: Die Ordner `originals/`, `previews/`, `thumbnails/`, `crops/` und `metadata/` müssen zusammenbleiben. Das entpackte Archiv lässt sich ohne Login und ohne Internet ansehen; Panoramax- und Lizenzlinks benötigen eine Internetverbindung.

Filtern Sie nach **MobiData-Code**, **Prüfbedarf**, Ort oder Kennung. Vergleichen Sie Vollbild, markierten Ausschnitt und Originalauflösung. Die [Review-Anleitung mit der vollständigen Flag-Legende](SAMMELN_UND_SORTIEREN.md#8-review-der-85-kandidaten-galerie) beschreibt die Prüfung und den Export Ihrer Notizen. Die Online-Galerie auf Hugging Face bietet die Bild-/Crop-Paare und Quelllinks; die interaktiven Filter und lokalen Notizen stehen in der entpackten `SICHTUNG.html` bereit.

Die 85 Ausschnitte bestehen aus **42 Zielcrop-Vorschlägen**, **16 Crops anderer sichtbarer Schilder** und **27 Kontext-Prüfbereichen ohne bestätigtes Zielschild**. Alle Varianten und Ablesungen bleiben zunächst ungeprüft. Kontextbereiche dürfen weder als bestätigte Schildklassen noch als objektfreie Negativbeispiele übernommen werden. Die Galerie besitzt `normal_course_importer_compatible=false`; ändern Sie die feste Liste der 136 Modellklassen nicht aufgrund eines Katastercodes.

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

Bewahren Sie Archive, heruntergeladene Prüfsummenliste, festen Revisionswert und die enthaltenen bildbezogenen Herkunftsangaben auf. Die bisherigen Bild-/Annotationspakete stehen gemäß Quellen unter **CC BY-SA 4.0**. Die neue 85-Kandidaten-Galerie enthält **81 Originalfotos unter CC BY-SA 4.0 und drei unter Etalab Licence Ouverte 2.0**; erhalten Sie deren bildbezogene Lizenzlinks auch für Crops und Vorschauen. Beigefügter Projektcode bleibt unter **AGPLv3**. Lesen Sie die [Dataset Card am festgelegten Stand](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/blob/42ed75dd292a56a83b5736f940ca4ce5ab80eef8/README.md) und die beiliegenden Lizenzangaben. Erhalten Sie auch die Mapillary-Urheber und Quelllinks; das offizielle Logo ist eine Marke von Mapillary und wird durch die Datenlizenz nicht umlizenziert. Verändern Sie beim Einsortieren keine Quellmanifeste oder Originaldateien.
