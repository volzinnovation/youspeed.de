# Prolix: tatsächliche Quellenprüfung und Einrichtung

Untersucht am 19.10.2026: GitLab-Quellstand `36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f`.
Quellarchiv tatsächlich von `https://gitlab.com/api/v4/projects/panoramax%2Fclients%2Fprolix/repository/archive.tar.gz?sha=36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f` geladen, nach `/private/tmp/prolix-source-36bb92b` entpackt und gelesen. Archiv-SHA256 `8b11f7bbac561d4dc29c7ac8a9ca2117bc9a5d92c542ec3218f1847a6330b8db`. Kein Paket installiert, kein heruntergeladener Code ausgeführt, kein Server geändert.

## Was Prolix in diesem Stand macht

README beschreibt ein Kommandozeilenwerkzeug für Erkennen/Klassifizieren, Zusammenführen/Positionieren und Hochladen. `prolix/main.py` und `docs/Commands.md` registrieren genau drei fachliche Befehle:

- `run-model-traffic-signs`: Bilder → Detektion → Ausschnitte → Zusatzzeichen-Detektion → Klassifikation → annotations.geojson.
- `analyze-traffic-signs`: vorhandene Annotationen geometrisch gruppieren/positionieren → tfsigns.geojson; kein Training und keine Qualitätsbewertung gegen Ground Truth.
- `upload-annotations`: Annotationen an die Panoramax Semantics API senden. Dies ist ein Schreibbefehl und gehört nicht zum hier vorbereiteten Lern-/Evaluationsablauf.

Es gibt keinen `train`, `evaluate`, `splittrain` oder Dataset-Split-Befehl. Die Quellcodesuche enthält keinen Trainingsaufruf `.train()`. Training und Ground-Truth-Evaluation müssen mit separaten Ultralytics-/Projektwerkzeugen erfolgen.

## Quellen und direkte, gepinnte Links

- https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/README.md
- https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/docs/Install.md
- https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/docs/Usage.md
- https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/docs/Commands.md
- https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/pyproject.toml
- https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/prolix/models.py
- https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/prolix/runners.py
- https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/prolix/runner_trafficsign.py

## Einrichtung als getrennte Lernumgebung (Rezept, nicht ausgeführt)

Die offizielle Installation klont das Repository, initialisiert Submodule, erstellt ein venv und installiert editable. Für ein reproduzierbares Lernrezept den Commit festhalten und das Submodule tatsächlich auschecken:

```bash
git clone https://gitlab.com/panoramax/clients/prolix.git prolix-study
cd prolix-study
git checkout --detach 36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f
git submodule update --init --recursive
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pip check
python -m pip freeze > environment.freeze.txt
prolix --help
```

Vorher CUDA-fähiges PyTorch passend zum vorhandenen Server/Treiber bereitstellen und die native TurboJPEG-Bibliothek prüfen. `pyturbojpeg==1.7.7` ist ein Python-Binding und lädt eine native Bibliothek. Eine vorhandene geprüfte Containerumgebung ist gegenüber einer Änderung des Produktions-Python vorzuziehen. `pyproject.toml` deklariert Python >=3.10 und u.a. ultralytics~=8.4.49, NumPy~=2.4.4, Pillow11.1.0, SciPy~=1.17.1. Der Quellcode nutzt jedoch `Path.walk()` und `TemporaryDirectory(delete=False)` (Python3.12 APIs); deshalb im Rezept Python3.12 statt bloßer Untergrenze3.10 verwenden. Ein Freeze nach Installation ist ein Laufzeitbeleg, kein vorher vorhandener vollständig aufgelöster Lock.

Nach Zuweisung einer freien Lehr-GPU durch die Serverbetreuung:

```bash
export CUDA_VISIBLE_DEVICES=ASSIGNED_GPU_UUID
python - <<'PY'
import torch
assert torch.cuda.is_available()
print(torch.__version__, torch.version.cuda)
print(torch.cuda.device_count(), torch.cuda.get_device_name(0))
PY
```

Den Platzhalter durch die freigegebene GPU-UUID ersetzen; keine Produktions-GPU aus einer Inventarliste ungeprüft übernehmen. Innerhalb dieser Umgebung erscheint die zugewiesene GPU als device0. Das Skript ist ein vorgeschlagener Smoke-Test, noch kein erfolgreich gemessener Lauf.

## Dokumentierter Offline-Inferenzablauf

Bilder müssen UUID-Dateinamen und externe Metadaten besitzen. Die offiziellen Download-Flags sind `--file-name id` und `--external-metadata-dir-name meta`:

```bash
panoramax_cli download \
  --api-url https://panoramax.youspeed.de \
  --user LEHRDATENSATZ_NUTZER \
  --path /mnt/nvme/LEHRPROJEKT/pictures \
  --file-name id \
  --external-metadata-dir-name meta \
  --quality sd

prolix run-model-traffic-signs \
  --models-path /mnt/nvme/LEHRPROJEKT/models \
  --tmp-path /mnt/nvme/LEHRPROJEKT/tmp-prolix \
  --parallel-tasks 1 \
  /mnt/nvme/LEHRPROJEKT/pictures \
  /mnt/nvme/LEHRPROJEKT/prolix-results

prolix analyze-traffic-signs \
  --annotations-path /mnt/nvme/LEHRPROJEKT/prolix-results/annotations.geojson \
  /mnt/nvme/LEHRPROJEKT/pictures \
  /mnt/nvme/LEHRPROJEKT/analyzer-results
```

Dies ist die echte CLI-Syntax, aber **kein fertiges deutsches Trainingsrezept**: Der Stockrunner ist in `models.py:212–218` auf YOLO11l, französischen Zusatzzeichendetektor und französischen Klassifikator eingestellt. `--models-path` ändert den Ablageort, nicht Land/Architektur. Ohne vorgelagerte Bereitstellung holt `HFModel.download()` Dateien von beweglichem `main`, ohne SHA-Prüfung. Für die DE-Übung daher die bereits vorhandene, gepinnte deutsche Projektpipeline und ein getrenntes Training/eine getrennte Evaluation verwenden; nicht den Stockrunner mit französischen Ausgaben als DE-Benchmark ausgeben.

Bei Verwendung des Upstreamrunners können die fest erwarteten lokalen Dateien `tf_detect_sign.pt`, `tf_detect_subsign.pt`, `tf_classify.pt` vorab aus den gepinnten Quellen provisioniert und gehasht werden. Ein deutscher Austausch würde zusätzlich Modellreferenz, Klassen-/Code-Normalisierung und Exportsemantik im Code benötigen. Er ist keine vorhandene CLI-Option.

Der temporäre Ordner enthält Status-CSV und Zwischen-Crops und erlaubt Wiederaufnahme. Vor einem neuen Modell-/Datensatzexperiment einen neuen temporären Ordner verwenden; sonst werden bereits bearbeitete Bilder übersprungen. `--parallel-tasks` bedeutet parallele Inferenzaufgaben, nicht GPU-Anzahl, Trainingsepochen oder Cross-Validation.

## DE310/311 Training und Evaluation sauber einordnen

Prolix liefert Daten-/Inferenzbausteine. Studierende müssen außerhalb dieses CLI: Annotationen prüfen, vollständige Szenen und Crops trennen, unabhängige Gruppen-Splits bauen, den deutschen Klassifikator um die zwei Klassen erweitern, Detektor nur bei nachgewiesenem Recall-Problem nachtrainieren und neue/alte Klassen auf einem unangetasteten Test vergleichen. Anschließend denselben ausgewählten Checkpoint als PyTorch, CoreML und LiteRT mit identischen Eingangsbildern prüfen. Mobile Laufzeit und End-to-End-Passage sind eigene Messungen.
