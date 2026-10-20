# Bildklassifikation mit KI

## Wie verbessere ich ein vorhandenes KI-Modell?

Montag, 26. Oktober 2026 · 27 Folien · 45 Minuten

Technischer Quellenstand: 19. Oktober 2026. Hugging-Face-Modellkarte und Trainingsversuch: 20. Oktober 2026. Datenpakete: 20. Oktober 2026, Hugging-Face-Commit 6837ae4fae0d1d216612afa739c9dfefd6b277ab. Repository-Links sind auf die dokumentierten HEAD-Revisionen gepinnt; tatsächlich gelesene Arbeitsdateien sind zusätzlich im Modellinventar gehasht.

## 1. Bildklassifikation mit KI

**0–0,5 Minuten · 0,5 Min.**

Die Vorlesung erklärt, wie wir mit menschlich geprüften Panoramax-Boxen und Bildausschnitte eine fehlende Modellfähigkeit ergänzen. Im Mittelpunkt stehen Ortseingang und Ortsausgang. Die gesamte Lehrsequenz dauert 45 Minuten einschließlich einer kurzen Partnerübung und Fragen. Der vollständige Trainingslauf findet danach als Projektarbeit statt. Der geprüfte technische Quellenstand ist der 19. Oktober; der Vortrag ist am Montag, 26. Oktober 2026.

Quellen:

- [TSR_PROLIX_ALIGNMENT_2026-09-10.md](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_PROLIX_ALIGNMENT_2026-09-10.md)

## 2. Am Ende können Sie einen Modellversuch aufsetzen

**0,5–1,5 Minuten · 1 Min.**

Der Einstieg ist für Studierende im 3. Semester ohne Vorwissen zu Machine Learning gedacht. Begriffe werden anhand von Bildbeispielen erklärt. Die Lehrperson stellt eine vorbereitete Python-/GPU-Umgebung, den geprüften 134-Klassen-Checkpoint und einen kuratierten Datenbestand bereit. Die Studierenden müssen keine eigene Netzarchitektur implementieren. Im Praktikum führen sie drei konkrete Skripte aus: Daten vorbereiten, trainieren und bewerten. Die feste Anleitung steht in praktikum/README.md. Vier öffentliche Panoramax-Datenpakete liegen auf Hugging Face unter loffenauer/ws26_hspf_imo. Sie enthalten ungeprüfte Bildausschnitte und Boxvorschläge. Der vollständige kuratierte Bestand der 134 alten Klassen und der Modellcheckpoint müssen weiterhin von der Lehrperson bereitgestellt werden. Ein Bildausschnitt (englisch Crop) ist der aus einer Box ausgeschnittene Teil eines Fotos. Ab hier verwenden die Folien den deutschen Begriff.

Quellen:

- [TSR_TRAINING_ROUND_TRIP.md](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_TRAINING_ROUND_TRIP.md)

## 3. Zwei Situationen: Box fehlt oder Klasse falsch

**1,5–3 Minuten · 1,5 Min.**

Situation 1: Im verlinkten Panoramax-Bild aus Dobel ist die Ortstafel sichtbar, für sie fehlt die gespeicherte Box. Das Gefahrzeichen rechts hat dagegen eine SGBlur-Box und die Klassifikation DE:101. Die abgerufene API enthält genau diese eine Annotation. Die Folie zeigt den gespeicherten Zustand und keinen neu ausgeführten Modelltest. Der orange Rahmen um das Gefahrzeichen ist eine vorhandene Panoramax-Annotation. Die gelbe Ortstafel darf nicht mit diesem erkannten Objekt verwechselt werden. Ohne passende Schildbox entsteht im üblichen Ablauf kein Bildausschnitt für die zweite Stufe. Situation 2: Die Bernbach-Tafel wurde lokalisiert, aber vom alten Klassifikator als bad ausgegeben. Für beide Fälle unterscheiden sich die zusätzlichen Trainingsdaten: Vollbilder plus Boxen für die Lokalisierung, geprüfte Bildausschnitte plus Zeichenklassen für die Klassifikation. Eine Annotation in Panoramax verbessert zunächst den Datenbestand. Gewichte ändern sich erst beim erneuten Lernen und werden danach als neuer Modellstand bereitgestellt. Beide Fotos: admin / Panoramax, CC BY-SA 4.0.

Quellen:

- [?focus=pic&pic=965b93dc-e04d-45aa-a4bf-a8bc20c9a106&seq=1cde254e-daab-4de3-b256-813984ea9620](https://panoramax.youspeed.de/?focus=pic&pic=965b93dc-e04d-45aa-a4bf-a8bc20c9a106&seq=1cde254e-daab-4de3-b256-813984ea9620)
- [965b93dc-e04d-45aa-a4bf-a8bc20c9a106](https://panoramax.youspeed.de/api/collections/1cde254e-daab-4de3-b256-813984ea9620/items/965b93dc-e04d-45aa-a4bf-a8bc20c9a106)
- [TSR_PROLIX_ALIGNMENT_2026-09-10.md#bernbach-zeichen-310-experiment](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_PROLIX_ALIGNMENT_2026-09-10.md#bernbach-zeichen-310-experiment)

## 4. Die Box stimmt – die neue Klasse fehlt

**3–4 Minuten · 1 Min.**

Das reale Bild stammt von admin / Panoramax, CC BY-SA 4.0. Die historische Box im 2376 × 4224 Pixel großen Bild lautet [1827,2244,2039,2392], also 212 × 148 Pixel. Das Experiment lief mit Core ML auf macOS-CPU und mit LiteRT im Android-Emulator. Es ist kein aktueller Benchmark physischer Telefone. Die spätere gespeicherte menschliche DE:310-Annotation ist vom früheren generischen Detektionsstand zu unterscheiden. Der Befund zeigt eine Klassifikationslücke: Der gepinnte Klassifikator hat die beiden Ortstafelklassen nicht. Ein Piktogramm oder Alias in der Referenztabelle erzeugt keinen zusätzlichen Netzausgang. Die angegebene Quelle classified_de_road_signs enthält die beschrifteten Trainingsbilder. Die Gewichte des verwendeten Klassifikators liegen im getrennten Modell-Repository classify_de_road_signs. Beide Links sind sichtbar. Der vorhandene Datensatz dokumentiert den Altbestand, der für DE:310/311 ergänzt werden soll. Die neue Quellenfolie nach YOLO erklärt diese Unterscheidung.

Quellen:

- [TSR_PROLIX_ALIGNMENT_2026-09-10.md#bernbach-zeichen-310-experiment](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_PROLIX_ALIGNMENT_2026-09-10.md#bernbach-zeichen-310-experiment)
- [city-entry-source.json](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/lectures/assets/city-entry-source.json)
- [prolix-de-class-catalog-v1.json](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/shared/tsr/prolix-de-class-catalog-v1.json)
- [classified_de_road_signs](https://huggingface.co/datasets/Panoramax/classified_de_road_signs)
- [classify_de_road_signs](https://huggingface.co/Panoramax/classify_de_road_signs)

## 5. Ein neuronales Netz lernt Gewichte aus Beispielen

**4–6,5 Minuten · 2,5 Min.**

Ein Pixel ist für das Netz zunächst eine Zahl. Ein Neuron kombiniert Eingaben als gewichtete Summe mit Bias; eine nichtlineare Aktivierung erlaubt komplexere Abbildungen als eine einzige lineare Rechnung. Viele verknüpfte Schichten liefern am Ende einen Score pro Klasse. Die Ausgänge müssen dem bekannten Klasseninventar entsprechen. Beim überwachten Lernen vergleichen wir die Ausgabe mit dem menschlichen Label. Cross-Entropy bestraft eine niedrige Wahrscheinlichkeit der richtigen Klasse. Backpropagation berechnet Gradienten, ein Optimizer aktualisiert Gewichte. Bei der Inferenz werden weder Labels benötigt noch Gewichte aktualisiert. Ein Softmax-Wert ist keine Garantie für die Richtigkeit auf einer unbekannten Situation. Die Grafik ist ein didaktisches Schema, keine Darstellung der konkreten YOLO-Architektur. Überwachtes Lernen bedeutet: Zu jedem Trainingsbild ist die richtige Klasse bekannt. Die Loss-Funktion vergleicht die Vorhersage mit dieser bekannten Lösung. Erst anschließend verändert der Optimizer die Gewichte.

Quellen:

- [buildmodel_tutorial.html](https://docs.pytorch.org/tutorials/beginner/basics/buildmodel_tutorial.html)
- [optimization_tutorial.html](https://docs.pytorch.org/tutorials/beginner/basics/optimization_tutorial.html)

## 6. CNNs lernen lokale Merkmale im Bild

**6,5–9 Minuten · 2,5 Min.**

CNN bedeutet Convolutional Neural Network. Kleine Filter betrachten lokale Nachbarschaften; ihre Gewichte werden räumlich geteilt. Das reduziert die Anzahl unabhängiger Parameter gegenüber einer voll verbundenen Schicht über alle Pixel. Mehrere Faltungen, Aktivierungen und räumliche Verdichtung erzeugen Merkmalskarten mit zunehmendem Kontext. Beim Klassifikator verdichtet ein Kopf diese Merkmale zu Klassenwerten. Für unsere Ortstafeln sind Farbe und Rechteckform allein nicht ausreichend: Wegweiser oder Werbung sind ähnliche Gegenbeispiele. Der rote Diagonalstrich des Ausgangsschilds und die vollständige Tafel müssen im Bildausschnitt erhalten bleiben. Beim Transfer Learning nutzen wir gelernte Merkmale des Ausgangsnetzes und passen Kopf beziehungsweise Teile des Backbones mit neuen geprüften Beispielen an. Mehr Parameter oder eine größere Datei garantieren keinen besseren unabhängigen Test. Im konkreten DE-Modell folgen auf Faltungen und C3k2-Merkmalsblöcke eine C2PSA-Attention-Stufe und der Classification Head. Dieser enthält eine 1×1-Faltung, Global Average Pooling, Dropout und eine lineare Schicht mit 1280 Eingangsmerkmalen und 134 Ausgaben. Das ist kein LeNet-Modell; historische CNN-Quellen dienen nur der Einordnung. Forschungsbezug: Jocher et al., Ultralytics YOLO26: Unified Real-Time End-to-End Vision Models, arXiv:2606.03748v1, 2. Juni 2026, Abschnitt 3.4 zur Klassifikation. Für den konkreten Checkpoint wurde zusätzlich die gespeicherte YAML-Konfiguration und der tatsächlich kompilierte Core-ML-Rechengraph geprüft. Die 512×7×7 Backbone-Ausgabe wird im Head durch eine 1×1-Faltung zu 1280 Kanälen und durch Global Average Pooling zu 1280 Werten. Die lineare Schicht hat 134×1280 Gewichte plus 134 Biaswerte. Die zwei zusätzlichen Klassen benötigen 2562 zusätzliche Parameter. Aussagen zu NMS-freien Detektoren aus dem YOLO26-Paper gelten nicht für unseren YOLO11-Detektor und sind keine Eigenschaft dieses Klassifikationskopfs.

Quellen:

- [cifar10_tutorial.html](https://docs.pytorch.org/tutorials/beginner/blitz/cifar10_tutorial.html)
- [](https://docs.ultralytics.com/tasks/classify/)
- [2606.03748v1](https://arxiv.org/abs/2606.03748v1)
- [yolo26-cls.yaml](https://github.com/ultralytics/ultralytics/blob/v8.4.56/ultralytics/cfg/models/26/yolo26-cls.yaml)
- [head.py](https://github.com/ultralytics/ultralytics/blob/v8.4.56/ultralytics/nn/modules/head.py)

## 7. Zwei Lernaufgaben hinter einer Erkennung

**9–10,5 Minuten · 1,5 Min.**

Die zwei Lernprobleme werden getrennt bewertet. Der Detektor kann weiterhin eine generische Klasse sign verwenden; die nationale Bedeutung muss nicht als zusätzliche Detektorklasse angelegt werden. Für seine Verbesserung benötigen wir ganze Bilder mit vollständigen Boxannotationen. Der Klassifikator erhält den ausgeschnittenen Bereich, bei der mobilen Inferenz einschließlich der dokumentierten Randzugabe. Gute Cropmetriken sagen noch nichts über übersehene Zeichen aus. Eine spätere Ereignis- beziehungsweise Passageentscheidung ist nochmals ein eigener Laufzeitschritt; sie wird durch dieses Training nicht neu definiert.

Quellen:

- [README.md](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/shared/tsr/README.md)
- [TrafficSignRuntime.swift](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/iphone/SpeedConsumerApp/TrafficSignRuntime.swift)
- [worker.py](https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/prolix_pipeline/worker.py)

## 8. YOLO: eine Modellfamilie für verschiedene Aufgaben

**10,5–12,5 Minuten · 2 Min.**

YOLO bezeichnet eine Modellfamilie und nicht ein einzelnes Verkehrszeichenmodell. Backbone bedeutet Rückgrat: Dieser Teil gewinnt Bildmerkmale wie Kanten und Formen. Der Neck verbindet fein und grob aufgelöste Merkmalskarten desselben Bilds, also Details und Überblick. Head bedeutet Kopf: Aus den Merkmalen berechnet der Detection Head Boxkoordinaten und Klassenscores. Beim hier verwendeten Klassifikator entfällt der Detektionsneck; der Classification Head liefert einen Score je Zeichenklasse. Die Bezeichnungen erklären die Aufgabe der Netzteile, nicht drei unabhängig trainierte Modelle. Ein Detektionsmodell lokalisiert mehrere Objekte. In der hier betrachteten YOLO11-Pipeline werden schwächer bewertete überlappende Vorschläge durch Non-Maximum Suppression unterdrückt. Ein Modell mit cls-Kopf klassifiziert dagegen einen gesamten Ausschnitt. Ein 224-Pixel-Cropklassifikator kann allein keine Tafel im vollständigen Kamerabild lokalisieren. n, s, m und l bezeichnen Architekturgrößen; cls bezeichnet die Aufgabe. Das deutsche Modell ist ein angepasstes YOLO26l-cls, während die mobile Lokalisierung YOLO11n nutzt. Es ist daher falsch, alle Projektmodelle pauschal YOLO11 zu nennen. Für unsere Übung benötigen wir nur Boxen und Klassen. Forschungsursprung: Redmon, Divvala, Girshick und Farhadi, You Only Look Once: Unified, Real-Time Object Detection, CVPR 2016. Das ist die historische Grundidee der gemeinsamen Box- und Klassenvorhersage, nicht die konkrete Architektur unseres neueren Checkpoints. Der verwendete YOLO11n-Detektor hat Conv/C3k2-Merkmalsblöcke, SPPF und C2PSA, führt Merkmale in einem FPN/PAN-Neck auf drei Skalen zusammen und verwendet einen separaten Detection Head mit DFL und NMS. Ultralytics nennt für YOLO11 ausdrücklich kein formales Forschungspaper; hierfür werden die offizielle Softwaredokumentation und die passende Konfiguration zitiert.

Quellen:

- [](https://docs.ultralytics.com/tasks/detect/)
- [](https://docs.ultralytics.com/tasks/classify/)
- [metadata.json](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/iphone/SpeedConsumerApp/TSRModelPacks/DE.panoramax-bootstrap.tsrmodelpack/classify_de_road_signs.mlmodelc/metadata.json)
- [1506.02640v5](https://arxiv.org/abs/1506.02640v5)
- [](https://docs.ultralytics.com/models/yolo11/)
- [yolo11.yaml](https://github.com/ultralytics/ultralytics/blob/v8.4.56/ultralytics/cfg/models/11/yolo11.yaml)

## 9. Trainingsbilder und Modellgewichte

**12,5–13,5 Minuten · 1 Min.**

Der Datensatz enthält beschriftete Bildausschnitte, das Modell enthält gelernte Gewichte. Die Dataset Card beschreibt über 20.000 Zeichenbilder in über 130 Klassen, darunter bad und other. Die Bilder stammen überwiegend aus deutschen Panoramax-Aufnahmen, ergänzt um ähnliche Zeichen aus anderen europäischen Ländern mit Länderpräfix im Dateinamen. Lizenz laut Dataset Card: CC BY-SA 4.0. Für den Kurs werden Herkunft und Urheber beibehalten. Der verwendete Datenstand ist b4856947ed7cb6312587258acc90e8cf88a4aa13. Die geprüften Archive enthalten 13.287 beziehungsweise 6.944 Bilddateien, davon 522 exakt gleiche Bilder in beiden Archiven. Nach Deduplizierung verbleiben 19.709 Bilder. Diese ursprüngliche Aufteilung ist deshalb kein unabhängiger Abschlusstest. Im dokumentierten Kursversuch wurden Duplikate und zusammengehörende Bildquellen vor der neuen Aufteilung berücksichtigt. Der Ausgangscheckpoint kann die alten Bilder dennoch bereits kennen. Seine Prüfung bleibt ein rückblickender Regressionstest. Die beiden neuen Ortstafelklassen und neue unabhängige Prüfgruppen kommen aus unserer geprüften Sammlung hinzu. Es wird ein vorhandener Datensatz erweitert und ein vorhandenes Modell weitergelernt. Nicht jedes Datenrepository enthält Gewichte. Quellenprüfung: source/hf-model-card-review-2026-10-20.json. Ergänzender Kartenbeleg: source/dataset-card-review-2026-10-20.json.

Quellen:

- [README.md](https://huggingface.co/datasets/Panoramax/classified_de_road_signs/blob/b4856947ed7cb6312587258acc90e8cf88a4aa13/README.md)
- [README.md](https://huggingface.co/Panoramax/classify_de_road_signs/blob/5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790/README.md)

## 10. Modelle: Gewichte, Dateien und App-Speicher

**13,5–15 Minuten · 1,5 Min.**

Die Parameter wurden tatsächlich in den SHA-256-geprüften Originalcheckpoints auf der CPU gezählt: sum(p.numel() for p in model.parameters()). Detektor 2.590.425, deutscher Klassifikator 13.006.278 Parameter einschließlich Bias und eingefrorener Parameter. Der Detektor enthält 16 feste DFL-Projektionsparameter. FP16-Parameterbytes sind 5.180.850 beziehungsweise 26.012.556; Dateiverpackung und Puffer zählen zusätzlich. Die Dateigrößen werden auf volle dezimale MB gerundet. Detektor: Original 5.979.923 Byte, Core ML 5.576.860, LiteRT 5.669.818 → jeweils 6 MB. Klassifikator: 26.282.865, 26.175.294, 26.080.976 → jeweils 26 MB. Die sichtbaren Android-App-Puffer sind aus dem aktuellen Quellcode berechnete Kapazitäten: 34.649.600 Byte für den Detektor und 1.004.056 Byte für den Klassifikator. Diese Werte sind keine Messung des vollständigen RAM-Bedarfs; Gewichte, Runtime-Arenen, Zwischenaktivierungen, GPU-Kopien, Kamera und Karte kommen hinzu. Eine getrennte RAM-Messung je Modell liegt nicht vor. Als App-Gesamtbeispiele stehen ein neuer Android-PSS-Snapshot von 645,67 MB am 19.10.2026 und ein historischer iPhone-physical-footprint-Sample von 231,93 MB am 01.10.2026 zur Verfügung. Unterschiedliche Last, Versionen und Messgrößen: daraus keinen Plattformvergleich ableiten. Rohbelege und Berechnung stehen in source/model-weights-evidence.json und source/model-memory-evidence.json. Die Links öffnen die gepinnten tatsächlichen Modellquellen. Die sichtbare HF-Quelle benennt Panoramax/classify_de_road_signs ausdrücklich. Dieser exakt gepinnte Checkpoint ist die Ausgangsbasis des Fine-Tuning-Beispiels auf Folie 20. Die Modellkarte nennt das Training mit Panoramax/classified_de_road_signs. Ihre 98,6 Prozent Accuracy sind eine selbst berichtete Herausgeberangabe und nicht unser Testergebnis. Lizenzangaben getrennt lesen: Modellkarte Etalab 2.0, Bilddatensatz CC BY-SA 4.0 und Ultralytics-Software AGPL-3.0 beziehungsweise Enterprise. Prüfbeleg: source/hf-model-card-review-2026-10-20.json.

Quellen:

- [training-sources-v1.json](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/shared/tsr/training-sources-v1.json)
- [end-sign-review-2026-09-24.md](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/shared/tsr/end-sign-review-2026-09-24.md)
- [android-export-report.json](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/provenance/android-export-report.json)
- [classify_de_road_signs](https://huggingface.co/Panoramax/classify_de_road_signs)

## 11. SGBlur erkennt Boxen; Prolix ergänzt die Bedeutung

**15–16 Minuten · 1 Min.**

Namens- und Projektherkunft: SGBlur wird im originalen README als Panoramax „Speedy Gonzales“ Blurring Algorithm bezeichnet. Das ursprüngliche Repository liegt unter cquest/sgblur; das Projekt wurde nach gitlab.com/panoramax/server/sgblur verlegt. Prolix ist ein Kommandozeilenwerkzeug des Panoramax-Projekts zur Objekterkennung und Klassifikation. Das pyproject.toml nennt Adrien Pavie als Autor. Eine weitergehende Etymologie des Namens Prolix wird in den geprüften Primärquellen nicht erklärt und deshalb hier nicht behauptet. Beide Originalprojekte sind direkt auf der Folie verlinkt. Der gepinnte SGBlur-Quellstand verwendet YOLO11 für die drei Klassen sign, plate und face. Die Detektions-API profitiert von CUDA. Der separate Blur-Dienst bearbeitet die erkannten sensiblen JPEG-Bereiche auf der CPU; Schildbereiche sind davon ausgenommen. Normale JPEG-MCU-Pfade erhalten andere Bildteile, doch es gibt Sonderpfade mit Rekodierung. Der derzeitige landesspezifische Prolix-kompatible Serveradapter nimmt bestehende Annotationen, schneidet aus der bereits verwischten Bildableitung aus und klassifiziert. Ein größerer Detektor im Modellregister belegt nicht, dass dieser Worker ihn ausführt. Wenn wir den gemeinsam verwendeten SGBlur-Detektor nachtrainieren, dürfen seine Gesicht-/Kennzeichenfähigkeiten nicht unbeachtet verloren gehen.

Quellen:

- [README.md](https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/README.md)
- [detect.py](https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/src/detect/detect.py)
- [blur.py](https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/src/blur/blur.py)
- [README.md](https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/README.md)
- [pyproject.toml](https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/pyproject.toml)
- [sgblur](https://gitlab.com/panoramax/server/sgblur)
- [worker.py](https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/prolix_pipeline/worker.py)
- [prolix-ki-server-runbook.md](https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/docs/prolix-ki-server-runbook.md)

## 12. Ein Klassifikator-Checkpoint, drei Laufzeitformate

**16–17,5 Minuten · 1,5 Min.**

Die Quellhashes in den Modellmanifesten und im Serverregister verweisen auf denselben deutschen Klassifikator. Linux verwendet den PyTorch-Checkpoint, Android einen LiteRT-Export und iPhone das Core-ML-Artefakt. Es sind unterschiedliche Dateien. Die gesamte Detektionspipeline ist nicht identisch: SGBlur kann andere Modellgrößen und mehrere Bildauflösungen verwenden; mobil läuft nano bei 1280. Die Croprandzugabe ist im Serveradapter 15 Prozent rundum, mobil asymmetrisch. Auch Rundungen und Nachverarbeitung können Ergebnisse ändern. Nach dem Training frieren wir einen ausgewählten Checkpoint ein, exportieren ihn und vergleichen denselben Korpus mit expliziten numerischen Toleranzen und gleicher Klassensemantik.

Quellen:

- [TSR_EXPORT_AND_SOURCE_PROVENANCE.md](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_EXPORT_AND_SOURCE_PROVENANCE.md)
- [models.json](https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/deploy/prolix/models.json)
- [manifest.json](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/iphone/SpeedConsumerApp/TSRModelPacks/DE.panoramax-bootstrap.tsrmodelpack/manifest.json)
- [manifest.json](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/manifest.json)

## 13. Welche Hardware rechnet die Inferenz?

**17,5–19,5 Minuten · 2 Min.**

Serverinventar vom 18. Oktober: Host-GPU 0 A5000, GPU 1 RTX PRO 6000 Blackwell Max-Q Workstation Edition, GPU 2 A5000. Prolix hat als Compose-Default CUDA_VISIBLE_DEVICES=1 und wählt intern cuda:0. Das ist die logische erste sichtbare GPU und keine zusätzliche Grafikkarte. Aufgezeichnete Canaries belegen CUDA-Ausführung, aber ein externes .env kann den Default überschreiben. Das Inventar ordnet SGBlur-Prozesse nicht sicher einer bestimmten Host-GPU zu. Auf Android ist GPU-Ausführung auf dem Moto g86 5G mit Mali-G615 MC2 dokumentiert. Historische gleiche Referenz: Median 521,59 ms GPU gegenüber 1419,33 ms CPU; kein allgemeines FPS-Versprechen. iPhone fordert .all an: Core ML entscheidet über CPU, GPU und Neural Engine. Die Neural Engine ist keine GPU. Eine konkrete Operationszuordnung müsste mit Xcode-Profiling gemessen werden.

Quellen:

- [server-status.json](https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/docs/youspeed/operations-evidence/2026-10-18-ki-ocr/server-status.json)
- [compose.yml](https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/deploy/prolix/compose.yml)
- [classifier.py](https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/prolix_pipeline/classifier.py)
- [ANDROID_TSR_DEVICE_DIAGNOSIS_2026-09-14.md](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/ANDROID_TSR_DEVICE_DIAGNOSIS_2026-09-14.md)
- [all](https://developer.apple.com/documentation/coreml/mlcomputeunits/all)
- [gpu](https://developers.google.com/edge/litert/android/gpu)

## 14. Die Vorverarbeitung gehört zum Modellvertrag

**19,5–20,5 Minuten · 1 Min.**

Die mobile Klassifikation skaliert den vorgesehenen Bildausschnitt auf 224 × 224. Ein Default-CenterCrop kann bei einer breiten Ortstafel den Rand oder den Ausgangsstrich entfernen. Der Lernentwurf im Praktikum ersetzt deshalb die Standardtransformationen und verwendet den passenden Validator. Die exakte Interpolation und Pixelwerte müssen für strenge Parität dennoch geprüft werden. Bei Android heißt das Gewichtsartefakt float16, seine äußeren Eingabe-/Ausgabetensoren sind aber float32. Der Detektor hat NHWC [1,1280,1280,3] und Ausgabe [1,7,33600]; die sieben Werte sind vier Boxkoordinaten plus drei Objektklassen. Der Klassifikator hat [1,224,224,3] zu [1,134]. NMS ist in der Core-ML-Pipeline enthalten und auf Android nativ implementiert.

Quellen:

- [TrafficSignRuntime.swift](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/iphone/SpeedConsumerApp/TrafficSignRuntime.swift)
- [AndroidTrafficSignRuntime.kt](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/android/app/src/main/java/de/youspeed/android/alpha/AndroidTrafficSignRuntime.kt)
- [android-export-report.json](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/provenance/android-export-report.json)
- [#custom-transforms](https://docs.ultralytics.com/tasks/classify/#custom-transforms)

## 15. Panoramax: Box zeichnen, Bedeutung prüfen

**20,5–22,5 Minuten · 2 Min.**

Zeigen Sie die vorhandene Bernbach-Annotation im Screenshot oder öffnen Sie das Bild mit einem vorbereiteten Kurskonto. Der Screenshot dokumentiert einen vorhandenen Zustand; für die Vorlesung wurden keine Annotationen verändert. In Panoramax lautet der Schlüssel osm|traffic_sign, in OSM traffic_sign. Frontansicht, Rückseite und Verdeckung bewusst unterscheiden. Bei vorhandener generischer Schildbox die Semantik korrigieren statt ein Duplikat darüberzulegen. Geometrieänderungen benötigen laut API eine Ersatzannotation; das ist eine Aufgabe für das tatsächlich berechtigte Kursteam. Bei unlesbarer oder unklarer Tafel markieren wir Unsicherheit statt zu raten. Nach dem Speichern erneut öffnen und Box sowie Semantik gegenprüfen. Der gespeicherte Screenshot steht als Demo-Reserve bereit. Das ergänzte Dobel-Bild und seine aktuelle Annotation wurden über Viewer und API lesend geprüft. Die beiden Codes ausdrücklich vorlesen: DE:310 bedeutet Ortseingang, DE:311 bedeutet Ortsausgang. Der Wert wird am Objekt unter dem Schlüssel osm|traffic_sign gespeichert.

Quellen:

- [?pic=a458609a-bbf1-413a-a039-5e0f685e9923&focus=pic](https://panoramax.youspeed.de/?pic=a458609a-bbf1-413a-a039-5e0f685e9923&focus=pic)
- [](https://docs.panoramax.fr/backend/install/deep_dive/semantics/)
- [ASSET_CREDITS.md](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/lectures/ASSET_CREDITS.md)

## 16. Der Crawler sammelt Beispiele für beide Modelle

**22,5–24 Minuten · 1,5 Min.**

Das bereitgestellte Skript praktikum/crawl_panoramax.py liest vorhandene Panoramax-Objektannotationen und lädt die verfügbaren HD-Bildableitungen. Es führt keinen Detektor oder Klassifikator aus und verändert die Instanz nicht. Es sammelt zwei ungeprüfte Sätze unter data/collection/inbox: vollständige Bilder samt allen erkannten vorhandenen Boxannotationen für den Detektor sowie einen Bildausschnitt je Schildannotation für den Klassifikator. Die Studierenden prüfen die Beispiele und verschieben die Bildausschnitte in approved/classifier/<klassenordner>; der Ordner bestimmt das korrigierte Klassenlabel. Die Ordner city__start und city__end entsprechen intern city:start beziehungsweise city:end. Unbekannte Schildklassen können ebenfalls den bereitgestellten Bestandsordnern zugeordnet werden. Für den Detektor wird der komplette Ordner mit image.png, labels.txt und metadata.json nach approved/detector/<bild-ID> verschoben. Dies bestätigt ausdrücklich die vollständige Prüfung aller drei Klassen sign, plate und face; eine vorhandene Schildannotation allein beweist diese Vollständigkeit nicht. Fehlende oder falsche Boxen müssen zunächst in Panoramax korrigiert und erneut abgerufen werden. Verschieben korrigiert keine Boxgeometrie. Öffentliche HD-Ableitungen können bereits anonymisiert sein; sie belegen keine Erkennung ungeblurter Gesichter und Kennzeichen. Metadaten, Lizenz, Autor, IDs und SHA-256 bleiben im Manifest erhalten. Der Crawler nutzt nur GET, folgt ausschließlich den next-Links der Seiten und dokumentiert Limits oder unvollständige Abrufe. Panoramen werden im Einstieg übersprungen; HD-Boxen werden nicht unverändert auf SD-Bilder übertragen. Einzelheiten und Verschiebebeispiele stehen in praktikum/SAMMELN_UND_SORTIEREN.md. Als vorbereiteten Einstieg verwenden Sie die vier veröffentlichten Datenpakete unter https://huggingface.co/datasets/loffenauer/ws26_hspf_imo. Der Crawler bleibt für eigene Ergänzungen verfügbar. Die große Lernsammlung enthält 100 Vollbilder und 214 Bildausschnitte. Die beiden kleinen Demobilder sind bereits darin enthalten. Die zwei zusätzlichen Kandidatenpakete bleiben für die Lehrperson reserviert und gelangen nicht in den normalen Trainingsimport. Die Downloadanleitung praktikum/DATEN_HERUNTERLADEN.md nennt den unveränderlichen Dataset-Commit 6837ae4fae0d1d216612afa739c9dfefd6b277ab, Prüfsummen und die tatsächlichen Archivwurzeln. Alle Dateien bleiben bis zur menschlichen Prüfung ungeprüft.

Quellen:

- [select_panoramax_end_signs.py](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/select_panoramax_end_signs.py)
- [diagnostic_dataset.py](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/diagnostic_dataset.py)
- [](https://docs.panoramax.fr/backend/install/deep_dive/semantics/)
- [](https://docs.panoramax.fr/backend/dev/STAC_compatibility/)
- [#panoramax_cli-download](https://docs.panoramax.fr/cli/COMMANDS/#panoramax_cli-download)
- [6837ae4fae0d1d216612afa739c9dfefd6b277ab](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/tree/6837ae4fae0d1d216612afa739c9dfefd6b277ab)

## 17. Eine feste Struktur für Training, Validierung und Test

**24–26 Minuten · 2 Min.**

Die Studierenden ordnen nur Klasse und Eignung zu, nicht den Split. import_sorted_folders.py liest die geprüften Ordner, verifiziert Dateien und Hashes und übernimmt Bild-/Annotations-/Sequenzidentität aus dem Crawler-Manifest. Standardmäßig bleibt eine ganze Sequenz zusammen. Physisch gleiche Tafeln oder zusammengehörende Fahrten über mehrere Sequenzen müssen vorab über die gemeinsame Gruppen-CSV zusammengeführt werden; das Skript entdeckt solche Beziehungen nicht selbst. Beide Sätze verwenden dieselbe Funktion partition_for_group und Seed 20261026 mit Zielanteilen 70/15/15. Ein Vollbild und alle seine Bildausschnitte bleiben dadurch im gleichen Split. Der Detektorsatz liegt anschließend direkt unter data/reviewed/detector mit images, labels und data.yaml. Für den Klassifikator entstehen data/reviewed/classifier/annotations.csv und images. Der zusätzliche bereitgestellte Bestand alter Klassen kann beim Import zusammengeführt werden. Anschließend materialisiert prepare_dataset.py mit diesen beiden Eingabepfaden den festen Ordner data/dataset für die unveränderten Trainings-/Evaluationsskripte. Hierzu lautet der Befehl: python prepare_dataset.py --annotations data/reviewed/classifier/annotations.csv --images data/reviewed/classifier/images. Alle 136 Klassen müssen im Klassifikatortraining vertreten sein. Fehlende Prüfklassen führen später weiterhin zu UNVOLLSTAENDIG. Das lokale Panoramax-Korpus garantiert keine vollständige Abdeckung aller alten Klassen. Bereits eingefrorene Tests werden nicht für bessere Ergebnisse neu aufgeteilt. Die zusätzlichen Hugging-Face-Testkandidaten sind ausdrücklich aus diesem normalen 70/15/15-Import ausgeschlossen. Die Lehrperson hält sie getrennt, prüft Klassen, vollständige Boxen und gemeinsame physische Standorte beziehungsweise Fahrten und erstellt erst danach einen eigenen eingefrorenen Testexport. Der bisherige Evaluator benötigt dafür einen gesonderten Modus und darf nicht durch geänderte Checkpoint-Metadaten umgangen werden.

Quellen:

- [group_splits_v2.py](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/group_splits_v2.py)
- [TSR_TRAINING_ROUND_TRIP.md](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_TRAINING_ROUND_TRIP.md)
- [training-sources-v1.json](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/shared/tsr/training-sources-v1.json)

## 18. Prolix einrichten und seine Rolle verstehen

**26–28 Minuten · 2 Min.**

Die offizielle Installation und der tatsächliche Quellstand wurden gelesen. Der hier gezeigte Commit ist derselbe ältere Upstreamstand wie im Deployment. Er bietet run-model-traffic-signs, analyze-traffic-signs und upload-annotations; keinen Trainings- oder Evaluationsbefehl. Der Stockrunner ist französisch festgelegt und --models-path ändert nur den Speicherort. Aktuelles main dokumentiert inzwischen --country DE; diese Option darf nicht auf die alte Version übertragen werden. Der Projektadapter im Schwesterrepo ergänzt die Länderlogik. Wir verwenden Python 3.12, weil der gelesene Quellcode Path.walk und weitere 3.12-APIs nutzt. Vor der Installation müssen im separaten Kursimage CUDA-fähiges Torch und die native TurboJPEG-Bibliothek bereitstehen. pip freeze hält das Ergebnis fest; für reproduzierbare Kurse benötigen wir zusätzlich einen vorab aufgelösten Lock und Image-Digest. Der lange Installationsblock wird erläutert, nicht live im Produktionsdienst ausgeführt.

Quellen:

- [Install.md](https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/docs/Install.md)
- [pyproject.toml](https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/pyproject.toml)
- [models.py](https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/prolix/models.py)
- [Commands.md](https://gitlab.com/panoramax/clients/prolix/-/blob/main/docs/Commands.md)
- [requirements.txt](https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/deploy/prolix/requirements.txt)

## 19. Datenpakete auf dem KI-Server herunterladen

**28–31 Minuten · 3 Min.**

Die Lehrperson stellt den KI-Server-Zugang, den Kursordner und die Trainingsumgebung bereit. Beginnen Sie im Ordner praktikum. Die öffentliche Quelle lautet https://huggingface.co/datasets/loffenauer/ws26_hspf_imo. Ein Hugging-Face-Konto oder Token ist für diese Downloads nicht erforderlich. Die getestete Anleitung installiert huggingface_hub==1.10.2, typer==0.24.1 und click==8.3.2 im separaten Venv .venv-hf. Der sichtbare Pfad .venv-hf/bin/hf verändert die Torch-Trainingsumgebung nicht. Der sichtbare Befehl lädt die große Lernsammlung und die zugehörige Prüfsummenliste nach data/downloads. Der volle Commit 6837ae4fae0d1d216612afa739c9dfefd6b277ab fixiert den geprüften Datenstand. Er ist ein Versionsbezeichner und kein Passwort. Laden Sie zusätzlich SHA256SUMS.txt aus derselben Revision und vergleichen Sie die relevante Prüfsumme vor dem Entpacken. Die Anleitung zeigt auch den kleinen Demo-Download, den HTTPS-Weg und die korrekten Archivpfade. Beide Demo-Bilder sind eine Teilmenge der 100er-Sammlung. Die zwei weiteren Pakete sind reservierte Testkandidaten: eigene Instanz mit 39 HD-Bildern und 77 Bildausschnitte samt 246 SD-Vorschauen sowie externe Quellen mit 15 Zielansichten, davon zwei DE:310- und 13 DE:311-Vorschläge. Die 39 HD-Bilder sind eine Teilmenge der SD-Bilder, mehrere Zielansichten können dieselbe Tafel zeigen. Alle Pakete enthalten ungeprüfte Vorschläge. Kopieren Sie die Testkandidaten nicht in data/collection, verwenden Sie sie nicht für Epochen- oder Hyperparameterwahl und wenden Sie darauf nicht den normalen 70/15/15-Importer an. Vor dem Training müssen die Studierenden die Lernsammlung prüfen und einsortieren. Vollständige sign-, plate- und face-Boxen sind für eine Detektorfreigabe nötig. Der 134-Klassen-Bestandskorpus und der Baselinecheckpoint kommen weiterhin separat von der Lehrperson. Die Quelle ist öffentlich unter CC BY-SA 4.0 mit bildbezogenen Urhebern dokumentiert; Quellmetadaten und Lizenz bleiben erhalten.

Quellen:

- [6837ae4fae0d1d216612afa739c9dfefd6b277ab](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/tree/6837ae4fae0d1d216612afa739c9dfefd6b277ab)
- [SHA256SUMS.txt](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/6837ae4fae0d1d216612afa739c9dfefd6b277ab/SHA256SUMS.txt)
- [cli#download-files](https://huggingface.co/docs/huggingface_hub/guides/cli#download-files)

## 20. Fine-Tuning mit dem Panoramax-Modell

**31–33 Minuten · 2 Min.**

Fine-Tuning bedeutet, die Gewichte eines bereits trainierten Modells mit passenden beschrifteten Beispielen weiter zu optimieren. Die vorhandenen Bildmerkmale dienen als Ausgangspunkt. Beim Training von Grund auf wären die Gewichte zunächst zufällig. In unserem TSR-Versuch optimiert der Trainingsloop alle Modellgewichte weiter. Eine Variante friert einige Schichten ein und lernt nur die übrigen weiter. Das ist eine bewusste Trainingsentscheidung, keine automatische Eigenschaft des Begriffs. Prolix bindet den Klassifikator ein; der konkrete Gewichteanbieter ist Panoramax auf Hugging Face. Die Modellkarte nennt eine Feinabstimmung auf Panoramax/classified_de_road_signs und YOLOv26. Unser tatsächlich geprüfter Checkpoint ist YOLO26l-cls mit 134 Klassen und 13.006.278 Parametern. Ausgangsdatei classify_de_road_signs.pt, Revision 5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790, SHA-256 f8277a3790fd3357b3ca31a086c7dc9f365785c7fa44bfd3b5c68834555699c7, 26.282.865 Byte. Genau diese Basis wurde am 20.10.2026 auf dem KI-Server verwendet. Die Lehrperson legt sie nach Prüfung unter models/baseline.pt ab. praktikum/train.py liest den festen Datensatz und erweitert den Classification Head: Die 134 alten Zeilen bleiben anfangs namens- und indexgetreu erhalten, zwei neue Zeilen für city:start und city:end werden initialisiert. Das ergänzt 2.562 Parameter und ergibt 13.008.840 Parameter. Die Studierenden verwenden den bereitgestellten PyTorch-Trainingsloop. RGB-Bildausschnitte werden vollständig auf 224×224 skaliert und mit 1/255 normalisiert. Im dokumentierten Lauf enthielt das Training 13.603 alte Bildausschnitte plus 38 Ortstafeln, die Validierung 3.077 alte Bildausschnitte plus acht Ortstafeln. AdamW, Lernrate 0,0001, Seed 20261026, RTX A5000. Die Validierung wählte nach 20 Epochen den Stand aus Epoche 4 anhand des Macro-F1. Der Test blieb bis zur Auswahl zurückgehalten. Eine Epoche ist ein Durchlauf durch die Trainingsbilder. runs/versuch-01 enthält Konfiguration, progress.csv und weights/best.pt. Die 98,6 Prozent Accuracy auf der Modellkarte sind eine selbst berichtete Herausgeberangabe. Sie stammen nicht aus unserem Prüfbestand und belegen keine Qualität für DE:310/311. Zusätzlich überlappen die veröffentlichten train/val-Archive um 522 exakt gleiche Bilder. Unser dokumentierter Vergleich gruppiert solche Duplikate vor der Aufteilung. Die alten Bilder können dem Ausgangsmodell dennoch bekannt sein, daher bleibt dieser Teil ein rückblickender Regressionstest. Siehe source/hf-model-card-review-2026-10-20.json und TRAININGSERGEBNISSE-2026-10-20.md. Der neue Kandidat enthält state_dict und Metadaten und benötigt model_utils.load_candidate(). Der Core-ML-/LiteRT-Export dieses Kandidaten ist noch nicht getestet.

Quellen:

- [README.md](https://huggingface.co/Panoramax/classify_de_road_signs/blob/5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790/README.md)
- [b4856947ed7cb6312587258acc90e8cf88a4aa13](https://huggingface.co/datasets/Panoramax/classified_de_road_signs/tree/b4856947ed7cb6312587258acc90e8cf88a4aa13)
- [transfer_learning_tutorial.html](https://docs.pytorch.org/tutorials/beginner/transfer_learning_tutorial.html)
- [train_fr_end_sign_classifier.py](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/train_fr_end_sign_classifier.py)
- [#custom-transforms](https://docs.ultralytics.com/tasks/classify/#custom-transforms)
- [prolix-de-class-catalog-v1.json](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/shared/tsr/prolix-de-class-catalog-v1.json)
- [bootstrap_sources.py](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/bootstrap_sources.py)

## 21. Nur bei fehlenden Boxen den Detektor nachtrainieren

**33–34 Minuten · 1 Min.**

Das Ortstafelprojekt benötigt nicht zwingend zwei neue Detektorklassen. Wenn die generische Lokalisierung bereits funktioniert, liegt der erste Hebel beim Klassifikator. Falls auf einem unabhängigen Vollbildsatz Tafelboxen fehlen, können zusätzliche Boxannotationen und ein Detektorversuch nötig sein. Aus Pixelbox [xmin,ymin,xmax,ymax] entstehen normierter Mittelpunkt cx,cy und Breite/Höhe. Zur Prüfung die Labels wieder auf das Bild zeichnen. Für Vollbilder alle relevanten Objekte vollständig annotieren; unvollständige Ziele erzeugen falsches Hintergrundtraining. Beim gemeinsamen SGBlur-Modell gehören face und plate zum Regressionstest, weil diese Ausgänge der Anonymisierung dienen. Das neue Importskript liefert data/reviewed/detector/data.yaml mit der festen Klassenreihenfolge 0=sign, 1=plate, 2=face. Die Lehrperson stellt models/detector-baseline.pt als geprüften SGBlur-YOLO11n-Checkpoint bereit. Ein Vollbild wird erst nach vollständiger Prüfung aller Klassen in den Trainingssatz übernommen. Wenn Validierung oder Test mangels unabhängiger Gruppen leer sind, sind weitere Daten nötig; die Gruppen werden nicht neu gewürfelt. Ultralytics verwendet die vorbereiteten Pfade und wählt den Trainingskandidaten anhand der Validierung. Der Test wird erst nach Auswahl mit yolo detect val ... split=test ausgeführt. Für den Detektor werden die per-class Metriken von Ausgangsmodell und Kandidat auf denselben zurückgehaltenen Vollbildern verglichen. Der technische Crawler-Test ist keine echte Trainings- oder Qualitätsmessung. Fine-Tuning kann auf ausgewählte Teile beschränkt werden. Unser dokumentierter SGBlur-Versuch vom 20.10.2026 war eine solche begrenzte Anpassung: 195 Skalare der finalen sign-Ausgänge wurden weitergelernt, alle übrigen Gewichte und BatchNorm-Zustände blieben eingefroren. Er ist nicht mit dem gezeigten allgemeinen Volltraining gleichzusetzen. Weil vollständige ungeblurte face-/plate-Annotationen fehlen, belegen die verbesserten bekannten Schildboxen keine vollständige Anonymisierungsqualität. Einzelheiten stehen in TRAININGSERGEBNISSE-2026-10-20.md.

Quellen:

- [detect.py](https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/src/detect/detect.py)
- [](https://docs.ultralytics.com/datasets/detect/)
- [TSR_PROLIX_ALIGNMENT_2026-09-10.md](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_PROLIX_ALIGNMENT_2026-09-10.md)

## 22. Precision, Recall und F1 beim Klassifizieren

**34–36 Minuten · 2 Min.**

Alle Zahlen dieser Folie sind frei erfunden und dienen ausschließlich zum Rechnen. Die echten Messwerte folgen erst auf der nächsten Folie. Jeder Bildausschnitt enthält genau eine Tafel und das Spielzeugmodell kann nur DE:310 oder DE:311 vorhersagen. Die Box ist bereits vorgegeben. Hier wird die richtige Klasse bewertet, nicht das Finden einer Box. Beginnen Sie mit den tatsächlichen Klassen in den Zeilen: sechs Ortseingänge, vier Ortsausgänge. In den Spalten steht die Modellvorhersage. Für DE:310 liegen vier richtige Zuordnungen vor. Ein echter Ortsausgang wurde fälschlich als Ortseingang gemeldet. Zwei echte Ortseingänge wurden als Ortsausgang eingeordnet. Precision fragt: Wie viele der fünf DE:310-Vorhersagen stimmen? Vier von fünf, also 80 Prozent. Recall fragt: Wie viele der sechs echten Ortseingänge wurden richtig zugeordnet? Vier von sechs, etwa 67 Prozent. Precision hat alle Vorhersagen dieser Klasse im Nenner, Recall alle tatsächlich vorhandenen Beispiele dieser Klasse. Ein hoher Recall alleine verhindert keine falschen Meldungen; eine hohe Precision alleine verhindert keine ausgelassenen richtigen Ziele. F1 verbindet beide durch das harmonische Mittel, 2×P×R/(P+R), mit P und R als Anteilen zwischen null und eins. Für DE:310 ergibt sich 8/11, etwa 73 Prozent. Das ist nicht das einfache arithmetische Mittel. Mit Trefferzahlen lautet dieselbe Formel 2×richtig/(2×richtig+falsch gemeldet+falsch als andere Klasse eingeordnet). Für DE:311 wechseln wir den Blick auf die andere Klasse: drei richtige, zwei falsch gemeldete und ein als DE:310 eingeordneter Ortsausgang. Precision 3/5=60 Prozent, Recall 3/4=75 Prozent und F1 6/9≈67 Prozent. Lassen Sie die Studierenden die Nenner fünf und vier an der Matrix zeigen. Im realen 136-Klassen-Modell zählt jede andere Klasse als Gegenklasse der betrachteten Klasse. Die drei Werte werden je Klasse berechnet. Werte von 0,80 in der Ergebnisfolie bedeuten 80 Prozent. Zum Einstieg sind die Kürzel TP, FP und FN nicht erforderlich.

Quellen:

- [model_evaluation.html#precision-recall-f-measure-metrics](https://scikit-learn.org/stable/modules/model_evaluation.html#precision-recall-f-measure-metrics)

## 23. Fortschritt messen – und alte Klassen bewahren

**36–38 Minuten · 2 Min.**

Das Skript evaluate.py vergleicht unveränderte Baseline und Kandidat standardmäßig auf val. Es schreibt einen lesbaren Bericht, JSON-Metriken und Konfusions-/Klassen-CSV. Für die alten 134 Klassen werden dieselben zurückgehaltenen Beispiele alter Klassen verwendet, ohne neue Ortstafel-Beispiele in diesen Teilvergleich einzumischen. Für jede alte Klasse werden Recall und F1 gegenüber dem Ausgangsmodell geprüft. Ein Rückgang über reine numerische Rundung hinaus führt zu REGRESSION und einem Fehlerstatus. Fehlt eine alte Klasse im Prüfbestand, lautet das Ergebnis UNVOLLSTAENDIG; eine fehlende Klasse wird nicht als bestanden gewertet. Der Gewinn bei zwei neuen Klassen kompensiert keine Verschlechterung bei Bestandsklassen. BESTANDEN und Exitcode 0 beziehen sich nur auf das Bestandsklassen-Gate. Die Precision-, Recall- und F1-Werte der neuen Klassen sind zusätzlich zu beurteilen; dies ist keine automatische Gesamtfreigabe. Gesamtgenauigkeit allein reicht nicht. Erst nach der Kandidatenauswahl wird derselbe Befehl mit --split test --output reports/abschluss ausgeführt. Aussagen gelten für den dokumentierten, endlichen Prüfbestand und sind keine Garantie für alle zukünftigen Straßenbilder. Konkretes Fine-Tuning-Ergebnis vom 20.10.2026: Der nach Validierung ausgewählte Kandidat aus Epoche 4 klassifizierte die 15 zurückgehaltenen manuell ausgeschnittenen Ortstafeln mit 14 richtigen Zuordnungen. DE:310: zwei von drei richtig, Precision 1,00, Recall 0,6667, F1 0,80. DE:311: zwölf von zwölf richtig, Precision/Recall/F1 jeweils 1,00. Die große Unsicherheit von nur drei Ortseingängen ausdrücklich erklären. Der vollständige Detektor-Klassifikator-Ablauf erkannte dagegen neun von 15 Ortstafeln korrekt (DE:310 zwei von drei, DE:311 sieben von zwölf). Die Cropzahlen auf dieser Folie messen daher ausschließlich den TSR-Klassifikator bei vorgegebener Box. Recall meint den Anteil der tatsächlich vorhandenen Zielklasse, den das Modell richtig findet. Precision meint den Anteil richtiger Treffer unter allen Vorhersagen dieser Klasse. F1 ist das harmonische Mittel aus beiden. Auf denselben 3.029 alten Bildausschnitten mit allen 134 Klassen sank die Anzahl korrekter Zuordnungen von 3.015 auf 3.010. Elf vormals richtige Beispiele wurden falsch und sechs Fehler wurden korrigiert. Bei 20 Klassen sank F1, bei elf der Recall. Trotz leicht gestiegenem Macro-F1 scheitert das Bestandsklassen-Gate: REGRESSION. Die alten Bilder stammen aus dem öffentlichen Panoramax-Bestand und können dem Ausgangsmodell schon bekannt sein. Der Vergleich misst rückblickend Veränderungen, keine unabhängige absolute Genauigkeit. Neue Ortstafeln: 15 Ansichten, 14 mögliche Standorte in 13 konservativen Gruppen, darunter projizierte Ansichten. Sie tragen nur eine begrenzte Schlussfolgerung. Der Kandidat erhält keine produktive Freigabe. Vollständige Belege: TRAININGSERGEBNISSE-2026-10-20.md, source/real-training-2026-10-20/tsr/results-summary.json und source/real-training-2026-10-20/tsr/reports/retrospective-old/regression-gate.json. Nach dem Abschlusstest folgte keine Parameterwahl anhand dieser Testdaten.

Quellen:

- [evaluate_ch_classifier.py](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/evaluate_ch_classifier.py)
- [TSR_TRAINING_ROUND_TRIP.md](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_TRAINING_ROUND_TRIP.md)
- [TSR_FR_END_SIGN_TRAINING.md](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_FR_END_SIGN_TRAINING.md)

## 24. Denselben Kandidaten auf allen Zielen prüfen

**38–39 Minuten · 1 Min.**

Das im Kurs erzeugte best.pt enthält ein eigenes sicheres state_dict plus Metadaten und ist kein direktes Ultralytics-Exportartefakt. Zuerst muss model_utils.load_candidate() das trainierte Modell rekonstruieren; ein direkter Befehl yolo export model=best.pt ist dafür ungeeignet. Die Core-ML-/LiteRT-Konvertierung dieses Kursformats wurde noch nicht getestet. Die vorhandenen Dockerfiles unter scripts/tsr/foreign-export trennen Core ML und LiteRT. Das dortige Export-CLI erlaubt aktuell FR, NL, BE und CH, aber kein DE. Der deutsche Ortstafel-Kandidat braucht deshalb einen angepassten und überprüften Exportweg, keine erfundene --country-DE-Option. Core-ML-Konvertierung kann auf Linux vorbereitet werden; die mlmodelc-Kompilierung und Einbindung bleibt beim Mac/Xcode-Schritt. Serverreferenz und Exporte auf dem gleichen orientierten Korpus vergleichen; zunächst Bildausschnitte isolieren, danach Vollbilder. Erst Modellsemantik, dann Laufzeit und vollständige Passage prüfen. Die vorhandene geschützte Geschwindigkeitsreferenz-Policy wird für diese Vorlesung nicht verändert. Ein erkanntes DE:311 setzt nicht blind 100 km/h. Veröffentlichung oder Deployment ist nicht Teil des Unterrichtsbeispiels.

Quellen:

- [Dockerfile.coreml](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/foreign-export/Dockerfile.coreml)
- [Dockerfile.litert](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/foreign-export/Dockerfile.litert)
- [export_classifier.py](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/foreign-export/export_classifier.py)
- [AGENTS.md](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/shared/speed-limit-reference/AGENTS.md)

## 25. Partnerübung: drei Fehler, drei nächste Schritte

**39–42 Minuten · 3 Min.**

Geben Sie 90 Sekunden zum Austausch und danach 90 Sekunden für die gemeinsame Lösung. A: Lokalisierung untersuchen; Vollbilder mit vollständigen Boxlabels, unabhängigen Detector-Recall messen. B: Klassifikator erweitern und Gewichte mit neuen/alten geprüften Bildausschnitte trainieren; Klasse sowie Indexmapping und Verwechslungen testen. C hat mehrere mögliche Ursachen: Split-Leakage, andere Aufnahmebedingungen oder Lokalisierungsfehler. Zuerst physische Schildgruppen, Größe/Blickwinkel und die beiden Stufen getrennt prüfen. Ein weiteres blindes Training ist keine Diagnose. Gute Antworten nennen einen überprüfbaren nächsten Schritt statt nur ein größeres Netz. Die Musterlösung steht im Dozentenleitfaden.

Quellen:

- [TSR_PROLIX_ALIGNMENT_2026-09-10.md](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_PROLIX_ALIGNMENT_2026-09-10.md)
- [group_splits_v2.py](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/group_splits_v2.py)

## 26. Ihr Ergebnis ist ein reproduzierbarer Modellversuch

**42–43 Minuten · 1 Min.**

Der Projektbericht muss erkennen lassen, welche Modellstufe verbessert wurde und wie groß der unabhängige Test ist. Datensatz und Modell erhalten Versionen und Hashes, dazu Paketlock beziehungsweise Image-Digest und den ausführbaren Versuch. Die längeren Schritte stehen im Praktikum. Als kurzer Lerncheck: Warum hilft eine Mappingänderung allein nicht? Warum kann ein Test mit Bildausschnitten fehlende Detektorboxen nicht beurteilen? Warum ist device 0 im Container nicht zwingend Host-GPU 0? Die Antworten zeigen, ob die Verbindung zwischen Daten, Modell und Laufzeit verstanden wurde.

Quellen:

- [TSR_TRAINING_ROUND_TRIP.md](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_TRAINING_ROUND_TRIP.md)

## 27. Fragen?

**43–45 Minuten · 2 Min.**

Zwei Minuten für Fragen und den Übergang zur Projektarbeit. Falls keine Fragen kommen: Eine Person nennt das erste Datenartefakt, eine zweite die erste GPU-Probe und eine dritte die wichtigste Testtrennung. Erwartet werden eine überprüfte Box-/Bildausschnitt-Liste mit Quellen und Gruppen, ein echter Forward-/Backward-/Save-Reload-Smoke und ein Test an bislang unbekannten physischen Schildern. Nicht voraussetzen, dass während 45 Minuten bereits ein produktiver Modellkandidat trainiert oder deployed wurde.

Quellen:

- [README.md](https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/README.md)
- [TSR_TRAINING_ROUND_TRIP.md](https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_TRAINING_ROUND_TRIP.md)
