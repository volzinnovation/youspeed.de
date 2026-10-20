export const meta = {
  "title": "Bildklassifikation mit KI",
  "subtitle": "Wie verbessere ich ein vorhandenes KI-Modell?",
  "author": "Prof. Dr. Raphael Volz · HSPF",
  "date": "Montag, 26. Oktober 2026",
  "evidenceDate": "19. Oktober 2026",
  "minutes": 45
};
export const slides = [
  {
    "title": "Bildklassifikation mit KI",
    "type": "cover",
    "minutes": 0.5,
    "notes": "Die Vorlesung erklärt, wie wir mit menschlich geprüften Panoramax-Boxen und Bildausschnitte eine fehlende Modellfähigkeit ergänzen. Im Mittelpunkt stehen Ortseingang und Ortsausgang. Die gesamte Lehrsequenz dauert 45 Minuten einschließlich einer kurzen Partnerübung und Fragen. Der vollständige Trainingslauf findet danach als Projektarbeit statt. Der geprüfte technische Quellenstand ist der 19. Oktober; der Vortrag ist am Montag, 26. Oktober 2026.",
    "sources": [
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_PROLIX_ALIGNMENT_2026-09-10.md"
    ],
    "sourceSlide": 1,
    "sourcePptxSlide": 1
  },
  {
    "title": "Am Ende können Sie einen Modellversuch aufsetzen",
    "type": "steps",
    "minutes": 1,
    "items": [
      [
        "Verstehen",
        "Bekannte Bildbeispiele → Gewichte lernen → Klasse vorhersagen"
      ],
      [
        "Vorbereiten",
        "Geprüfte Bildausschnitte (Crops) fest aufteilen: Training, Validierung, Test"
      ],
      [
        "Ausführen",
        "Die bereitgestellten Skripte starten und Berichte lesen"
      ],
      [
        "Bewerten",
        "Ortstafeln erkennen; bisherige Klassen auf Rückschritte prüfen"
      ]
    ],
    "notes": "Der Einstieg ist für Studierende im 3. Semester ohne Vorwissen zu Machine Learning gedacht. Begriffe werden anhand von Bildbeispielen erklärt. Der Dozent stellt eine vorbereitete Python-/GPU-Umgebung, den geprüften 134-Klassen-Checkpoint und einen kuratierten Datenbestand bereit. Die Studierenden müssen keine eigene Netzarchitektur implementieren. Im Praktikum führen sie drei konkrete Skripte aus: Daten vorbereiten, trainieren und bewerten. Die feste Anleitung steht in praktikum/README.md. Vier öffentliche Panoramax-Datenpakete liegen auf Hugging Face unter loffenauer/ws26_hspf_imo. Sie enthalten ungeprüfte Bildausschnitte und Boxvorschläge. Der vollständige kuratierte Bestand der 134 alten Klassen und der Modellcheckpoint müssen weiterhin vom Dozenten bereitgestellt werden. Ein Bildausschnitt (englisch Crop) ist der aus einer Box ausgeschnittene Teil eines Fotos. Ab hier verwenden die Folien den deutschen Begriff.",
    "sources": [
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_TRAINING_ROUND_TRIP.md"
    ],
    "sourceSlide": 2,
    "sourcePptxSlide": 2
  },
  {
    "title": "Zwei Situationen: Box fehlt oder Klasse falsch",
    "type": "failureComparison",
    "minutes": 1.5,
    "leftImage": "assets/panoramax-dobel-965b93dc-viewer.png",
    "rightImage": "../assets/city-entry.jpg",
    "leftTitle": "1  Box fehlt an der Ortstafel",
    "rightTitle": "2  Box erkannt, Klasse falsch",
    "leftBody": "Dobel: keine Box → kein Bildausschnitt\nDetektion mit Vollbildern und Boxen verbessern",
    "rightBody": "Bernbach: Box vorhanden → bad\nMit geprüften Bildausschnitten nachtrainieren",
    "takeaway": "Zuerst prüfen: Liegt der Fehler bei der Lokalisierung oder der Klassifikation?",
    "notes": "Situation 1: Im verlinkten Panoramax-Bild aus Dobel ist die Ortstafel sichtbar, für sie fehlt die gespeicherte Box. Das Gefahrzeichen rechts hat dagegen eine SGBlur-Box und die Klassifikation DE:101. Die abgerufene API enthält genau diese eine Annotation. Die Folie zeigt den gespeicherten Zustand und keinen neu ausgeführten Modelltest. Der orange Rahmen um das Gefahrzeichen ist eine vorhandene Panoramax-Annotation. Die gelbe Ortstafel darf nicht mit diesem erkannten Objekt verwechselt werden. Ohne passende Schildbox entsteht im üblichen Ablauf kein Bildausschnitt für die zweite Stufe. Situation 2: Die Bernbach-Tafel wurde lokalisiert, aber vom alten Klassifikator als bad ausgegeben. Für beide Fälle unterscheiden sich die zusätzlichen Trainingsdaten: Vollbilder plus Boxen für die Lokalisierung, geprüfte Bildausschnitte plus Zeichenklassen für die Klassifikation. Eine Annotation in Panoramax verbessert zunächst den Datenbestand. Gewichte ändern sich erst beim erneuten Lernen und werden danach als neuer Modellstand bereitgestellt. Beide Fotos: admin / Panoramax, CC BY-SA 4.0.",
    "sources": [
      "https://panoramax.youspeed.de/?focus=pic&pic=965b93dc-e04d-45aa-a4bf-a8bc20c9a106&seq=1cde254e-daab-4de3-b256-813984ea9620",
      "https://panoramax.youspeed.de/api/collections/1cde254e-daab-4de3-b256-813984ea9620/items/965b93dc-e04d-45aa-a4bf-a8bc20c9a106",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_PROLIX_ALIGNMENT_2026-09-10.md#bernbach-zeichen-310-experiment"
    ],
    "sourceSlide": 3,
    "sourcePptxSlide": 3
  },
  {
    "title": "Die Box stimmt – die neue Klasse fehlt",
    "type": "failure",
    "minutes": 1,
    "image": "../assets/city-entry.jpg",
    "body": [
      "Bernbach: Ortstafel lokalisiert",
      "Historische Klassifikation: bad",
      "DE-Modell: 134 Klassen\nDE:310 und DE:311 fehlen"
    ],
    "takeaway": "Annotation in Panoramax verändert das Modell nicht, erst bei erneutem Lernen.",
    "notes": "Das reale Bild stammt von admin / Panoramax, CC BY-SA 4.0. Die historische Box im 2376 × 4224 Pixel großen Bild lautet [1827,2244,2039,2392], also 212 × 148 Pixel. Das Experiment lief mit Core ML auf macOS-CPU und mit LiteRT im Android-Emulator. Es ist kein aktueller Benchmark physischer Telefone. Die spätere gespeicherte menschliche DE:310-Annotation ist vom früheren generischen Detektionsstand zu unterscheiden. Der Befund zeigt eine Klassifikationslücke: Der gepinnte Klassifikator hat die beiden Ortstafelklassen nicht. Ein Piktogramm oder Alias in der Referenztabelle erzeugt keinen zusätzlichen Netzausgang. Die angegebene Quelle classified_de_road_signs enthält die beschrifteten Trainingsbilder. Die Gewichte des verwendeten Klassifikators liegen im getrennten Modell-Repository classify_de_road_signs. Beide Links sind sichtbar. Der vorhandene Datensatz dokumentiert den Altbestand, der für DE:310/311 ergänzt werden soll. Die neue Quellenfolie nach YOLO erklärt diese Unterscheidung.",
    "sources": [
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_PROLIX_ALIGNMENT_2026-09-10.md#bernbach-zeichen-310-experiment",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/lectures/assets/city-entry-source.json",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/shared/tsr/prolix-de-class-catalog-v1.json",
      "https://huggingface.co/datasets/Panoramax/classified_de_road_signs",
      "https://huggingface.co/Panoramax/classify_de_road_signs"
    ],
    "sourceSlide": 4,
    "links": [
      [
        "Trainingsbilder: Panoramax/classified_de_road_signs",
        "https://huggingface.co/datasets/Panoramax/classified_de_road_signs"
      ],
      [
        "Gewichte: Panoramax/classify_de_road_signs",
        "https://huggingface.co/Panoramax/classify_de_road_signs"
      ]
    ],
    "evidenceDate": "20. Oktober 2026",
    "sourcePptxSlide": 4
  },
  {
    "title": "Ein neuronales Netz lernt Gewichte aus Beispielen",
    "type": "network",
    "minutes": 2.5,
    "body": [
      "Eingabe: Zahlenwerte der Bildpixel",
      "Gewichte + Aktivierungen erzeugen Klassenscores",
      "Loss misst den Unterschied (Fehler) zur bekannten Lösung des Beispiels",
      "Backpropagation + Optimizer verändern die Gewichte"
    ],
    "takeaway": "Training verändert Gewichte. Inferenz verwendet die gelernten Gewichte.",
    "notes": "Ein Pixel ist für das Netz zunächst eine Zahl. Ein Neuron kombiniert Eingaben als gewichtete Summe mit Bias; eine nichtlineare Aktivierung erlaubt komplexere Abbildungen als eine einzige lineare Rechnung. Viele verknüpfte Schichten liefern am Ende einen Score pro Klasse. Die Ausgänge müssen dem bekannten Klasseninventar entsprechen. Beim überwachten Lernen vergleichen wir die Ausgabe mit dem menschlichen Label. Cross-Entropy bestraft eine niedrige Wahrscheinlichkeit der richtigen Klasse. Backpropagation berechnet Gradienten, ein Optimizer aktualisiert Gewichte. Bei der Inferenz werden weder Labels benötigt noch Gewichte aktualisiert. Ein Softmax-Wert ist keine Garantie für die Richtigkeit auf einer unbekannten Situation. Die Grafik ist ein didaktisches Schema, keine Darstellung der konkreten YOLO-Architektur. Überwachtes Lernen bedeutet: Zu jedem Trainingsbild ist die richtige Klasse bekannt. Die Loss-Funktion vergleicht die Vorhersage mit dieser bekannten Lösung. Erst anschließend verändert der Optimizer die Gewichte.",
    "sources": [
      "https://docs.pytorch.org/tutorials/beginner/basics/buildmodel_tutorial.html",
      "https://docs.pytorch.org/tutorials/beginner/basics/optimization_tutorial.html"
    ],
    "subtitle": "Überwachtes Lernen",
    "sourceSlide": 5,
    "sourcePptxSlide": 5
  },
  {
    "title": "CNNs lernen lokale Merkmale im Bild",
    "type": "cnn",
    "minutes": 2.5,
    "body": [
      "Faltung: derselbe kleine Filter an vielen Bildpositionen",
      "Backbone: lokale Muster zu Bildmerkmalen verbinden",
      "Attention: wichtige Merkmale unterschiedlich gewichten",
      "Classification Head: Merkmale → 134 Klassenwerte"
    ],
    "takeaway": "Vorhandene Merkmale weiterverwenden; den Classification Head um zwei Klassen erweitern.",
    "notes": "CNN bedeutet Convolutional Neural Network. Kleine Filter betrachten lokale Nachbarschaften; ihre Gewichte werden räumlich geteilt. Das reduziert die Anzahl unabhängiger Parameter gegenüber einer voll verbundenen Schicht über alle Pixel. Mehrere Faltungen, Aktivierungen und räumliche Verdichtung erzeugen Merkmalskarten mit zunehmendem Kontext. Beim Klassifikator verdichtet ein Kopf diese Merkmale zu Klassenwerten. Für unsere Ortstafeln sind Farbe und Rechteckform allein nicht ausreichend: Wegweiser oder Werbung sind ähnliche Gegenbeispiele. Der rote Diagonalstrich des Ausgangsschilds und die vollständige Tafel müssen im Bildausschnitt erhalten bleiben. Beim Transfer Learning nutzen wir gelernte Merkmale des Ausgangsnetzes und passen Kopf beziehungsweise Teile des Backbones mit neuen geprüften Beispielen an. Mehr Parameter oder eine größere Datei garantieren keinen besseren unabhängigen Test. Im konkreten DE-Modell folgen auf Faltungen und C3k2-Merkmalsblöcke eine C2PSA-Attention-Stufe und der Classification Head. Dieser enthält eine 1×1-Faltung, Global Average Pooling, Dropout und eine lineare Schicht mit 1280 Eingangsmerkmalen und 134 Ausgaben. Das ist kein LeNet-Modell; historische CNN-Quellen dienen nur der Einordnung. Forschungsbezug: Jocher et al., Ultralytics YOLO26: Unified Real-Time End-to-End Vision Models, arXiv:2606.03748v1, 2. Juni 2026, Abschnitt 3.4 zur Klassifikation. Für den konkreten Checkpoint wurde zusätzlich die gespeicherte YAML-Konfiguration und der tatsächlich kompilierte Core-ML-Rechengraph geprüft. Die 512×7×7 Backbone-Ausgabe wird im Head durch eine 1×1-Faltung zu 1280 Kanälen und durch Global Average Pooling zu 1280 Werten. Die lineare Schicht hat 134×1280 Gewichte plus 134 Biaswerte. Die zwei zusätzlichen Klassen benötigen 2562 zusätzliche Parameter. Aussagen zu NMS-freien Detektoren aus dem YOLO26-Paper gelten nicht für unseren YOLO11-Detektor und sind keine Eigenschaft dieses Klassifikationskopfs.",
    "sources": [
      "https://docs.pytorch.org/tutorials/beginner/blitz/cifar10_tutorial.html",
      "https://docs.ultralytics.com/tasks/classify/",
      "https://arxiv.org/abs/2606.03748v1",
      "https://github.com/ultralytics/ultralytics/blob/v8.4.56/ultralytics/cfg/models/26/yolo26-cls.yaml",
      "https://github.com/ultralytics/ultralytics/blob/v8.4.56/ultralytics/nn/modules/head.py"
    ],
    "subtitle": "Im Projekt: YOLO26l-cls",
    "links": [
      [
        "Architekturquelle: Jocher et al. (2026), YOLO26",
        "https://arxiv.org/abs/2606.03748v1"
      ]
    ],
    "sourceSlide": 6,
    "sourcePptxSlide": 6
  },
  {
    "title": "Zwei Lernaufgaben hinter einer Erkennung",
    "type": "pipeline",
    "minutes": 1.5,
    "stages": [
      "Straßenbild",
      "Detektor\nWo ist ein Schild?",
      "Bildausschnitt\nAus der Box",
      "DE-Klassifikator\nWelches Zeichen?"
    ],
    "body": [
      "Box fehlt → Detektor und Vollbildlabels prüfen",
      "Box stimmt, Klasse falsch → Bildausschnitt, Klassen und Klassifikator prüfen"
    ],
    "notes": "Die zwei Lernprobleme werden getrennt bewertet. Der Detektor kann weiterhin eine generische Klasse sign verwenden; die nationale Bedeutung muss nicht als zusätzliche Detektorklasse angelegt werden. Für seine Verbesserung benötigen wir ganze Bilder mit vollständigen Boxannotationen. Der Klassifikator erhält den ausgeschnittenen Bereich, bei der mobilen Inferenz einschließlich der dokumentierten Randzugabe. Gute Cropmetriken sagen noch nichts über übersehene Zeichen aus. Eine spätere Ereignis- beziehungsweise Passageentscheidung ist nochmals ein eigener Laufzeitschritt; sie wird durch dieses Training nicht neu definiert.",
    "sources": [
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/shared/tsr/README.md",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/iphone/SpeedConsumerApp/TrafficSignRuntime.swift",
      "https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/prolix_pipeline/worker.py"
    ],
    "sourceSlide": 7,
    "sourcePptxSlide": 7
  },
  {
    "title": "YOLO: eine Modellfamilie für verschiedene Aufgaben",
    "type": "yolo",
    "minutes": 1.5,
    "headers": [
      "Variante",
      "Eingabe",
      "Ausgabe"
    ],
    "rows": [
      [
        "Detektion",
        "Ganzes Straßenbild",
        "Boxen + Objektklassen + Scores"
      ],
      [
        "Klassifikation (−cls)",
        "Ein Bildausschnitt",
        "Ein Score je Zeichenklasse"
      ]
    ],
    "stages": [
      "Backbone\nKanten und Formen\nals Merkmale gewinnen",
      "Neck\nFeine und grobe\nMerkmale verbinden",
      "Head (Detection Head)\nBoxen + Klassen\nvorhersagen"
    ],
    "body": [
      "YOLO = You Only Look Once",
      "Detektor: Backbone → Neck → Detection Head → Boxen",
      "Klassifikator: Backbone → Classification Head → Klasse (ohne Neck)"
    ],
    "notes": "YOLO bezeichnet eine Modellfamilie und nicht ein einzelnes Verkehrszeichenmodell. Backbone bedeutet Rückgrat: Dieser Teil gewinnt Bildmerkmale wie Kanten und Formen. Der Neck verbindet fein und grob aufgelöste Merkmalskarten desselben Bilds, also Details und Überblick. Head bedeutet Kopf: Aus den Merkmalen berechnet der Detection Head Boxkoordinaten und Klassenscores. Beim hier verwendeten Klassifikator entfällt der Detektionsneck; der Classification Head liefert einen Score je Zeichenklasse. Die Bezeichnungen erklären die Aufgabe der Netzteile, nicht drei unabhängig trainierte Modelle. Ein Detektionsmodell lokalisiert mehrere Objekte. In der hier betrachteten YOLO11-Pipeline werden schwächer bewertete überlappende Vorschläge durch Non-Maximum Suppression unterdrückt. Ein Modell mit cls-Kopf klassifiziert dagegen einen gesamten Ausschnitt. Ein 224-Pixel-Cropklassifikator kann allein keine Tafel im vollständigen Kamerabild lokalisieren. n, s, m und l bezeichnen Architekturgrößen; cls bezeichnet die Aufgabe. Das deutsche Modell ist ein angepasstes YOLO26l-cls, während die mobile Lokalisierung YOLO11n nutzt. Es ist daher falsch, alle Projektmodelle pauschal YOLO11 zu nennen. Für unsere Übung benötigen wir nur Boxen und Klassen. Forschungsursprung: Redmon, Divvala, Girshick und Farhadi, You Only Look Once: Unified, Real-Time Object Detection, CVPR 2016. Das ist die historische Grundidee der gemeinsamen Box- und Klassenvorhersage, nicht die konkrete Architektur unseres neueren Checkpoints. Der verwendete YOLO11n-Detektor hat Conv/C3k2-Merkmalsblöcke, SPPF und C2PSA, führt Merkmale in einem FPN/PAN-Neck auf drei Skalen zusammen und verwendet einen separaten Detection Head mit DFL und NMS. Ultralytics nennt für YOLO11 ausdrücklich kein formales Forschungspaper; hierfür werden die offizielle Softwaredokumentation und die passende Konfiguration zitiert.",
    "sources": [
      "https://docs.ultralytics.com/tasks/detect/",
      "https://docs.ultralytics.com/tasks/classify/",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/iphone/SpeedConsumerApp/TSRModelPacks/DE.panoramax-bootstrap.tsrmodelpack/classify_de_road_signs.mlmodelc/metadata.json",
      "https://arxiv.org/abs/1506.02640v5",
      "https://docs.ultralytics.com/models/yolo11/",
      "https://github.com/ultralytics/ultralytics/blob/v8.4.56/ultralytics/cfg/models/11/yolo11.yaml"
    ],
    "links": [
      [
        "Forschungsursprung: Redmon et al. (CVPR 2016), YOLO",
        "https://arxiv.org/abs/1506.02640v5"
      ]
    ],
    "sourceSlide": 8,
    "sourcePptxSlide": 8
  },
  {
    "title": "Trainingsbilder und Modellgewichte",
    "type": "dataAndModel",
    "minutes": 1,
    "evidenceDate": "20. Oktober 2026",
    "columns": [
      {
        "title": "Datensatz: Bilder + Klassenlabels",
        "label": "Panoramax/classified_de_road_signs",
        "url": "https://huggingface.co/datasets/Panoramax/classified_de_road_signs",
        "body": [
          "Bildausschnitte von Verkehrszeichen",
          "Bekannte Klasse je Beispiel",
          "train.zip zum Lernen\nval.zip für die Modellauswahl"
        ]
      },
      {
        "title": "Modell: gelernte Gewichte",
        "label": "Panoramax/classify_de_road_signs",
        "url": "https://huggingface.co/Panoramax/classify_de_road_signs",
        "body": [
          "YOLO26l-cls mit 134 Klassen",
          "Sagt die Klasse eines Ausschnitts voraus",
          "Fine-Tuning ergänzt DE:310 / DE:311"
        ]
      }
    ],
    "body": "Für unseren Versuch bleiben alte Beispiele erhalten. Neue Ortstafeln kommen hinzu.",
    "takeaway": "Vor der Kursaufteilung Dopplungen prüfen und zusammengehörende Bilder gruppieren.",
    "notes": "Der Datensatz enthält beschriftete Bildausschnitte, das Modell enthält gelernte Gewichte. Die Dataset Card beschreibt über 20.000 Zeichenbilder in über 130 Klassen, darunter bad und other. Die Bilder stammen überwiegend aus deutschen Panoramax-Aufnahmen, ergänzt um ähnliche Zeichen aus anderen europäischen Ländern mit Länderpräfix im Dateinamen. Lizenz laut Dataset Card: CC BY-SA 4.0. Für den Kurs werden Herkunft und Urheber beibehalten. Der verwendete Datenstand ist b4856947ed7cb6312587258acc90e8cf88a4aa13. Die geprüften Archive enthalten 13.287 beziehungsweise 6.944 Bilddateien, davon 522 exakt gleiche Bilder in beiden Archiven. Nach Deduplizierung verbleiben 19.709 Bilder. Diese ursprüngliche Aufteilung ist deshalb kein unabhängiger Abschlusstest. Gruppieren Sie Duplikate und zusammengehörende Bildquellen vor der neuen Aufteilung. Der Ausgangscheckpoint kann die alten Bilder dennoch bereits kennen. Seine Prüfung bleibt ein rückblickender Regressionstest. Die beiden neuen Ortstafelklassen und neue unabhängige Prüfgruppen kommen aus unserer geprüften Sammlung hinzu. Es wird ein vorhandener Datensatz erweitert und ein vorhandenes Modell weitergelernt. Nicht jedes Datenrepository enthält Gewichte. Quellenprüfung: source/hf-model-card-review-2026-10-20.json. Ergänzender Kartenbeleg: source/dataset-card-review-2026-10-20.json.",
    "sources": [
      "https://huggingface.co/datasets/Panoramax/classified_de_road_signs/blob/b4856947ed7cb6312587258acc90e8cf88a4aa13/README.md",
      "https://huggingface.co/Panoramax/classify_de_road_signs/blob/5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790/README.md"
    ],
    "sourcePptxSlide": 9
  },
  {
    "title": "Modelle: Gewichte, Dateien und App-Speicher",
    "type": "modelTable",
    "minutes": 1,
    "headers": [
      "Modell",
      "Parameter",
      "Datei: MB\n.pt / iOS / Android",
      "App-Puffer¹\nAndroid"
    ],
    "rows": [
      [
        "YOLO11n · Detektor\n3 Klassen · 1024²",
        "2.590.425",
        "6 / 6 / 6",
        "22 MB"
      ],
      [
        "YOLO26l-cls · DE\n134 Klassen · 224²",
        "13.006.278",
        "26 / 26 / 26",
        "1 MB"
      ]
    ],
    "body": [
      "Detektor: SGBlur · 1024 × 1024 mobil · 3 Objektklassen",
      "Klassifikator: Panoramax / Prolix · 224 × 224 · 134 Zeichenklassen"
    ],
    "takeaway": "Volle MB gerundet. Gesamtapp: unterschiedliche Last und Messgrößen; kein isolierter Modell-RAM.",
    "notes": "Die Parameter wurden tatsächlich in den SHA-256-geprüften Originalcheckpoints auf der CPU gezählt: sum(p.numel() for p in model.parameters()). Detektor 2.590.425, deutscher Klassifikator 13.006.278 Parameter einschließlich Bias und eingefrorener Parameter. Der Detektor enthält 16 feste DFL-Projektionsparameter. FP16-Parameterbytes sind 5.180.850 beziehungsweise 26.012.556; Dateiverpackung und Puffer zählen zusätzlich. Die Dateigrößen werden auf volle dezimale MB gerundet. Detektor: Original 5.979.923 Byte, aktuelles Core ML 5.504.286, aktuelles LiteRT 5.524.669 → jeweils 6 MB. Klassifikator: 26.282.865, 26.175.294, 26.080.976 → jeweils 26 MB. Die sichtbaren Android-App-Puffer sind aus dem Quellcode vom 20. Oktober berechnete Kapazitäten: 22.175.744 Byte für den Detektor bei 1024² und 21.504 Vorschlägen und 1.004.056 Byte für den Klassifikator. Diese Werte sind keine Messung des vollständigen RAM-Bedarfs; Gewichte, Runtime-Arenen, Zwischenaktivierungen, GPU-Kopien, Kamera und Karte kommen hinzu. Eine getrennte RAM-Messung je Modell liegt nicht vor. Als App-Gesamtbeispiele stehen ein neuer Android-PSS-Snapshot von 645,67 MB am 19.10.2026 und ein historischer iPhone-physical-footprint-Sample von 231,93 MB am 01.10.2026 zur Verfügung. Unterschiedliche Last, Versionen und Messgrößen: daraus keinen Plattformvergleich ableiten. Rohbelege und Berechnung stehen in source/model-weights-evidence.json und source/model-memory-evidence.json. Die Links öffnen die gepinnten tatsächlichen Modellquellen. Die sichtbare HF-Quelle benennt Panoramax/classify_de_road_signs ausdrücklich. Dieser exakt gepinnte Checkpoint ist die Ausgangsbasis des Fine-Tuning-Beispiels auf Folie 22. Die Modellkarte nennt das Training mit Panoramax/classified_de_road_signs. Ihre 98,6 Prozent Accuracy sind eine selbst berichtete Herausgeberangabe und nicht unser Testergebnis. Lizenzangaben getrennt lesen: Modellkarte Etalab 2.0, Bilddatensatz CC BY-SA 4.0 und Ultralytics-Software AGPL-3.0 beziehungsweise Enterprise. Prüfbeleg: source/hf-model-card-review-2026-10-20.json.",
    "sources": [
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/shared/tsr/training-sources-v1.json",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/shared/tsr/end-sign-review-2026-09-24.md",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/provenance/android-export-report.json",
      "https://huggingface.co/Panoramax/classify_de_road_signs"
    ],
    "links": [
      [
        "SGBlur: Modellquelle",
        "https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/models/yolo11n_panoramax.pt"
      ],
      [
        "HF: Panoramax/classify_de_road_signs",
        "https://huggingface.co/Panoramax/classify_de_road_signs/tree/5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790"
      ]
    ],
    "memoryNotes": [
      "¹ Berechnete Puffer; Gewichte, Aktivierungen und GPU-Speicher kommen hinzu.",
      "Historische Gesamtapp-Beispiele: Android 646 MB PSS · iPhone 232 MB phys. Footprint."
    ],
    "evidenceDate": "20. Oktober 2026",
    "sourceSlide": 9,
    "sourcePptxSlide": 10
  },
  {
    "title": "YOLO26s im Dashcam-Vergleich",
    "type": "detectorCandidate",
    "minutes": 1,
    "intro": "3 Fahrten · 31:47 Minuten · 65 feste Prüfbilder · 1024 × 1024",
    "headers": [
      "Detektor",
      "Gefundene Boxen¹",
      "Fehlvorschläge¹",
      "Mac-CPU²"
    ],
    "rows": [
      [
        "YOLO11n · aktuell",
        "17 / 48",
        "1",
        "68 ms"
      ],
      [
        "YOLO26s · Kandidat",
        "14 / 48",
        "0",
        "128 ms"
      ]
    ],
    "body": [
      "¹ Assistentenannotation: erkennbare Schildfronten ab 20 px · keine App-Fehlalarmrate",
      "² Median über 3.814 Videobilder · One-to-many-Zweig · keine Telefonmessung"
    ],
    "takeaway": "Die Videoprüfung rechtfertigt noch keinen Modellwechsel in den Apps.",
    "link": [
      "SGBlur: gepinnter YOLO26s-Checkpoint",
      "https://github.com/cquest/sgblur/blob/fa83262033b6addb9c8085caa5a0fd82d212f16a/models/yolo26s_face_plate_sign.pt"
    ],
    "notes": "Der Commit vom 6. Oktober 2026 ergänzt die Datei yolo26s_face_plate_sign.pt, schaltet den Dienst aber nicht automatisch um. Beide Checkpoints speichern imgsz=2048 als Trainingsgröße; die Inferenzgröße bleibt wählbar. Die Apps verwenden aktuell 1024×1024. Der frühere Vergleich mit 13 Lern-/Validierungsbildern und Teilannotation bleibt separat dokumentiert: 10/16 bekannte Boxen für YOLO11n und 13/16 für YOLO26s. Die Folie zeigt jetzt den zusätzlichen Videoversuch. Drei vollständige archivierte Fahrten wurden vor der Inferenz ausgewählt und gegen den privaten HF-Backupstand bd12056313e00acc790d25ebe5486aac11f4cf79 gehasht: iPhone bei Tag, Android in der Morgendämmerung und Android bei Sonnenuntergang. Zusammen 31 Minuten 47 Sekunden, bei zwei Einzelbildern pro Sekunde 3814 Eingaben. Die Android-Videos haben variable Bildraten. Einzelne OpenCV-Seeks weichen bis zu 0,79 Sekunden vom angeforderten Zeitpunkt ab; einmal sind zwei Nachbarbilder um 0,10 Sekunden zeitlich vertauscht. Modellvergleich und Annotation verwenden dennoch exakt dieselben gespeicherten Pixel. Das ist kein lückenloser Trackingtest. Die gleichen aufrechten Fenster werden proportional auf 1024 Pixel Höhe skaliert und rechts auf 1024 Spalten begrenzt. Native Interpolation ist damit angenähert, nicht bitgenau nachgewiesen. Alle 30 Sekunden wurde ab Sekunde null ein festes Prüfbild gewählt. 65 Bilder enthalten nach der quellbildbasierten Prüfung 48 Schildinstanzen; wiederholte Sichtungen desselben Schilds zählen mehrfach. Die Annotation wurde ohne Kenntnis der Modellvorschläge eingefroren und stammt von einem Assistenten, nicht von einer unabhängigen menschlichen Prüfstelle. Gezählt werden erkennbare Schildfronten mit mindestens 20 Pixeln kürzerer Boxkante, einschließlich Wegweisern, Park-, Haltestellen- und Zusatztafeln. Rückseiten, angeschnittene und unklare oder kleine Schilder werden markiert ausgeschlossen. Confidence ist 0,25, NMS-IoU 0,7, Zuordnungs-IoU 0,5, Eins-zu-eins-Zuordnung. YOLO11n findet 17 von 48 Instanzen mit 1 bewerteten Fehlvorschlägen; YOLO26s findet 14 mit 0. Der Kandidat gewinnt 1 und verliert 4 Treffer gegenüber dem alten Modell. Das sind Detektorwerte auf den fest beschrifteten Bildern. Aus den Rohvorschlägen aller 3814 Bilder lässt sich keine Genauigkeit ableiten. Eine verfehlte Momentaufnahme bedeutet auch keinen vollständig verpassten Schildkontakt: Der Kandidat erkennt die bei Sekunde 510 verfehlte Nässe-Zusatztafel bereits bei Sekunde 506 und die bei Sekunde 150 verfehlte Kurventafel bei Sekunde 150,5. Diese nachträglich ausgewählten Nachbarbilder gehören nicht zu den festen Kennzahlen. Der Median der Python-predict-Wandzeit beträgt 68.0 beziehungsweise 128.5 ms auf der Mac-CPU mit vier Threads, einschließlich predict-Vor-/Nachverarbeitung, aber ohne Videodekodierung und Fensterbildung. Das ist keine iPhone-/Android-Laufzeit- oder Thermikmessung. Der ursprüngliche End-to-end-Zweig des YOLO26s wurde danach separat auf denselben 65 Prüfbildern geprüft: 13/48 Treffer und 0 bewertete Fehlvorschläge. Dieser Zusatzlauf hat keine vergleichbare 3814-Bilder-Laufzeitmessung. Der Standardzweig liefert [1,300,6] mit xyxy, Score und Klassenindex und benötigt auf beiden Plattformen eine gesonderte Integration. Der kompatible Kandidatenexport wählt ausdrücklich end2end=false; er liefert vor NMS [1,7,21504], mit Core-ML-NMS für Vision und nativer Android-NMS. Die Python-NMS mit IoU 0,7 und bis zu 300 Vorschlägen ist nicht der vollständige Android-Ablauf mit IoU 0,45 und maximal zwölf Vorschlägen. Die zehn aktuellen Länderpaket-Manifeste bleiben bytegleich und die Apps behalten YOLO11n. Es gibt noch keine Freigabe für einen Wechsel, keine Messung der Folgeklassifikation/OCR und keine Änderung der gemeinsamen Speed-Reference-Policy. Der deutsche 134-Klassen-Klassifikator und die historischen Trainingsresultate bleiben unverändert. Quellen und Grenzen: docs/SGBLUR_YOLO26_DASHCAM_REPLAY_2026-10-20.md sowie docs/sgblur-yolo26-dashcam-2026-10-20.evidence.json und die eingefrorenen Labels. Die Daten sind kein unabhängiger Test mit nachgewiesen unbekannten Trainingsorten.",
    "sources": [
      "https://github.com/cquest/sgblur/commit/fa83262033b6addb9c8085caa5a0fd82d212f16a",
      "https://huggingface.co/datasets/loffenauer/youspeed.de/tree/bd12056313e00acc790d25ebe5486aac11f4cf79"
    ],
    "evidenceDate": "20. Oktober 2026"
  },
  {
    "title": "SGBlur erkennt Boxen; Prolix ergänzt die Bedeutung",
    "type": "sgblur",
    "minutes": 1,
    "origins": [
      {
        "name": "SGBlur",
        "meaning": "„Speedy Gonzales“\nBlurring Algorithm · Panoramax",
        "credit": "Ursprüngliches Repository: cquest/sgblur",
        "label": "Originalprojekt und Namensherkunft",
        "url": "https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/README.md"
      },
      {
        "name": "Prolix",
        "meaning": "Panoramax-Werkzeug für\nObjekterkennung und Klassifikation",
        "credit": "Autor: Adrien Pavie · Panoramax-Projekt",
        "label": "Originalprojekt: Panoramax / Prolix",
        "url": "https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/README.md"
      }
    ],
    "stages": [
      "SGBlur-Detektor\nSchild · Kennzeichen · Gesicht",
      "CPU-Bildbearbeitung\nSensible Boxen verwischen",
      "Prolix / Adapter\nBildausschnitte klassifizieren"
    ],
    "body": [
      "Die Schildbox bleibt als Objektannotation erhalten",
      "Aktueller Serveradapter verwendet vorhandene SGBlur-Boxen",
      "Änderungen am gemeinsamen Detektor: Gesicht und Kennzeichen mitprüfen"
    ],
    "notes": "Namens- und Projektherkunft: SGBlur wird im originalen README als Panoramax „Speedy Gonzales“ Blurring Algorithm bezeichnet. Das ursprüngliche Repository liegt unter cquest/sgblur; das Projekt wurde nach gitlab.com/panoramax/server/sgblur verlegt. Prolix ist ein Kommandozeilenwerkzeug des Panoramax-Projekts zur Objekterkennung und Klassifikation. Das pyproject.toml nennt Adrien Pavie als Autor. Eine weitergehende Etymologie des Namens Prolix wird in den geprüften Primärquellen nicht erklärt und deshalb hier nicht behauptet. Beide Originalprojekte sind direkt auf der Folie verlinkt. Der gepinnte SGBlur-Quellstand verwendet YOLO11 für die drei Klassen sign, plate und face. Die Detektions-API profitiert von CUDA. Der separate Blur-Dienst bearbeitet die erkannten sensiblen JPEG-Bereiche auf der CPU; Schildbereiche sind davon ausgenommen. Normale JPEG-MCU-Pfade erhalten andere Bildteile, doch es gibt Sonderpfade mit Rekodierung. Der derzeitige landesspezifische Prolix-kompatible Serveradapter nimmt bestehende Annotationen, schneidet aus der bereits verwischten Bildableitung aus und klassifiziert. Ein größerer Detektor im Modellregister belegt nicht, dass dieser Worker ihn ausführt. Wenn wir den gemeinsam verwendeten SGBlur-Detektor nachtrainieren, dürfen seine Gesicht-/Kennzeichenfähigkeiten nicht unbeachtet verloren gehen.",
    "sources": [
      "https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/README.md",
      "https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/src/detect/detect.py",
      "https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/src/blur/blur.py",
      "https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/README.md",
      "https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/pyproject.toml",
      "https://gitlab.com/panoramax/server/sgblur",
      "https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/prolix_pipeline/worker.py",
      "https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/docs/prolix-ki-server-runbook.md"
    ],
    "sourceSlide": 10,
    "sourcePptxSlide": 11
  },
  {
    "title": "Ein Klassifikator-Checkpoint, drei Laufzeitformate",
    "type": "platforms",
    "minutes": 1.5,
    "stages": [
      "Eingefrorener DE-Checkpoint\nGewichte + Labelreihenfolge",
      "Linux / Server\nPyTorch .pt",
      "Android\nLiteRT .tflite",
      "iPhone\nCore ML .mlmodelc"
    ],
    "takeaway": "Gemeinsame Gewichte sind die Basis; gleiche Ergebnisse müssen wir nachweisen.",
    "notes": "Die Quellhashes in den Modellmanifesten und im Serverregister verweisen auf denselben deutschen Klassifikator. Linux verwendet den PyTorch-Checkpoint, Android einen LiteRT-Export und iPhone das Core-ML-Artefakt. Es sind unterschiedliche Dateien. Die gesamte Detektionspipeline ist nicht identisch: SGBlur kann andere Modellgrößen und mehrere Bildauflösungen verwenden; mobil läuft YOLO11n im festen rechten 1024 × 1024-Fenster bei voller Bildhöhe. Die Croprandzugabe ist im Serveradapter 15 Prozent rundum, mobil asymmetrisch. Auch Rundungen und Nachverarbeitung können Ergebnisse ändern. Nach dem Training frieren wir einen ausgewählten Checkpoint ein, exportieren ihn und vergleichen denselben Korpus mit expliziten numerischen Toleranzen und gleicher Klassensemantik.",
    "sources": [
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_EXPORT_AND_SOURCE_PROVENANCE.md",
      "https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/deploy/prolix/models.json",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/iphone/SpeedConsumerApp/TSRModelPacks/DE.panoramax-bootstrap.tsrmodelpack/manifest.json",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/manifest.json"
    ],
    "sourceSlide": 11,
    "sourcePptxSlide": 12
  },
  {
    "title": "Welche Hardware rechnet die Inferenz?",
    "type": "gpuTable",
    "minutes": 2,
    "headers": [
      "Ziel",
      "Beschleunigung",
      "Was ist belegt?"
    ],
    "rows": [
      [
        "Linux / KI-Server",
        "NVIDIA CUDA",
        "2 × RTX A5000, je 24 GiB\nRTX PRO 6000 Blackwell, 96 GiB"
      ],
      [
        "Android-Testgerät",
        "LiteRT GPU-Delegate",
        "Mali-G615 MC2; CPU/XNNPACK bei Fehler"
      ],
      [
        "iPhone",
        "Core ML mit .all",
        "CPU, Apple GPU und Neural Engine erlaubt"
      ]
    ],
    "takeaway": "Belegt ≠ fest zugewiesen: die konkrete SGBlur-Host-GPU ist nicht nachgewiesen.",
    "notes": "Serverinventar vom 18. Oktober: Host-GPU 0 A5000, GPU 1 RTX PRO 6000 Blackwell Max-Q Workstation Edition, GPU 2 A5000. Prolix hat als Compose-Default CUDA_VISIBLE_DEVICES=1 und wählt intern cuda:0. Das ist die logische erste sichtbare GPU und keine zusätzliche Grafikkarte. Aufgezeichnete Canaries belegen CUDA-Ausführung, aber ein externes .env kann den Default überschreiben. Das Inventar ordnet SGBlur-Prozesse nicht sicher einer bestimmten Host-GPU zu. Auf Android ist GPU-Ausführung auf dem Moto g86 5G mit Mali-G615 MC2 dokumentiert. Historische gleiche Referenz: Median 521,59 ms GPU gegenüber 1419,33 ms CPU; kein allgemeines FPS-Versprechen. iPhone fordert .all an: Core ML entscheidet über CPU, GPU und Neural Engine. Die Neural Engine ist keine GPU. Eine konkrete Operationszuordnung müsste mit Xcode-Profiling gemessen werden.",
    "sources": [
      "https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/docs/youspeed/operations-evidence/2026-10-18-ki-ocr/server-status.json",
      "https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/deploy/prolix/compose.yml",
      "https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/prolix_pipeline/classifier.py",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/ANDROID_TSR_DEVICE_DIAGNOSIS_2026-09-14.md",
      "https://developer.apple.com/documentation/coreml/mlcomputeunits/all",
      "https://developers.google.com/edge/litert/android/gpu"
    ],
    "sourceSlide": 12,
    "sourcePptxSlide": 13
  },
  {
    "title": "Die Vorverarbeitung gehört zum Modellvertrag",
    "type": "steps",
    "minutes": 1,
    "items": [
      [
        "Koordinaten",
        "Orientierung und Bildgröße müssen zur Annotation passen"
      ],
      [
        "Detektor",
        "RGB · rechtes 1024²-Fenster, volle Höhe"
      ],
      [
        "Klassifikator",
        "Feste Ränder · RGB / 255 · Resize auf 224 × 224"
      ],
      [
        "Vergleich",
        "Labelreihenfolge, Fensterkoordinaten und Scores kontrollieren"
      ]
    ],
    "notes": "Beide Apps orientieren das Bild aufrecht, skalieren proportional auf 1024 Pixel Höhe und behalten die rechten 1024 Spalten. Schmale Hochformatbilder erhalten links RGB-114-Padding. Detektion, Klassifikation und lokale OCR arbeiten in diesen Fensterkoordinaten. Die mobile Klassifikation skaliert den vorgesehenen Bildausschnitt auf 224 × 224. Ein Default-CenterCrop kann bei einer breiten Ortstafel den Rand oder den Ausgangsstrich entfernen. Der Lernentwurf im Praktikum ersetzt deshalb die Standardtransformationen und verwendet den passenden Validator. Die exakte Interpolation und Pixelwerte müssen für strenge Parität dennoch geprüft werden. Bei Android heißt das Gewichtsartefakt float16, seine äußeren Eingabe-/Ausgabetensoren sind aber float32. Der Detektor hat NHWC [1,1024,1024,3] und Ausgabe [1,7,21504]; die sieben Werte sind vier Boxkoordinaten plus drei Objektklassen. Der Klassifikator hat [1,224,224,3] zu [1,134]. NMS ist in der Core-ML-Pipeline enthalten und auf Android nativ implementiert. Der YOLO26s-Kandidatenexport wählt ausdrücklich auf beiden Plattformen den One-to-many-Zweig, damit diese Verträge bestehen bleiben.",
    "sources": [
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/iphone/SpeedConsumerApp/TrafficSignRuntime.swift",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/android/app/src/main/java/de/youspeed/android/alpha/AndroidTrafficSignRuntime.kt",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/provenance/android-export-report.json",
      "https://docs.ultralytics.com/tasks/classify/#custom-transforms"
    ],
    "sourceSlide": 13,
    "sourcePptxSlide": 14
  },
  {
    "title": "Panoramax: Box zeichnen, Bedeutung prüfen",
    "type": "annotation",
    "minutes": 2,
    "image": "../assets/de/panoramax-annotation-detail.png",
    "body": [
      "Eine Box pro sichtbarer Tafel",
      "DE:310 = Ortseingang\nDE:311 = Ortsausgang",
      "Objekt-Tag: osm|traffic_sign\nSpeichern und gegenprüfen"
    ],
    "takeaway": "Das Label gehört zur Objektbox; ein Bild-Tag allein reicht nicht.",
    "notes": "Zeigen Sie die vorhandene Bernbach-Annotation im Screenshot oder öffnen Sie das Bild mit einem vorbereiteten Kurskonto. Der Screenshot dokumentiert einen vorhandenen Zustand; für die Vorlesung wurden keine Annotationen verändert. In Panoramax lautet der Schlüssel osm|traffic_sign, in OSM traffic_sign. Frontansicht, Rückseite und Verdeckung bewusst unterscheiden. Bei vorhandener generischer Schildbox die Semantik korrigieren statt ein Duplikat darüberzulegen. Geometrieänderungen benötigen laut API eine Ersatzannotation; das ist eine Aufgabe für das tatsächlich berechtigte Kursteam. Bei unlesbarer oder unklarer Tafel markieren wir Unsicherheit statt zu raten. Nach dem Speichern erneut öffnen und Box sowie Semantik gegenprüfen. Der gespeicherte Screenshot steht als Demo-Reserve bereit. Das ergänzte Dobel-Bild und seine aktuelle Annotation wurden über Viewer und API lesend geprüft. Die beiden Codes ausdrücklich vorlesen: DE:310 bedeutet Ortseingang, DE:311 bedeutet Ortsausgang. Der Wert wird am Objekt unter dem Schlüssel osm|traffic_sign gespeichert.",
    "sources": [
      "https://panoramax.youspeed.de/?pic=a458609a-bbf1-413a-a039-5e0f685e9923&focus=pic",
      "https://docs.panoramax.fr/backend/install/deep_dive/semantics/",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/lectures/ASSET_CREDITS.md"
    ],
    "sourceSlide": 14,
    "sourcePptxSlide": 15
  },
  {
    "title": "Der Crawler sammelt Beispiele für beide Modelle",
    "type": "datasets",
    "minutes": 1.5,
    "headers": [
      "Detektor: Vollbilder + Boxen",
      "Klassifikator: Bildausschnitte"
    ],
    "columns": [
      [
        "inbox/detector/<bild-ID>/",
        "Bild + labels.txt + Metadaten",
        "Schilder, Kennzeichen, Gesichter",
        "Prüfen → approved/detector/<bild-ID>/"
      ],
      [
        "Bildausschnitte: inbox/classifier/",
        "DE:310 → city__start",
        "DE:311 → city__end",
        "Prüfen → approved/classifier/<klasse>/"
      ]
    ],
    "takeaway": "Datenpakete: huggingface.co/datasets/loffenauer/ws26_hspf_imo",
    "notes": "Das bereitgestellte Skript praktikum/crawl_panoramax.py liest vorhandene Panoramax-Objektannotationen und lädt die verfügbaren HD-Bildableitungen. Es führt keinen Detektor oder Klassifikator aus und verändert die Instanz nicht. Es sammelt zwei ungeprüfte Sätze unter data/collection/inbox: vollständige Bilder samt allen erkannten vorhandenen Boxannotationen für den Detektor sowie einen Bildausschnitt je Schildannotation für den Klassifikator. Die Studierenden prüfen die Beispiele und verschieben die Bildausschnitte in approved/classifier/<klassenordner>; der Ordner bestimmt das korrigierte Klassenlabel. Die Ordner city__start und city__end entsprechen intern city:start beziehungsweise city:end. Unbekannte Schildklassen können ebenfalls den bereitgestellten Bestandsordnern zugeordnet werden. Für den Detektor wird der komplette Ordner mit image.png, labels.txt und metadata.json nach approved/detector/<bild-ID> verschoben. Dies bestätigt ausdrücklich die vollständige Prüfung aller drei Klassen sign, plate und face; eine vorhandene Schildannotation allein beweist diese Vollständigkeit nicht. Fehlende oder falsche Boxen müssen zunächst in Panoramax korrigiert und erneut abgerufen werden. Verschieben korrigiert keine Boxgeometrie. Öffentliche HD-Ableitungen können bereits anonymisiert sein; sie belegen keine Erkennung ungeblurter Gesichter und Kennzeichen. Metadaten, Lizenz, Autor, IDs und SHA-256 bleiben im Manifest erhalten. Der Crawler nutzt nur GET, folgt ausschließlich den next-Links der Seiten und dokumentiert Limits oder unvollständige Abrufe. Panoramen werden im Einstieg übersprungen; HD-Boxen werden nicht unverändert auf SD-Bilder übertragen. Einzelheiten und Verschiebebeispiele stehen in praktikum/SAMMELN_UND_SORTIEREN.md. Als vorbereiteten Einstieg verwenden Sie die sechs veröffentlichten Datenpakete unter https://huggingface.co/datasets/loffenauer/ws26_hspf_imo. Der Crawler bleibt für eigene Ergänzungen verfügbar. Die große Lernsammlung enthält 100 Vollbilder und 214 Bildausschnitte. Die beiden kleinen Demobilder sind bereits darin enthalten. Die zwei zusätzlichen Kandidatenpakete bleiben für den Dozenten reserviert und gelangen nicht in den normalen Trainingsimport. Die Downloadanleitung praktikum/DATEN_HERUNTERLADEN.md nennt den unveränderlichen Dataset-Commit e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8, Prüfsummen und die tatsächlichen Archivwurzeln. Alle Dateien bleiben bis zur menschlichen Prüfung ungeprüft.",
    "sources": [
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/select_panoramax_end_signs.py",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/diagnostic_dataset.py",
      "https://docs.panoramax.fr/backend/install/deep_dive/semantics/",
      "https://docs.panoramax.fr/backend/dev/STAC_compatibility/",
      "https://docs.panoramax.fr/cli/COMMANDS/#panoramax_cli-download",
      "https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/tree/e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8"
    ],
    "datasetUrl": "https://huggingface.co/datasets/loffenauer/ws26_hspf_imo",
    "sourceSlide": 15,
    "sourcePptxSlide": 16
  },
  {
    "title": "Eine feste Struktur für Training, Validierung und Test",
    "type": "datasetPlan",
    "minutes": 2,
    "body": [
      "Gruppieren nach physischem Schild, Fahrt und Nahe-Duplikaten",
      "Dann Training, Entwicklungsvalidierung und unabhängigen Test trennen",
      "Kalibration / Schwellenwahl getrennt dokumentieren",
      "Erst danach augmentieren oder häufigere Beispiele erzeugen"
    ],
    "takeaway": "Beide Sätze verwenden dieselben Gruppen; die Zuordnung zu train / val / test erfolgt automatisch.",
    "notes": "Die Studierenden ordnen nur Klasse und Eignung zu, nicht den Split. import_sorted_folders.py liest die geprüften Ordner, verifiziert Dateien und Hashes und übernimmt Bild-/Annotations-/Sequenzidentität aus dem Crawler-Manifest. Standardmäßig bleibt eine ganze Sequenz zusammen. Physisch gleiche Tafeln oder zusammengehörende Fahrten über mehrere Sequenzen müssen vorab über die gemeinsame Gruppen-CSV zusammengeführt werden; das Skript entdeckt solche Beziehungen nicht selbst. Beide Sätze verwenden dieselbe Funktion partition_for_group und Seed 20261026 mit Zielanteilen 70/15/15. Ein Vollbild und alle seine Bildausschnitte bleiben dadurch im gleichen Split. Der Detektorsatz liegt anschließend direkt unter data/reviewed/detector mit images, labels und data.yaml. Für den Klassifikator entstehen data/reviewed/classifier/annotations.csv und images. Der zusätzliche bereitgestellte Bestand alter Klassen kann beim Import zusammengeführt werden. Anschließend materialisiert prepare_dataset.py mit diesen beiden Eingabepfaden den festen Ordner data/dataset für die unveränderten Trainings-/Evaluationsskripte. Hierzu lautet der Befehl: python prepare_dataset.py --annotations data/reviewed/classifier/annotations.csv --images data/reviewed/classifier/images. Alle 136 Klassen müssen im Klassifikatortraining vertreten sein. Fehlende Prüfklassen führen später weiterhin zu UNVOLLSTAENDIG. Das lokale Panoramax-Korpus garantiert keine vollständige Abdeckung aller alten Klassen. Bereits eingefrorene Tests werden nicht für bessere Ergebnisse neu aufgeteilt. Die zusätzlichen Hugging-Face-Testkandidaten sind ausdrücklich aus diesem normalen 70/15/15-Import ausgeschlossen. Der Dozent hält sie getrennt, prüft Klassen, vollständige Boxen und gemeinsame physische Standorte beziehungsweise Fahrten und erstellt erst danach einen eigenen eingefrorenen Testexport. Der bisherige Evaluator benötigt dafür einen gesonderten Modus und darf nicht durch geänderte Checkpoint-Metadaten umgangen werden.",
    "sources": [
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/group_splits_v2.py",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_TRAINING_ROUND_TRIP.md",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/shared/tsr/training-sources-v1.json"
    ],
    "tree": "data/dataset/\n  train/<klasse>/   ca. 70 %\n  val/<klasse>/     ca. 15 %\n  test/<klasse>/    ca. 15 %\n  manifest.json",
    "roles": [
      [
        "Training",
        "Hier lernt das Netz seine Gewichte."
      ],
      [
        "Validierung",
        "Hier wählen Sie den besten Kandidaten."
      ],
      [
        "Test",
        "Einmaliger Abschlusstest nach der Auswahl."
      ]
    ],
    "command": "python import_sorted_folders.py",
    "sourceSlide": 16,
    "sourcePptxSlide": 17
  },
  {
    "title": "Prolix einrichten und seine Rolle verstehen",
    "type": "prolix",
    "minutes": 2,
    "code": "git clone https://gitlab.com/panoramax/clients/prolix.git\ncd prolix\ngit checkout --detach 36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f\ngit submodule update --init --recursive\npython3.12 -m venv env\nsource env/bin/activate\npython -m pip install -e .\nprolix --help",
    "body": [
      "Prolix: Inferenz → räumlich zusammenführen → Annotationen",
      "Training und Ground-Truth-Evaluation: PyTorch / Ultralytics"
    ],
    "takeaway": "Aktuelles upstream main und der gepinnte Deploymentstand unterscheiden sich.",
    "notes": "Die offizielle Installation und der tatsächliche Quellstand wurden gelesen. Der hier gezeigte Commit ist derselbe ältere Upstreamstand wie im Deployment. Er bietet run-model-traffic-signs, analyze-traffic-signs und upload-annotations; keinen Trainings- oder Evaluationsbefehl. Der Stockrunner ist französisch festgelegt und --models-path ändert nur den Speicherort. Aktuelles main dokumentiert inzwischen --country DE; diese Option darf nicht auf die alte Version übertragen werden. Der Projektadapter im Schwesterrepo ergänzt die Länderlogik. Wir verwenden Python 3.12, weil der gelesene Quellcode Path.walk und weitere 3.12-APIs nutzt. Vor der Installation müssen im separaten Kursimage CUDA-fähiges Torch und die native TurboJPEG-Bibliothek bereitstehen. pip freeze hält das Ergebnis fest; für reproduzierbare Kurse benötigen wir zusätzlich einen vorab aufgelösten Lock und Image-Digest. Der lange Installationsblock wird erläutert, nicht live im Produktionsdienst ausgeführt.",
    "sources": [
      "https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/docs/Install.md",
      "https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/pyproject.toml",
      "https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/prolix/models.py",
      "https://gitlab.com/panoramax/clients/prolix/-/blob/main/docs/Commands.md",
      "https://github.com/volzinnovation/Woladen.de-analytics/blob/614f0950086e009b7af6356518fa05aa07d5aa55/deploy/prolix/requirements.txt"
    ],
    "sourceSlide": 17,
    "sourcePptxSlide": 18
  },
  {
    "title": "Datenpakete auf dem KI-Server herunterladen",
    "type": "serverDownload",
    "minutes": 3,
    "evidenceDate": "21. Oktober 2026",
    "datasetUrl": "https://huggingface.co/datasets/loffenauer/ws26_hspf_imo",
    "datasetLabel": "huggingface.co/datasets/loffenauer/ws26_hspf_imo",
    "intro": "Vollständige Lernsammlung: 220 Vollbilder und 334 Bildausschnitte",
    "code": ".venv-hf/bin/hf download loffenauer/ws26_hspf_imo \\\n  --include 'packages/panoramax-studenten-*' \\\n  --include 'packages/panoramax-mobidata-*' --include LEARNING_COLLECTION.json \\\n  --include SHA256SUMS.txt --type dataset \\\n  --revision e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8 --local-dir data/downloads",
    "body": [
      "MobiData BW: 57 + 63 Paare; drei Lernarchive insgesamt",
      "Klassen und Boxen prüfen; Testkandidaten getrennt aufbewahren"
    ],
    "takeaway": "Vollständige Befehle: praktikum/DATEN_HERUNTERLADEN.md",
    "notes": "Laden Sie die vollständige Lernsammlung aus drei Archiven herunter: die 100er-Sammlung mit 214 Crops, MobiData BW v2 mit 57 Paaren und die zusätzliche MobiData-Sammlung mit 63 Paaren. Zusammen stehen 220 Vollbilder und 334 unterschiedliche Crop-Dateien zur Prüfung bereit. 190 Ortstafel-Kandidaten tragen Quell-Tags beziehungsweise visuelle Vorschläge, davon 144 DE:310 und 46 DE:311. Diese Zahlen belegen weder bestätigte Klassen noch unabhängige physische Tafeln; fünf Ortstafel-Crops der ersten Sammlung haben gemischte Quell-Tags. Der sichtbare Befehl nutzt wiederholte --include-Optionen und lädt genau die drei Lernarchive, LEARNING_COLLECTION.json und SHA256SUMS.txt. Die Optionen werden jeweils wiederholt; weitere Muster werden nicht als freie Dateinamen angehängt. Der feste Commit e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8 fixiert den geprüften Datenstand. Die Download-CLI liegt getrennt in .venv-hf; installieren Sie huggingface_hub==1.10.2, typer==0.24.1 und click==8.3.2 nach der Anleitung. Ein Hugging-Face-Konto oder Token ist für den öffentlichen Download nicht nötig. Prüfen Sie alle drei ZIP-Dateien und den Sammlungsindex vor dem Entpacken. Der Index nennt Archivwurzeln, Prüfsummen und Zielordner. Entpacken Sie nach data/collection, data/collection-mobidata-bw und data/collection-mobidata-bw-additions, ohne bestehende Reviews zu überschreiben. Öffnen Sie beide MobiData-SICHTUNG.html. Prüfen Sie die Klassen und alle Vollbildboxen. Die MobiData-Archive enthalten Teilannotation und benötigen einen passenden Kurs-Export; der Standardimporter kann sie nicht unverändert übernehmen. Erhalten Sie Vollbilder, Quellmetadaten, Urheber, Lizenz und Hashes. Gruppieren Sie gleiche Tafeln und mögliche Fahrten über alle drei Lernarchive hinweg. Die zwei ausdrücklich reservierten Testkandidatenpakete bleiben beim Dozenten und werden weder für Training noch Validierung oder Epochenwahl verwendet. Das kleine Demo ist schon in der 100er-Sammlung enthalten. Der ursprüngliche 134-Klassen-Korpus und der Baselinecheckpoint werden separat bereitgestellt. Die Studierenden führen Training und Modellauswertung selbst durch.",
    "sources": [
      "https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/tree/e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8",
      "https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8/SHA256SUMS.txt",
      "https://huggingface.co/docs/huggingface_hub/guides/cli#download-files",
      "https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8/LEARNING_COLLECTION.json"
    ],
    "sourceSlide": 18,
    "sourcePptxSlide": 19
  },
  {
    "title": "Nur bei fehlenden Boxen den Detektor nachtrainieren",
    "type": "detector",
    "minutes": 1,
    "body": [
      "Vollbilder mit vollständigen Boxen aller drei Klassen prüfen",
      "DE:310 und DE:311 bleiben beim Detektor generisch sign",
      "Import schreibt YOLO-Bilder, Labels und feste Gruppensplits",
      "Gesicht / Kennzeichen im unabhängigen Vergleich mitprüfen"
    ],
    "code": "yolo detect train model=models/detector-baseline.pt \\\n  data=data/reviewed/detector/data.yaml \\\n  epochs=20 imgsz=1280 device=0 seed=20261026",
    "notes": "Das Ortstafelprojekt benötigt nicht zwingend zwei neue Detektorklassen. Wenn die generische Lokalisierung bereits funktioniert, liegt der erste Hebel beim Klassifikator. Falls auf einem unabhängigen Vollbildsatz Tafelboxen fehlen, können zusätzliche Boxannotationen und ein Detektorversuch nötig sein. Aus Pixelbox [xmin,ymin,xmax,ymax] entstehen normierter Mittelpunkt cx,cy und Breite/Höhe. Zur Prüfung die Labels wieder auf das Bild zeichnen. Für Vollbilder alle relevanten Objekte vollständig annotieren; unvollständige Ziele erzeugen falsches Hintergrundtraining. Beim gemeinsamen SGBlur-Modell gehören face und plate zum Regressionstest, weil diese Ausgänge der Anonymisierung dienen. Das neue Importskript liefert data/reviewed/detector/data.yaml mit der festen Klassenreihenfolge 0=sign, 1=plate, 2=face. Der Dozent stellt models/detector-baseline.pt als unveränderte lokale Kopie von yolo11n_panoramax.pt aus cquest/sgblur bereit, Revision 169451970702aca0dde9ff3106dba0f67e0b88a8. SHA-256: 698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a. Dieser ursprüngliche SGBlur-YOLO11n hat 0=sign, 1=plate, 2=face. Der lokale Dateiname ist nur ein Alias für genau diese Gewichte. imgsz=1280 im gezeigten Befehl ist eine gewählte Größe für diesen Trainingsversuch; der gespeicherte Original-Trainingswert ist 2048, und die aktuelle App-Inferenz verwendet 1024×1024. Ein Vollbild wird erst nach vollständiger Prüfung aller Klassen in den Trainingssatz übernommen. Wenn Validierung oder Test mangels unabhängiger Gruppen leer sind, sind weitere Daten nötig; die Gruppen werden nicht neu gewürfelt. Ultralytics verwendet die vorbereiteten Pfade und wählt den Trainingskandidaten anhand der Validierung. Der Test wird erst nach Auswahl mit yolo detect val ... split=test ausgeführt. Für den Detektor werden die per-class Metriken von Ausgangsmodell und Kandidat auf denselben zurückgehaltenen Vollbildern verglichen. Der technische Crawler-Test ist keine echte Trainings- oder Qualitätsmessung. Fine-Tuning kann auf ausgewählte Teile beschränkt werden.",
    "sources": [
      "https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/models/yolo11n_panoramax.pt",
      "https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/src/detect/detect.py",
      "https://docs.ultralytics.com/datasets/detect/",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_PROLIX_ALIGNMENT_2026-09-10.md"
    ],
    "evidenceDate": "20. Oktober 2026",
    "sourceSlide": 20,
    "sourcePptxSlide": 21,
    "baselineLink": [
      "SGBlur-YOLO11n: yolo11n_panoramax.pt → models/detector-baseline.pt",
      "https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/models/yolo11n_panoramax.pt"
    ]
  },
  {
    "title": "Fine-Tuning mit dem Panoramax-Modell",
    "type": "fineTuning",
    "minutes": 2,
    "evidenceDate": "20. Oktober 2026",
    "definition": "Ein vortrainiertes Modell lernt mit beschrifteten Bildern weiter.\nDabei ändern sich seine Gewichte.",
    "modelLabel": "Ausgangsmodell: Panoramax/classify_de_road_signs",
    "modelUrl": "https://huggingface.co/Panoramax/classify_de_road_signs",
    "modelSpec": "YOLO26l-cls · 134 Klassen · Bildausschnitte mit 224 × 224 Pixeln",
    "code": "python train.py --epochs 20",
    "body": [
      "Gewichte übernehmen, Classification Head auf 136 Klassen erweitern",
      "Mit alten Schildern und geprüften Ortstafeln gemeinsam weiterlernen",
      "Validierung wählt best.pt. Der Abschlusstest folgt danach."
    ],
    "takeaway": "Eine Epoche = ein Durchlauf. Beginnen Sie mit 20 Epochen und prüfen Sie die Validierung.",
    "notes": "Fine-Tuning bedeutet, die Gewichte eines bereits trainierten Modells mit passenden beschrifteten Beispielen weiter zu optimieren. Die vorhandenen Bildmerkmale dienen als Ausgangspunkt. Beim Training von Grund auf wären die Gewichte zunächst zufällig. Das bereitgestellte Trainingsskript optimiert alle Modellgewichte weiter. Eine Variante friert einige Schichten ein und lernt nur die übrigen weiter. Das ist eine bewusste Trainingsentscheidung, keine automatische Eigenschaft des Begriffs. Prolix bindet den Klassifikator ein; der konkrete Gewichteanbieter ist Panoramax auf Hugging Face. Die Modellkarte nennt eine Feinabstimmung auf Panoramax/classified_de_road_signs und YOLOv26. Unser tatsächlich geprüfter Checkpoint ist YOLO26l-cls mit 134 Klassen und 13.006.278 Parametern. Ausgangsdatei classify_de_road_signs.pt, Revision 5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790, SHA-256 f8277a3790fd3357b3ca31a086c7dc9f365785c7fa44bfd3b5c68834555699c7, 26.282.865 Byte. Der Dozent legt sie nach Prüfung unter models/baseline.pt ab. praktikum/train.py liest den festen Datensatz und erweitert den Classification Head: Die 134 alten Zeilen bleiben anfangs namens- und indexgetreu erhalten, zwei neue Zeilen für city:start und city:end werden initialisiert. Das ergänzt 2.562 Parameter und ergibt 13.008.840 Parameter. Die Studierenden verwenden den bereitgestellten PyTorch-Trainingsloop. RGB-Bildausschnitte werden vollständig auf 224×224 skaliert und mit 1/255 normalisiert. Eine Epoche ist ein Durchlauf durch die Trainingsbilder. runs/versuch-01 enthält Konfiguration, progress.csv und weights/best.pt. Die 98,6 Prozent Accuracy auf der Modellkarte sind eine selbst berichtete Herausgeberangabe. Sie stammen nicht aus unserem Prüfbestand und belegen keine Qualität für DE:310/311. Zusätzlich überlappen die veröffentlichten train/val-Archive um 522 exakt gleiche Bilder. Gruppieren Sie solche Duplikate vor der Aufteilung. Die alten Bilder können dem Ausgangsmodell dennoch bekannt sein, daher bleibt dieser Teil ein rückblickender Regressionstest. Siehe source/hf-model-card-review-2026-10-20.json. Der neue Kandidat enthält state_dict und Metadaten und benötigt model_utils.load_candidate(). Der Core-ML-/LiteRT-Export dieses Kandidaten ist noch nicht getestet.",
    "sources": [
      "https://huggingface.co/Panoramax/classify_de_road_signs/blob/5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790/README.md",
      "https://huggingface.co/datasets/Panoramax/classified_de_road_signs/tree/b4856947ed7cb6312587258acc90e8cf88a4aa13",
      "https://docs.pytorch.org/tutorials/beginner/transfer_learning_tutorial.html",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/train_fr_end_sign_classifier.py",
      "https://docs.ultralytics.com/tasks/classify/#custom-transforms",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/shared/tsr/prolix-de-class-catalog-v1.json",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/bootstrap_sources.py"
    ],
    "sourceSlide": 19,
    "sourcePptxSlide": 20
  },
  {
    "title": "Precision, Recall und F1 beim Klassifizieren",
    "type": "classificationMetrics",
    "minutes": 2,
    "evidenceDate": "20. Oktober 2026",
    "intro": "Erfundenes Rechenbeispiel: 10 Bildausschnitte, nur DE:310 und DE:311",
    "matrixHeaders": [
      "Tatsächlich",
      "Vorhersage\nDE:310",
      "Vorhersage\nDE:311"
    ],
    "matrixRows": [
      [
        "6 × DE:310\nOrtseingang",
        "4",
        "2"
      ],
      [
        "4 × DE:311\nOrtsausgang",
        "1",
        "3"
      ]
    ],
    "counts": "Für DE:310: 4 richtig, 1 falsch gemeldet,\n2 als DE:311 eingeordnet",
    "headers": [
      "Klasse",
      "Precision",
      "Recall",
      "F1"
    ],
    "rows": [
      [
        "DE:310",
        "4/5 = 80 %",
        "4/6 ≈ 67 %",
        "8/11 ≈ 73 %"
      ],
      [
        "DE:311",
        "3/5 = 60 %",
        "3/4 = 75 %",
        "6/9 ≈ 67 %"
      ]
    ],
    "notes": "Alle Zahlen dieser Folie sind frei erfunden und dienen ausschließlich zum Rechnen. Die nächste Folie zeigt, welche Werte Sie selbst ermitteln und vergleichen. Jeder Bildausschnitt enthält genau eine Tafel und das Spielzeugmodell kann nur DE:310 oder DE:311 vorhersagen. Die Box ist bereits vorgegeben. Hier wird die richtige Klasse bewertet, nicht das Finden einer Box. Beginnen Sie mit den tatsächlichen Klassen in den Zeilen: sechs Ortseingänge, vier Ortsausgänge. In den Spalten steht die Modellvorhersage. Für DE:310 liegen vier richtige Zuordnungen vor. Ein echter Ortsausgang wurde fälschlich als Ortseingang gemeldet. Zwei echte Ortseingänge wurden als Ortsausgang eingeordnet. Precision fragt: Wie viele der fünf DE:310-Vorhersagen stimmen? Vier von fünf, also 80 Prozent. Recall fragt: Wie viele der sechs echten Ortseingänge wurden richtig zugeordnet? Vier von sechs, etwa 67 Prozent. Precision hat alle Vorhersagen dieser Klasse im Nenner, Recall alle tatsächlich vorhandenen Beispiele dieser Klasse. Ein hoher Recall alleine verhindert keine falschen Meldungen; eine hohe Precision alleine verhindert keine ausgelassenen richtigen Ziele. F1 verbindet beide durch das harmonische Mittel, 2×P×R/(P+R), mit P und R als Anteilen zwischen null und eins. Für DE:310 ergibt sich 8/11, etwa 73 Prozent. Das ist nicht das einfache arithmetische Mittel. Mit Trefferzahlen lautet dieselbe Formel 2×richtig/(2×richtig+falsch gemeldet+falsch als andere Klasse eingeordnet). Für DE:311 wechseln wir den Blick auf die andere Klasse: drei richtige, zwei falsch gemeldete und ein als DE:310 eingeordneter Ortsausgang. Precision 3/5=60 Prozent, Recall 3/4=75 Prozent und F1 6/9≈67 Prozent. Lassen Sie die Studierenden die Nenner fünf und vier an der Matrix zeigen. Im realen 136-Klassen-Modell zählt jede andere Klasse als Gegenklasse der betrachteten Klasse. Die drei Werte werden je Klasse berechnet. Ein F1-Wert von 0,80 entspricht 80 Prozent. Zum Einstieg sind die Kürzel TP, FP und FN nicht erforderlich.",
    "sources": [
      "https://scikit-learn.org/stable/modules/model_evaluation.html#precision-recall-f-measure-metrics"
    ],
    "sourcePptxSlide": 22
  },
  {
    "title": "Fortschritt messen – und alte Klassen bewahren",
    "type": "beginnerEvaluation",
    "minutes": 2,
    "headers": [
      "Prüfung",
      "Ihre Auswertung nach der Kandidatenwahl"
    ],
    "rows": [
      [
        "Neue Klassen:\nBildausschnitte",
        "DE:310 / DE:311: Support, Precision, Recall und F1"
      ],
      [
        "134 Bestandsklassen",
        "Jede Klasse auf denselben Prüfbeispielen vergleichen"
      ],
      [
        "Recall / F1 je Klasse",
        "Rückgänge melden; fehlende Abdeckung kennzeichnen"
      ]
    ],
    "notes": "Das Skript evaluate.py vergleicht unveränderte Baseline und Kandidat standardmäßig auf val. Es schreibt einen lesbaren Bericht, JSON-Metriken und Konfusions-/Klassen-CSV. Für die alten 134 Klassen werden dieselben zurückgehaltenen Beispiele alter Klassen verwendet, ohne neue Ortstafel-Beispiele in diesen Teilvergleich einzumischen. Für jede alte Klasse werden Recall und F1 gegenüber dem Ausgangsmodell geprüft. Ein Rückgang über reine numerische Rundung hinaus führt zu REGRESSION und einem Fehlerstatus. Fehlt eine alte Klasse im Prüfbestand, lautet das Ergebnis UNVOLLSTAENDIG; eine fehlende Klasse wird nicht als bestanden gewertet. Der Gewinn bei zwei neuen Klassen kompensiert keine Verschlechterung bei Bestandsklassen. BESTANDEN und Exitcode 0 beziehen sich nur auf das Bestandsklassen-Gate. Die Precision-, Recall- und F1-Werte der neuen Klassen sind zusätzlich zu beurteilen; dies ist keine automatische Gesamtfreigabe. Gesamtgenauigkeit allein reicht nicht. Erst nach der Kandidatenauswahl wird derselbe Befehl mit --split test --output reports/abschluss ausgeführt. Aussagen gelten für den dokumentierten, endlichen Prüfbestand und sind keine Garantie für alle zukünftigen Straßenbilder. Berechnen Sie Ihre Ergebnisse selbst und erklären Sie Fehlbilder. Eine höhere Gesamtgenauigkeit kann einzelne Klassenrückgänge verdecken.",
    "sources": [
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/evaluate_ch_classifier.py",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_TRAINING_ROUND_TRIP.md",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_FR_END_SIGN_TRAINING.md"
    ],
    "command": "python evaluate.py \\\n  --candidate runs/versuch-01/weights/best.pt",
    "takeaway": "Kandidaten mit Validierung wählen. Erst danach den Test auswerten.\nNeue und bestehende Klassen getrennt beurteilen.",
    "evidenceDate": "20. Oktober 2026",
    "sourceSlide": 21,
    "sourcePptxSlide": 23
  },
  {
    "title": "Denselben Kandidaten auf allen Zielen prüfen",
    "type": "parity",
    "minutes": 1,
    "steps": [
      [
        "1",
        "Einfrieren",
        "Gewichte-Hash, Datensatz-/Split-Hash, Labelindex und Konfiguration"
      ],
      [
        "2",
        "Konvertieren",
        "PyTorch → Core ML / LiteRT; getrennte Paketstände dokumentieren"
      ],
      [
        "3",
        "Vergleichen",
        "Gleiche Bildausschnitte und Vollbilder; Semantik, Boxen, Scores und Laufzeit"
      ],
      [
        "4",
        "Integrieren",
        "Vorhandene Schnittstellen nutzen; auf beiden Telefonen prüfen"
      ]
    ],
    "takeaway": "Der DE-Ortstafel-Export ist anzupassen; das vorhandene Fremdländer-CLI akzeptiert kein DE.",
    "notes": "Das im Kurs erzeugte best.pt enthält ein eigenes sicheres state_dict plus Metadaten und ist kein direktes Ultralytics-Exportartefakt. Zuerst muss model_utils.load_candidate() das trainierte Modell rekonstruieren; ein direkter Befehl yolo export model=best.pt ist dafür ungeeignet. Die Core-ML-/LiteRT-Konvertierung dieses Kursformats wurde noch nicht getestet. Die vorhandenen Dockerfiles unter scripts/tsr/foreign-export trennen Core ML und LiteRT. Das dortige Export-CLI erlaubt aktuell FR, NL, BE und CH, aber kein DE. Der deutsche Ortstafel-Kandidat braucht deshalb einen angepassten und überprüften Exportweg, keine erfundene --country-DE-Option. Core-ML-Konvertierung kann auf Linux vorbereitet werden; die mlmodelc-Kompilierung und Einbindung bleibt beim Mac/Xcode-Schritt. Serverreferenz und Exporte auf dem gleichen orientierten Korpus vergleichen; zunächst Bildausschnitte isolieren, danach Vollbilder. Erst Modellsemantik, dann Laufzeit und vollständige Passage prüfen. Die vorhandene geschützte Geschwindigkeitsreferenz-Policy wird für diese Vorlesung nicht verändert. Ein erkanntes DE:311 setzt nicht blind 100 km/h. Veröffentlichung oder Deployment ist nicht Teil des Unterrichtsbeispiels.",
    "sources": [
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/foreign-export/Dockerfile.coreml",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/foreign-export/Dockerfile.litert",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/foreign-export/export_classifier.py",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/shared/speed-limit-reference/AGENTS.md"
    ],
    "sourceSlide": 22,
    "sourcePptxSlide": 24
  },
  {
    "title": "Partnerübung: drei Fehler, drei nächste Schritte",
    "type": "exercise",
    "minutes": 3,
    "items": [
      [
        "A",
        "Im Vollbild fehlt die Ortstafelbox. Der manuelle Bildausschnitt wird richtig erkannt."
      ],
      [
        "B",
        "Die Box passt. Das alte Modell liefert bad; DE:310 fehlt im Inventar."
      ],
      [
        "C",
        "Test mit Bildausschnitten sehr gut. Auf einer neuen Strecke sinkt die Erkennung stark."
      ]
    ],
    "question": "Welche Stufe, welche zusätzlichen Daten und welcher Test helfen jeweils?",
    "notes": "Geben Sie 90 Sekunden zum Austausch und danach 90 Sekunden für die gemeinsame Lösung. A: Lokalisierung untersuchen; Vollbilder mit vollständigen Boxlabels, unabhängigen Detector-Recall messen. B: Klassifikator erweitern und Gewichte mit neuen/alten geprüften Bildausschnitte trainieren; Klasse sowie Indexmapping und Verwechslungen testen. C hat mehrere mögliche Ursachen: Split-Leakage, andere Aufnahmebedingungen oder Lokalisierungsfehler. Zuerst physische Schildgruppen, Größe/Blickwinkel und die beiden Stufen getrennt prüfen. Ein weiteres blindes Training ist keine Diagnose. Gute Antworten nennen einen überprüfbaren nächsten Schritt statt nur ein größeres Netz. Die Musterlösung steht im Dozentenleitfaden.",
    "sources": [
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_PROLIX_ALIGNMENT_2026-09-10.md",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/scripts/tsr/group_splits_v2.py"
    ],
    "sourceSlide": 23,
    "sourcePptxSlide": 25
  },
  {
    "title": "Ihr Ergebnis ist ein reproduzierbarer Modellversuch",
    "type": "steps",
    "minutes": 1,
    "items": [
      [
        "Daten",
        "Geprüfte Boxen / Bildausschnitte, Herkunft und unabhängige Schildgruppen"
      ],
      [
        "Code",
        "Trainingsumgebung, Seed, Klassenindex und Versionsstände"
      ],
      [
        "Beleg",
        "Baseline ↔ Kandidat; neue Klassen, Altklassen und Fehlbilder"
      ],
      [
        "Übertragung",
        "Checkpoint + Exporte; Linux, Android und iPhone vergleichen"
      ]
    ],
    "notes": "Der Projektbericht muss erkennen lassen, welche Modellstufe verbessert wurde und wie groß der unabhängige Test ist. Datensatz und Modell erhalten Versionen und Hashes, dazu Paketlock beziehungsweise Image-Digest und den ausführbaren Versuch. Die längeren Schritte stehen im Praktikum. Als kurzer Lerncheck: Warum hilft eine Mappingänderung allein nicht? Warum kann ein Test mit Bildausschnitten fehlende Detektorboxen nicht beurteilen? Warum ist device 0 im Container nicht zwingend Host-GPU 0? Die Antworten zeigen, ob die Verbindung zwischen Daten, Modell und Laufzeit verstanden wurde.",
    "sources": [
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_TRAINING_ROUND_TRIP.md"
    ],
    "sourceSlide": 24,
    "sourcePptxSlide": 26
  },
  {
    "title": "Fragen?",
    "type": "questions",
    "minutes": 2,
    "body": [
      "Wie würden Sie jetzt den ersten Versuch für DE:310 und DE:311 aufsetzen?"
    ],
    "notes": "Zwei Minuten für Fragen und den Übergang zur Projektarbeit. Falls keine Fragen kommen: Eine Person nennt das erste Datenartefakt, eine zweite die erste GPU-Probe und eine dritte die wichtigste Testtrennung. Erwartet werden eine überprüfte Box-/Bildausschnitt-Liste mit Quellen und Gruppen, ein echter Forward-/Backward-/Save-Reload-Smoke und ein Test an bislang unbekannten physischen Schildern. Nicht voraussetzen, dass während 45 Minuten bereits ein produktiver Modellkandidat trainiert oder deployed wurde.",
    "sources": [
      "https://gitlab.com/panoramax/clients/prolix/-/blob/36bb92bed7d8aba1d87c1fd10fcdf8ec7f06046f/README.md",
      "https://github.com/volzinnovation/youspeed.de/blob/917de04668100f2b48dadd5ed35391535cabd5ec/docs/TSR_TRAINING_ROUND_TRIP.md"
    ],
    "sourceSlide": 25,
    "sourcePptxSlide": 27
  }
];
