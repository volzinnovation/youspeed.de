# Panoramax-Daten auf den KI-Server herunterladen

Diese Anleitung verwendet den öffentlichen Datensatz [loffenauer/ws26_hspf_imo](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo). Sie benötigen dafür weder ein Hugging-Face-Konto noch einen Token. Sie laden die Daten direkt im Terminal Ihres KI-Server-Zugangs herunter; ein vorheriger Download auf Ihren eigenen Rechner ist nicht erforderlich.

Alle Befehle verwenden den festgelegten Datensatzstand **`6837ae4fae0d1d216612afa739c9dfefd6b277ab`**. Damit beziehen alle Kursteilnehmenden dieselben Dateien. Die Pakete enthalten **ungeprüfte Beispiele und Vorschläge, keine menschlich freigegebene Ground Truth**. Der Modellcheckpoint und der kuratierte Korpus der 134 Bestandsklassen werden zusätzlich von der Lehrperson bereitgestellt.

## 1. Paket auswählen und Arbeitsordner öffnen

| Paket | Inhalt | Verwendung |
| --- | --- | --- |
| `panoramax-studenten-2026-10-19.zip` | 100 Vollbilder, 214 Schild-Crops, 27 Sequenzen | Lernsammlung: herunterladen, prüfen und einsortieren; anschließend mit dem bereitgestellten Bestandskorpus zusammenführen. |
| `panoramax-beispiele-v6.zip` | 2 Vollbilder und 6 Crops; Teilmenge der Lernsammlung | Kleiner technischer Einstieg. Die Ortstafel-Crops sind nur 27 × 22 beziehungsweise 27 × 17 Pixel groß. |
| `panoramax-testkandidaten-2026-10-20.zip` | 39 HD-Vollbilder, 77 Crops; außerdem 246 SD-Bilder derselben acht Sequenzen | Für die Lehrperson und einen späteren gesonderten Abschlusstest reserviert. Die 39 HD-Bilder sind eine Teilmenge der 246 SD-Bilder. |
| `panoramax-externe-testkandidaten-2026-10-20.zip` | 15 Zielansichten: 2 Ortseingangs- und 13 Ortsausgangsvorschläge; 13 Standortkandidaten, 12 konservative Gruppen | Ebenfalls reserviert. 11 native 2D-Ansichten und 4 Perspektivansichten aus Panoramen; keine bestätigten unabhängigen Testfälle. |

Für die normale Studierendenübung benötigen Sie zunächst **nur die Lernsammlung**. Die beiden reservierten Pakete gehören nicht in Training, Validierung, Epochenwahl oder den normalen 70/15/15-Import. Für alle vier ZIP-Dateien zusammen werden bereits etwa 2,3 GB benötigt; entpackte Daten und spätere Arbeitskopien benötigen zusätzlichen Speicherplatz.

Wechseln Sie im KI-Server-Terminal vom Repository-Hauptordner in das Praktikum:

```sh
cd lectures/tsr-sgblur-de-2026-10-26/praktikum
mkdir -p data/downloads/packages
tsr_dataset_revision='6837ae4fae0d1d216612afa739c9dfefd6b277ab'
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

Die CLI heißt `hf`. Installieren Sie die drei festgelegten Versionen gemeinsam. Damit steht auch die von dieser CLI benötigte `click`-Abhängigkeit bereit. Aktivieren Sie diese Download-Umgebung nicht anstelle der von der Lehrperson vorbereiteten Trainingsumgebung. Hintergrund: [offizielle Hugging-Face-CLI-Dokumentation](https://huggingface.co/docs/huggingface_hub/guides/cli).

## 3. Die Lernsammlung herunterladen

```sh
.venv-hf/bin/hf download loffenauer/ws26_hspf_imo \
  packages/panoramax-studenten-2026-10-19.zip SHA256SUMS.txt \
  --type dataset --revision "$tsr_dataset_revision" \
  --local-dir data/downloads
```

Das ZIP liegt anschließend unter `data/downloads/packages/`; die veröffentlichte Prüfsummenliste liegt unter `data/downloads/SHA256SUMS.txt`. `--revision` legt den festen Stand fest, `--local-dir` den lokalen Downloadordner.

Falls Sie die CLI nicht verwenden können, laden diese HTTPS-Befehle dieselben zwei Dateien. Fahren Sie anschließend mit Abschnitt 4 fort:

```sh
tsr_dataset_base="https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/$tsr_dataset_revision"
curl --fail --location --retry 3 \
  --output data/downloads/SHA256SUMS.txt \
  "$tsr_dataset_base/SHA256SUMS.txt"
curl --fail --location --retry 3 \
  --output data/downloads/packages/panoramax-studenten-2026-10-19.zip \
  "$tsr_dataset_base/packages/panoramax-studenten-2026-10-19.zip"
```

## 4. Prüfsumme vor dem Entpacken vergleichen

Die veröffentlichte Liste enthält auch Dateien, die Sie nicht heruntergeladen haben. Der folgende Befehl wählt **genau die eine Zeile für die Lernsammlung** aus. Fehlt diese Zeile oder ist sie mehrfach vorhanden, wird die Prüfung nicht gestartet:

```sh
awk '$2 == "packages/panoramax-studenten-2026-10-19.zip" {print; n++} END {if (n != 1) exit 1}' \
  data/downloads/SHA256SUMS.txt > data/downloads/SHA256SUMS-lern.txt &&
  (cd data/downloads && sha256sum --strict -c SHA256SUMS-lern.txt)
```

Erwartet wird `packages/panoramax-studenten-2026-10-19.zip: OK`. Nur dann dürfen Sie entpacken. Bei einer Abweichung oder einem Downloadfehler stoppen Sie und klären die Ursache mit der Lehrperson. Fehlermeldungen werden nicht mit `--ignore-missing` oder ähnlichen Optionen unterdrückt.

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

Die beiden Bestandskorpuspfade stammen von der Lehrperson, nicht aus den ZIP-Paketen. Ergänzen Sie `--groups data/groups.csv`, wenn zusammengehörende Sequenzen festgelegt wurden. Unter den ursprünglichen Sequenzgruppen und dem unveränderten Seed `20261026` hat die Lernsammlung **keine Ortstafel-Testabdeckung**. Vor dem Modellversuch sind daher zusätzlich geeignete unabhängige Gruppen und die Abdeckung aller 134 Bestandsklassen zu klären. Ein erfolgreicher Download ist keine Trainings- oder Testfreigabe.

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

## 7. Nur Lehrperson: Testkandidaten getrennt reservieren

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

Bewahren Sie Archive, heruntergeladene Prüfsummenliste, festen Revisionswert und die enthaltenen bildbezogenen Herkunftsangaben auf. Bild-/Annotationsdaten stehen gemäß Quellen unter **CC BY-SA 4.0**; beigefügter Projektcode bleibt unter **AGPLv3**. Lesen Sie die [Dataset Card am festgelegten Stand](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/blob/6837ae4fae0d1d216612afa739c9dfefd6b277ab/README.md) und die beiliegenden Lizenzangaben. Verändern Sie beim Einsortieren keine Quellmanifeste oder Originaldateien.
