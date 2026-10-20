# Lehrvorbereitung

**26. Oktober 2026 · Studierende im 3. Semester ohne ML-Vorkenntnisse**

Bereiten Sie Daten, Originalmodelle und eine eigene Lehrumgebung vor dem Kurs vor. Die Studierenden sammeln und sortieren Bilder im Ordner `praktikum/` und verwenden anschließend die bereitgestellten Trainingsskripte. Der vollständige Trainingslauf folgt nach der 45-minütigen Vorlesung.

**Code und Klassentabelle sind enthalten. Die vier ungeprüften Panoramax-Pakete sind öffentlich verfügbar; der vollständige kuratierte Korpus der 134 Bestandsklassen und der Originalcheckpoint müssen zusätzlich bereitgestellt werden.** Die folgende Anleitung beschreibt diese Lehrvorbereitung.

## 1. Daten bereitstellen

Sie benötigen geprüfte Schild-Crops für **alle 134 Bestandsklassen** und für die neuen Klassen `city:start` (DE:310, Ortseingang) und `city:end` (DE:311, Ortsausgang). Stellen Sie bereit:

```text
praktikum/data/raw/images/        # geprüfte Crops, keine Straßen-Vollbilder
praktikum/data/annotations.csv
```

Der CSV-Kopf lautet genau `sample_id,image_path,label,group_id`. Bildpfade gelten relativ zu `data/raw/images/`. Die feste [class-index.json](praktikum/class-index.json) enthält die 134 Originalklassen plus zwei neue; ändern oder sortieren Sie sie nicht.

Lassen Sie Box und Klasse durch eine zweite Person prüfen. Bewahren Sie Quellbild-/Annotations-/Sequenzidentität, Autor und Lizenz in der Begleitdokumentation. Derselben physischen Tafel, Fahrt oder Nahe-Duplikatbeziehung zugehörige Bilder erhalten eine gemeinsame `group_id`. Das Skript entdeckt diese Beziehungen nicht selbst. Die [Beispiel-CSV](praktikum/examples/annotations.example.csv) erläutert nur das Format.

Der publizierte Panoramax-DE-Train/Val-Split enthält dokumentierte Überschneidungen und darf nicht unverändert als unabhängiger Kurs-Abschlusstest gelten. Prüfen und gruppieren Sie die Quellen neu; siehe [Trainings-Rundlauf](../../docs/TSR_TRAINING_ROUND_TRIP.md). `prepare_dataset.py` lädt keine Panoramax-Bilder und schneidet keine Vollbilder aus.

### Öffentliche Pakete auf den KI-Server laden

Die [kanonische Downloadanleitung](praktikum/DATEN_HERUNTERLADEN.md) enthält ausführbare Befehle für [loffenauer/ws26_hspf_imo](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo), festgelegt auf Revision **`e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8`**. Der öffentliche Download benötigt keinen Login. Installieren Sie die Download-CLI bei Bedarf in `.venv-hf/` mit `huggingface_hub==1.10.2`, `typer==0.24.1` und `click==8.3.2`, getrennt von der gepinnten Trainingsumgebung. Der Serverversuch zeigte bei einer frischen Installation ohne diese zusätzlichen Pins eine fehlende `click`-Abhängigkeit. Die Anleitung bietet auch HTTPS mit `curl` und verlangt die gezielte SHA-256-Prüfung vor dem Entpacken.

Stellen Sie die Lernsammlung mit **100 Vollbildern und 214 Crops** nach `praktikum/data/collection/`. Das ZIP enthält zunächst den Ordner `panoramax-studenten-2026-10-19/`, der als Ganzes übernommen wird. Das kleine Demo mit zwei Vollbildern und sechs Crops liegt getrennt unter `data/demo/collection-demo/`; diese beiden Bilder sind bereits Teil der Lernsammlung. Überschreiben oder vermischen Sie keine vorhandene Sammlung.

Die beiden Pakete mit **39 HD-Bildern/77 Crops plus 246 SD-Bildern** beziehungsweise **15 externen Zielansichten** bleiben unter `data/teacher-reserved/` getrennt. Es sind **0 menschlich freigegebene Testfälle**. Verwenden Sie diese Pakete nicht für Training, Validierung, Epochenwahl oder den normalen 70/15/15-Import. Vor einem späteren Abschlusstest sind menschliche Box-/Klassenprüfung, Standort-/Fahrtenabgleich, ein eigenes eingefrorenes Testmanifest und ein passender Evaluationsmodus erforderlich. Der vorhandene Evaluator bindet den Kandidaten an das ursprüngliche Trainingsmanifest; seine Herkunftsprüfungen dürfen dafür nicht abgeschaltet werden.

Unter den ursprünglichen Gruppen und dem unveränderten Seed hat die 100er-Lernsammlung keine Ortstafel-Testabdeckung. Neue Sequenz-IDs allein belegen keine unabhängigen Tafeln oder Fahrten. Die externen 15 Ansichten ergeben 13 Standortkandidaten und zwölf konservative Gruppen, keine zertifizierten unabhängigen Fälle. Vier zielzentrierte Perspektivbilder sind getrennt von elf nativen 2D-Ansichten zu bewerten. Die Downloadanleitung und die Paketberichte erläutern diese Grenzen. Der vollständige Altklassen-Regressionsbestand bleibt zusätzlich erforderlich.

### Sammlung und Ordnerprüfung vorbereiten

Verwenden Sie für die erste Ordnerprüfung die heruntergeladene Lernsammlung. Ein zusätzlicher Export vorhandener Annotationen und öffentlicher HD-Bildableitungen kann mit `crawl_panoramax.py` erfolgen. Verwenden Sie dafür einen neuen Ausgabeordner:

```sh
python crawl_panoramax.py --max-images 100 --output data/collection-neu
```

Die Lernsammlung unter `data/collection/` und der zusätzliche Export unter `data/collection-neu/` enthalten ungeprüfte Schild-Crops sowie Vollbildpakete mit `image.png`, `labels.txt` und `metadata.json`. Die Studierenden bestätigen eine Klasse durch Verschieben des Crops in einen der 136 angelegten Klassenordner; `city:start` heißt dort `city__start`, `city:end` heißt `city__end`. Detektorbeispiele werden nur als vollständige Pakete freigegeben. Der Ablauf steht mit Verschiebebeispielen in [SAMMELN_UND_SORTIEREN.md](praktikum/SAMMELN_UND_SORTIEREN.md). Die folgenden Standard-Importbefehle verwenden die Lernsammlung; einen anderen Sammelordner geben Sie mit `--source` an.

Prüfen Sie den Export vor dem Kurs auf ausreichende Auflösung und Lesbarkeit. Gespeicherte Modellklassen sind Vorschläge; auch ein hoher Score ist kein Nachweis menschlicher Prüfung. Die Auswahl der Studierenden muss von einer zweiten Person auf Box und Klasse geprüft werden. Eine Ortstafel ohne vorhandene Box wird beim Crawlen vorhandener Annotationen nicht automatisch zum gelabelten Beispiel. Fehlende oder falsche Boxen sind in Panoramax zu ergänzen beziehungsweise zu korrigieren und erneut zu exportieren. Der Crawler selbst schreibt nichts zum Server.

Metadaten-, Seiten- und Bildlimits begrenzen den Lauf. Die Sammlung ist kein vollständiges Instanzinventar und ersetzt den geprüften 134-Klassen-Korpus nicht. Erhalten Sie Quell-IDs, Autor, Lizenz und Prüfsummen mit der Sammlung. Nehmen Sie keine ausreichende Klassenabdeckung allein aufgrund eines erfolgreichen Downloads an.

Der Importer hält jede vollständige Sequenz einschließlich aller Vollbilder und Crops in derselben Gruppe. Legen Sie zusätzlich vorab `data/groups.csv` mit `sequence_id,group_id` an, wenn gleiche physische Tafeln, Fahrten oder Nahe-Duplikate mehrere Sequenzen verbinden. Gleiche Gruppenkennungen führen diese Sequenzen zusammen. Stimmen Sie die Kennungen mit dem bereitgestellten Bestandskorpus ab; die Software entdeckt solche Beziehungen nicht automatisch.

## 2. Baseline prüfen

Kopieren Sie den geprüften deutschen Originalcheckpoint nach `praktikum/models/baseline.pt`:

- Quelle: [Panoramax/classify_de_road_signs](https://huggingface.co/Panoramax/classify_de_road_signs/tree/5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790).
- Revision: `5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790`; Größe: 26.282.865 Byte.
- SHA-256: `f8277a3790fd3357b3ca31a086c7dc9f365785c7fa44bfd3b5c68834555699c7`.

Falls die Datei fehlt, können Sie vom Repository-Hauptordner gezielt dieses Artefakt beziehen. Ersetzen Sie den absoluten Beispielpfad:

```sh
python3 scripts/tsr/bootstrap_sources.py download --root /ABSOLUT/kurs-bootstrap \
  panoramax-de-yolo26-classifier-5360aa6
python3 scripts/tsr/bootstrap_sources.py verify --root /ABSOLUT/kurs-bootstrap \
  panoramax-de-yolo26-classifier-5360aa6
```

Kopieren Sie die ausgegebene geprüfte Datei nach `models/baseline.pt`. Der Trainingscode prüft den Hash erneut. Für dieses Crop-Praktikum ist kein zusätzlicher Detektorcheckpoint nötig.

Für einen zusätzlichen Detektorversuch stellen Sie getrennt `praktikum/models/detector-baseline.pt` bereit: den ursprünglichen **SGBlur-YOLO11n mit den drei Klassen `sign`, `plate`, `face`**. Sein SHA-256 lautet `698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a`; die Quelle ist der gepinnte [SGBlur-Checkpoint `yolo11n_panoramax.pt`](https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/models/yolo11n_panoramax.pt), auch in [model-inventory.json](source/model-inventory.json) dokumentiert. Folie 21 nennt diesen Checkpoint ausdrücklich. Verwechseln Sie diesen Checkpoint nicht mit dem deutschen 134-Klassen-Cropmodell. Prüfen Sie Hash und Klassenbelegung vor der Übung.

**Ergänzung vom 20. Oktober:** SGBlur bietet inzwischen einen YOLO26s-Detektor
mit denselben drei Objektklassen an. Folie 11 der Fassung v13 zeigt den zusätzlichen
Vergleich auf drei archivierten Dashcam-Fahrten. Die 65 festen Prüfbilder sind
durch einen Assistenten annotiert und keine mobile Freigabe. Verwenden Sie den neuen Checkpoint als
getrennten Kandidaten, wenn Sie ihn untersuchen möchten. Die dokumentierten
Verwenden Sie für den Kursversuch weiterhin die dokumentierte YOLO11n-Baseline; tauschen Sie deren Ausgangsgewichte nicht stillschweigend aus. [Quellen, Exporte und Grenzen des Kandidaten](../../docs/SGBLUR_YOLO26_CANDIDATE_2026-10-20.md).

## 3. Lehrumgebung vorbereiten

Verwenden Sie eine getrennte Python-3.12-Umgebung beziehungsweise ein Kursimage mit zugewiesener GPU und persistentem Arbeitsordner. Die direkten Pins stehen in [requirements.txt](praktikum/requirements.txt): Torch 2.6.0, Torchvision 0.21.0, Ultralytics 8.4.56 sowie NumPy/Pillow. Für die dokumentierte A5000-Basis wählen Sie passende CUDA-12.6-Wheels. Ein Beispiel innerhalb Ihres eigenen Lehrvenv:

```sh
python -m pip install torch==2.6.0 torchvision==0.21.0 \
  --index-url https://download.pytorch.org/whl/cu126
python -m pip install -r requirements.txt
python -m pip check
python -m pip freeze > environment.freeze.txt
```

Führen Sie dies aus dem Ordner `praktikum/` aus. Protokollieren Sie Code-Revision und vollständigen Paketstand beziehungsweise Image-Digest. Verändern Sie keine laufenden Prolix-/SGBlur-Dienste. Übertragen Sie diese A5000-Konfiguration nicht ungeprüft auf Blackwell; alternative GPU-/Torch-Stacks benötigen einen eigenen Kompatibilitätstest. Hintergrund: [Server-/Exportinventar](../../docs/TSR_EXPORT_AND_SOURCE_PROVENANCE.md).

## 4. Daten und Ablauf vorab prüfen

Prüfen und sortieren Sie zunächst einen begrenzten Export wie in der Sammelanleitung. Im vorbereiteten `praktikum/` folgt dann:

```sh
python import_sorted_folders.py \
  --include-annotations data/annotations.csv \
  --include-images data/raw/images
python prepare_dataset.py \
  --annotations data/reviewed/classifier/annotations.csv \
  --images data/reviewed/classifier/images
python train.py --epochs 1 --output runs/technikprobe
python evaluate.py --candidate runs/technikprobe/weights/best.pt \
  --output reports/technikprobe
```

Die feste Zielaufteilung ist **70/15/15**, Seed `20261026`, mit ganzen Gruppen statt exakter Bildquoten. `data/dataset/manifest.json` dokumentiert Gruppen, Klassen und Hashes. Prüfen Sie vor dem Kurs alle 136 Trainingsklassen, beide neuen Klassen in der Validierung und geeignete unabhängige Prüfbeispiele jeder Bestandsklasse in `val` und `test`. Beide neuen Klassen brauchen ebenfalls beurteilbare Testabdeckung. Fehlende Abdeckung erfordert zusätzliche unabhängige Daten.

Geben Sie beim Import gegebenenfalls zusätzlich `--groups data/groups.csv` an. `data/reviewed/` ist eine neue, eingefrorene Ausgabe. Für spätere Importstände wählen Sie einen neuen Ausgabeordner. Prüfen Sie in den Sammel- und Importmanifesten Herkunft, freigegebene Beispiele, Gruppen und Klassenabdeckung. Noch nicht freigegebene Eingangsdateien werden nicht importiert.

Der technische Probelauf mit einer Epoche prüft Laden, GPU-Rechnung, Speichern und Bewertung. Ein inhaltlich regressiver Kandidat kann dabei erwartungsgemäß durchfallen. Im Studierendenversuch lauten die Standardbefehle:

```sh
python train.py --epochs 20
python evaluate.py --candidate runs/versuch-01/weights/best.pt
```

Für den getrennten Detektorversuch prüfen Sie `data/reviewed/detector/` auf geeignete unabhängige Gruppen und ausreichende Schild-, Kennzeichen- und Gesichtsabdeckung in Training, Validierung und Test. Bei leeren oder unvollständigen Prüfpartitionen sind zusätzliche unabhängige vollständig annotierte Frames nötig; ein erneutes Auswürfeln der Aufteilung ist kein Ersatz. Der vorbereitete Aufruf lautet:

```sh
yolo detect train model=models/detector-baseline.pt \
  data=data/reviewed/detector/data.yaml \
  epochs=20 imgsz=1280 device=0 seed=20261026
```

Nach Auswahl anhand der Validierung werden Baseline und Kandidat mit `yolo detect val … split=test` auf denselben zurückgehaltenen Vollbildern verglichen. Die vollständigen Befehle und der an den tatsächlichen Versuchsordner anzupassende Kandidatenpfad stehen in der [Sammelanleitung](praktikum/SAMMELN_UND_SORTIEREN.md). Beurteilen Sie die bestehenden Gesichts-/Kennzeichenleistungen getrennt von einer Verbesserung bei Schildern. Öffentliche HD-Ableitungen sind häufig schon verwischt; daraus folgt kein Qualitätsnachweis für unverpixelte Gesichter und Kennzeichen. Der Importer prüft Dateiintegrität und Freigabepfade, nicht die tatsächliche Vollständigkeit aller Boxen.

Die Validierung dient dem Tuning und der Kandidatenwahl. Erst anschließend wird der Test einmal geöffnet:

```sh
python evaluate.py --candidate runs/versuch-01/weights/best.pt \
  --split test --output reports/abschluss
```

## 5. Bewertungsregel und Grenzen erklären

Der Bestandsvergleich verwendet für beide Modelle dieselben zurückgehaltenen alten Zielbilder. Recall/F1 jeder der 134 alten Klassen und alte Gesamtwerte dürfen nicht sinken. `REGRESSION` oder fehlende Abdeckung (`UNVOLLSTAENDIG`) führen **nach dem Schreiben aller Berichte zu Rückgabecode 3**. Regression hat bei gleichzeitig fehlender Abdeckung Vorrang.

`BESTANDEN`/Rückgabecode 0 betrifft **nur dieses Bestandsklassen-Gate**. Beurteilen Sie die neuen Klassen zusätzlich mit Support, Precision, Recall, F1 und Fehlbildern. Daraus folgt keine automatische Modellfreigabe oder Garantie für zukünftige Bilder. Öffnen Sie `BERICHT.md`, `regression-gate.json` und `old-only-per-class.csv`.

`best.pt` verwendet ein eigenes sicheres `state_dict`- und Metadatenformat. Vor einem Plattformexport muss das Modell mit `model_utils.load_candidate()` rekonstruiert werden. `yolo export model=best.pt` ist kein fertiger Kurs-Exportweg. **Core-ML-/LiteRT-Export dieses neuen Kandidaten wurde nicht getestet.**

## 6. Vortrag bereitlegen

Der zusätzliche [MobiData-BW-Sichtungseingang v2 auf Hugging Face](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8/packages/panoramax-mobidata-bw-review-2026-10-20-v2.zip?download=true)
enthält 57 Original-Vollbilder, 57 Ortstafel-Crops und Zielboxvorschläge (37 DE:310,
20 DE:311), darunter 44 zusätzliche Zielansichten aus dem 10-m-Abgleich.
Öffnen Sie `SICHTUNG.html` im entpackten Ordner. Verwenden Sie ihn als exploratives Lehr-/Reviewmaterial außerhalb
der reservierten Testkandidaten. Klassen und sämtliche Vollbildboxen müssen
noch menschlich geprüft werden; die normalen Kursimporter dürfen die
Teilannotation noch nicht übernehmen. Beginnen Sie mit den
[Sichtungshinweisen](source/mobidata-bw-review-2026-10-20-v2/BITTE_ZUERST_LESEN.txt).

Der neue Nonnenweier-Fall trennt Detektion und Klassifikation: Die Quellbox
stammt von `SGBlur-yolo11s/0.1.0`; das Label `FR:C50` mit Score 0,92 stammt von
`classify_fr_road_signs/0.13`, obwohl die sichtbare Tafel DE:310 nahelegt.
Der feste lokale YOLO11n-Replay verfehlt dieselbe Zieltafel. Verwenden Sie
Nachbarlabels nur bei passender Boxüberschneidung; pauschale Bildtags reichen
für diese Zuordnung nicht. Die 37 verfehlten neuen Zielvorschläge sind eine
gezielte Auswahl und keine populationsbezogene Recall-Schätzung.

Öffnen Sie die PowerPoint und [praktikum/README.md](praktikum/README.md). Prüfen Sie Panoramax-Kurskonto und Annotationsrechte; die gespeicherten Dobel-/Bernbach-Bilder stehen als Reserve bereit. Zeitplan und Übungslösungen hält der Dozent im lokalen Dozentenleitfaden bereit.

Die tatsächlichen Backbone-/Kopfstrukturen sind in [network-architecture-evidence.json](source/network-architecture-evidence.json) belegt. Die 35/1 MB der Modellfolie sind **berechnete Android-App-Puffer**, kein vollständiger RAM je Modell. Android-PSS rund 646 MB und historischer iPhone-Footprint rund 232 MB betreffen unterschiedliche Gesamtapp-Lasten und Messgrößen; siehe [RAM-Belege](source/model-memory-evidence.json).

Der [exakte CLI-Smoke-Test](source/praktikum-exact-cli-smoke.json) mit Ultralytics 8.4.56 auf CPU, künstlichen Farb-Crops und einer Epoche sowie 27 lokale Tests sind dokumentiert. Das belegt den technischen Ablauf einschließlich `UNVOLLSTAENDIG`/Exit 3; es ersetzt keinen echten Kurskorpus, keine Qualitätsmessung und keinen GPU-Probelauf.

Die erweiterte Sammlung und Ordnerprüfung sind mit **70 lokalen Tests** sowie einem begrenzten Live-Crawl mit zwei Vollbildern und sechs ungeprüften Crops geprüft. Der zusätzliche synthetische Ablauf verwendet alle 136 Klassen und hält Vollbild und Crops im gleichen Split. [Prüfbeleg](source/collection-smoke-evidence.json). Die kleine Live-Sammlung ist eine Übungsreserve für die Prüfung und das Einsortieren; sie ersetzt keinen vollständigen Kursdatensatz.


Die Studierenden erhalten außerdem [MobiData BW als zweiten Lerndatensatz](praktikum/DATEN_HERUNTERLADEN.md#5a-zweiter-lerndatensatz-mobidata-bw). Beide MobiData-Archive sind im öffentlichen Kursdatensatz am festen Stand `e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8` verfügbar. Vor der Übernahme benötigen die vorgeschlagenen Klassen und Zielboxen menschlichen Review, eine gruppierte Aufteilung und einen passenden Export. Ergebnisse vorweggenommener Trainingsversuche bleiben ausschließlich lokal.

Die vollständige Lernsammlung am oben festgelegten Stand besteht aus drei Archiven: 100er-Sammlung (214 Crops), MobiData BW v2 (57 Paare) und der [zusätzlichen 63er-Sammlung](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8/packages/panoramax-mobidata-bw-review-2026-10-20-additions.zip?download=true). Stellen Sie **220 Vollbilder und 334 Crops** zur Prüfung bereit; **190 Ortstafel-Kandidaten** verteilen sich nach Tags beziehungsweise Vorschlägen auf **144 DE:310 und 46 DE:311**. Bewahren Sie die drei Sichtungsordner getrennt und prüfen Sie gemeinsame Tafeln und Fahrten vor dem Split. Die vollständigen Download-, Prüfsummen- und Entpackbefehle stehen in der kanonischen Anleitung.
