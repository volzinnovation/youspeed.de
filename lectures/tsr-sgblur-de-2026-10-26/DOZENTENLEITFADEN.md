# Bildklassifikation mit KI

## Wie verbessere ich ein vorhandenes KI-Modell?

**Montag, 26. Oktober 2026 · Prof. Dr. Raphael Volz · HSPF**
27 Folien · Fassung v9.1 · 45 Minuten einschließlich Partnerübung und Fragen. Technischer Quellenstand: 19. Oktober 2026; dokumentierte Trainingsversuche: 20. Oktober 2026.

Der Einstieg richtet sich an Studierende im 3. Semester ohne ML-Vorkenntnisse. Sie sollen anschließend einen vorhandenen Klassifikator mit geprüften Panoramax-Bildausschnitten um **Ortseingang `DE:310`** und **Ortsausgang `DE:311`** erweitern und den Kandidaten mit dem Ausgangsmodell vergleichen können. Die 134 bisherigen Klassen dürfen im vorab festgelegten Bestandsvergleich nicht schlechter werden. Der tatsächlich ausgeführte Versuch zeigt, warum diese Bedingung nötig ist: bessere Ortstafelklassifikation bei gleichzeitig gemessener Regression alter Klassen.

Die Studierenden verwenden vorbereitete Skripte zum Sammeln, Einsortieren, Aufteilen, Trainieren und Bewerten. Sie müssen weder einen Trainingsloop schreiben noch CUDA installieren. Die verbindliche Einstiegsanleitung ist [praktikum/README.md](praktikum/README.md). Die vier ungeprüften Panoramax-Pakete sind unter [loffenauer/ws26_hspf_imo](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo) öffentlich verfügbar. [Downloadbefehle für den KI-Server](praktikum/DATEN_HERUNTERLADEN.md) verwenden den festen Stand `6837ae4fae0d1d216612afa739c9dfefd6b277ab`. Bereiten Sie Umgebung, Modell und Daten anhand von [LEHRVORBEREITUNG.md](LEHRVORBEREITUNG.md) vor. Der vollständige kuratierte Bestand der 134 alten Klassen muss weiterhin gesondert bereitgestellt werden.

## Ablauf für 45 Minuten

Die Zeiten stammen aus [source/slides.mjs](source/slides.mjs). Der eigene Trainingslauf der Studierenden folgt nach der Vorlesung; seine Dauer wird nicht als Teil der 45 Minuten versprochen.

| Minuten | Folien | Inhalt und Schwerpunkt |
| --- | --- | --- |
| 0–4 | 1–4 | Lernziel; Dobel ohne gespeicherte Ortstafelbox und Bernbach mit falscher Klassifikation |
| 4–9 | 5–6 | Überwachtes Lernen, Gewichte, Training/Inferenz und CNN-Merkmale |
| 9–12,5 | 7–8 | Zwei Aufgaben unterscheiden: Schild lokalisieren und Bildausschnitt klassifizieren; YOLO einordnen |
| 12,5–13,5 | 9 | Datensatz mit Bildern und Labels vom Modell mit gelernten Gewichten unterscheiden |
| 13,5–20,5 | 10–14 | Modelle, Größen, RAM, SGBlur/Prolix, Plattformformate, GPU und Vorverarbeitung |
| 20,5–26 | 15–17 | Panoramax-Box und Codes; Crawler für zwei Sätze; manuelles Einsortieren und feste Gruppensplits |
| 26–31 | 18–19 | Rolle von Prolix; Hugging-Face-Pakete auf dem KI-Server herunterladen und prüfen |
| 31–33 | 20 | Fine-Tuning des vorhandenen HF-Modells |
| 33–34 | 21 | Wann der Detektor zusätzliche Boxbeispiele benötigt |
| 34–36 | 22 | Precision, Recall und F1 am erfundenen Beispiel mit zehn Tafeln berechnen |
| 36–38 | 23 | Reale Ergebnisse und gescheitertes Bestandsklassen-Gate |
| 38–39 | 24 | Derselbe Kandidat auf allen Plattformen; Exporte getrennt prüfen |
| 39–42 | 25 | 90 Sekunden Partneraustausch, 90 Sekunden gemeinsame Auflösung |
| 42–45 | 26–27 | Abgabe/Lerncheck und zwei Minuten Fragen |

Die ausführlichen Notizen und Quellen je Folie stehen in [SPRECHERNOTIZEN.md](SPRECHERNOTIZEN.md) und in den PowerPoint-Sprechernotizen.

## Begriffe am Bild erklären

Führen Sie auf Folie 2 die Bezeichnung **Bildausschnitte (Crops)** ein. Verwenden Sie danach im Gespräch „Bildausschnitte“: Der Detektor liefert eine Box, aus der das Schildbild für den Klassifikator ausgeschnitten wird.

Erklären Sie zuerst das sichtbare Problem und erst danach die Technik. In Dobel fehlt die gespeicherte Box der gelben Ortstafel; das erkannte Gefahrzeichen daneben ist ein anderes Objekt. Der gespeicherte Panoramax-Zustand ist kein neu ausgeführter Detektortest. In Bernbach wurde die Tafel lokalisiert, das alte Modell lieferte jedoch `bad`. Eine menschliche Annotation verbessert zunächst den Datenbestand; erst ein Trainingslauf verändert Gewichte.

Nutzen Sie für Folie 5 die Folge **Bild + bekannte richtige Klasse → Vorhersage → Fehler → Gewichte anpassen**. „Überwachtes Lernen“ bedeutet, dass die richtige Klasse im Trainingsbeispiel bekannt ist. Bei Inferenz bleiben die Gewichte fest. Ein hoher Softmax-Score garantiert keine richtige Vorhersage bei unbekannten Bildern.

Für Folie 6 genügen zunächst drei Begriffe: Der **Backbone** erzeugt Bildmerkmale, **Pooling** verdichtet sie, der **Klassifikationskopf** liefert einen Wert je Klasse. Die konkreten Blocknamen dienen der technischen Einordnung; vertiefen Sie Attention oder DFL in diesem Zeitbudget nicht.

## Die tatsächlichen Netze präzise einordnen

Der deutsche Panoramax-Klassifikator ist ein angepasstes **YOLO26l-cls mit 13.006.278 Parametern und 134 Klassen**. Sein RGB-Bildausschnitt misst 224 × 224 Pixel. Der geprüfte Backbone verwendet Conv-/C3k2-Blöcke und C2PSA. Seine Ausgabe mit 512 Merkmalskarten à 7 × 7 wird im Kopf durch eine 1×1-Faltung auf 1280 Kanäle gebracht und räumlich gemittelt. Die lineare Schicht bildet diese 1280 Werte auf 134 Klassen ab. Für zwei zusätzliche Ausgänge werden 2562 zusätzliche Parameter benötigt. Der Klassifikator besitzt keinen FPN/PAN-Detektionsneck.

Folie 11 nennt die Projektherkunft und verlinkt die Originale: SGBlur bedeutet **„Speedy Gonzales“ Blurring Algorithm**; Prolix ist das Panoramax-Werkzeug zur Objekterkennung und Klassifikation von **Adrien Pavie**. Eine weitergehende Namensetymologie von Prolix ist in den geprüften Projektquellen nicht dokumentiert.

Folie 8 erklärt die drei Bauteile direkt am Detektor: **Backbone** gewinnt Bildmerkmale wie Kanten und Formen; **Neck** verbindet fein und grob aufgelöste Merkmalskarten desselben Bilds; **Head** berechnet die Vorhersagen. Beim Klassifikator entfällt der Detektionsneck; sein **Classification Head** liefert einen Score je Zeichenklasse.

Der **SGBlur-YOLO11n-Detektor** hat **2.590.425 Parameter** und die drei Klassen `sign`, `plate`, `face`. Mobil verarbeitet er 1280 × 1280 Pixel. Der Backbone enthält Conv/C3k2, SPPF und C2PSA; der Detektionsneck kombiniert Merkmale auf drei Skalen. Der Kopf liefert Boxen und Objektklassenscores. NMS unterdrückt schwächer bewertete überlappende Vorschläge. Eine NMS-freie YOLO26-Detektion darf diesem YOLO11-Checkpoint nicht zugeschrieben werden.

Die Architektur wurde anhand der gespeicherten Checkpointkonfiguration und des kompilierten Core-ML-Rechengraphen geprüft. Quellen, Formen und Parameterbelege stehen in [network-architecture-evidence.json](source/network-architecture-evidence.json). Das offizielle YOLO26-Paper von Jocher et al., [arXiv:2606.03748v1](https://arxiv.org/abs/2606.03748v1), erläutert Klassifikation in Abschnitt 3.4. Das ursprüngliche [YOLO-Paper von Redmon et al.](https://arxiv.org/abs/1506.02640) beschreibt den historischen Ansatz. Für YOLO11 gibt Ultralytics kein eigenes formales Forschungspaper an; zitieren Sie die dokumentierte Software und Konfiguration.

## Modellquellen, Speicher und Plattformen unterscheiden

Prolix ist das ausführende Werkzeug beziehungsweise der Projektadapter. Die deutsche Modellquelle ist [Panoramax/classify_de_road_signs](https://huggingface.co/Panoramax/classify_de_road_signs) in Revision `5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790`. Derselbe geprüfte Checkpoint ist der Ausgangspunkt unseres Fine-Tunings auf Folie 20. Linux und die beiden mobilen Exporte verweisen ebenfalls auf diesen Ausgangscheckpoint. Der mobile Detektor stammt aus SGBlur-Revision `169451970702aca0dde9ff3106dba0f67e0b88a8`. Exakte Dateibytes und Hashes stehen in [model-inventory.json](source/model-inventory.json).

Folie 4 verlinkt das Ausgangsmodell. Unterscheiden Sie auf Folie 9 den Datensatz [Panoramax/classified_de_road_signs](https://huggingface.co/datasets/Panoramax/classified_de_road_signs) mit Bilddateien und Klassenlabels vom Modell [Panoramax/classify_de_road_signs](https://huggingface.co/Panoramax/classify_de_road_signs) mit gelernten Gewichten. Der Datensatz enthält auch Beispiele der Klassen `bad` und `other`. Für den Kurs bleiben alte Beispiele erhalten; geprüfte Ortstafeln kommen hinzu. Prüfen Sie vor der neuen Aufteilung Duplikate und gemeinsame Bildquellen.

Die Modellkarte nennt **98,6 % Accuracy als selbst berichteten Wert**. Das ist weder ein Nachweis für die dort fehlenden Ortstafelklassen noch direkt mit unserem neu aufgeteilten Prüfbestand vergleichbar. Im veröffentlichten alten Train-/Val-Bestand wurden 522 identische Bilder gefunden. Modellkarte, eigener Messwert und Freigabeentscheidung sind getrennt zu erläutern. [Geprüfte Modellkarte und Datensatzbelege](source/hf-model-card-review-2026-10-20.json).

Folie 10 trennt drei Größen: Parameterzahl, Modelldatei und aus dem Android-Code berechnete App-Puffer. Die Pufferkapazitäten betragen **34,65 MB für den Detektor** und **1,00 MB für den Klassifikator**, gerundet 35 und 1 MB. Gewichte, Interpreter-Arenen, Aktivierungen, GPU-Kopien, Kamera und Karte kommen hinzu. Diese Kapazitäten messen keinen vollständigen Modell-RAM; für iPhone gelten sie nicht.

Die Gesamtapp-Beispiele sind ebenfalls getrennt zu erläutern: Android **645,67 MB PSS** als Momentaufnahme vom 19.10.2026; iPhone **231,93 MB höchster gesampelter Physical Footprint** in einem anderen Kamera-/TSR-/Video-Lauf vom 01.10.2026. Datum, Build, Last und Messgröße unterscheiden sich. Daraus folgt keine Plattformrangfolge und kein RAM-Wert je Modell. Rohbelege stehen in [model-memory-evidence.json](source/model-memory-evidence.json).

Linux führt den PyTorch-Checkpoint aus, Android einen LiteRT-Export, iPhone ein Core-ML-Artefakt. Gleiche Quellgewichte bedeuten keine identischen Dateien oder vollständigen Pipelines: Detektorauflösung, Randzugaben und Nachverarbeitung unterscheiden sich. Der aktuelle Serveradapter klassifiziert bereits vorhandene SGBlur-Boxen; ein größeres Modell im Register belegt dessen Ausführung im Worker nicht.

Die dokumentierte Serverhardware umfasst zwei RTX A5000 mit je 24 GiB und eine RTX PRO 6000 Blackwell Max-Q mit 96 GiB. Die konkrete GPU des laufenden SGBlur-Inferenzdienstes ist nicht sicher zugeordnet; die Trainingsversuche vom 20. Oktober verwendeten nachweislich die beiden RTX A5000. Auf dem Android-Testgerät ist der Mali-G615-MC2-GPU-Delegate belegt; bei Fehlern ist ein CPU-Rückfall vorgesehen. Auf iPhone erlaubt `.all` Core ML die Wahl von CPU, Apple GPU und Neural Engine. Es beweist keine feste Operationszuordnung.

## Den Einstieg mit konkreten Befehlen verbinden

Zeigen Sie auf Folie 15 die Objektannotation und lesen Sie die Codes ausdrücklich vor: **DE:310 = Ortseingang; DE:311 = Ortsausgang**. Der Panoramax-Schlüssel lautet `osm|traffic_sign`, die Trainingslabels heißen `city:start` und `city:end`.

`crawl_panoramax.py` sammelt vorhandene Objektannotationen und erzeugt zwei ungeprüfte Eingänge: Vollbilder mit Boxvorschlägen sowie Schild-Bildausschnitte. Die Studierenden verschieben geprüfte Bildausschnitte in die Klassenordner unter `approved/classifier/`; `city__start` und `city__end` entsprechen DE:310 und DE:311. Vollständig geprüfte Detektorpakete werden als ganze Ordner nach `approved/detector/` verschoben. Das bestätigt die Prüfung aller drei Objektklassen. Fehlende Boxen müssen zunächst in Panoramax ergänzt werden; öffentlich geblurrte Bilder belegen keine Erkennung ungeblurter Gesichter. Details stehen in [SAMMELN_UND_SORTIEREN.md](praktikum/SAMMELN_UND_SORTIEREN.md).

Folie 19 zeigt den öffentlichen Hugging-Face-Link und den Download der Lernsammlung samt Prüfsummenliste. Die Lehrperson installiert die Download-CLI in `.venv-hf` getrennt von der Trainingsumgebung. Nach dem Wechsel in `praktikum/` lautet der Befehl:

```sh
.venv-hf/bin/hf download loffenauer/ws26_hspf_imo \
  packages/panoramax-studenten-2026-10-19.zip \
  SHA256SUMS.txt --type dataset \
  --revision 6837ae4fae0d1d216612afa739c9dfefd6b277ab \
  --local-dir data/downloads
```

Zeigen Sie anschließend die passende SHA-256-Zeile und die Entpackbefehle aus [DATEN_HERUNTERLADEN.md](praktikum/DATEN_HERUNTERLADEN.md). Die Lernsammlung landet unter `data/collection/`. Ein zusätzlicher Crawl ist dafür nicht erforderlich. Das kleine Demo ist eine Teilmenge dieser Sammlung und wird getrennt geöffnet. Die beiden Testkandidatenpakete bleiben unter `data/teacher-reserved/` für die Lehrperson reserviert. Die Paketdateien enthalten ungeprüfte Quellvorschläge und gehören nicht in den normalen Import oder die Modellauswahl. Der Versuch vom 20. Oktober verwendet einen gesondert dokumentierten Assistentenreview, feste Testauswahlen und einen eigenen Evaluationsmodus; die ursprünglichen Freigabefelder bleiben unverändert. [Vorgehen und Ergebnisse](TRAININGSERGEBNISSE-2026-10-20.md).

Die Lehrperson liefert zusätzlich den Bestand der 134 alten Klassen und eine CSV mit `sample_id,image_path,label,group_id`. `import_sorted_folders.py` führt diesen Bestand und die geprüften neuen Bildausschnitte zusammen. Gruppen werden vorher geprüft: gleiche physische Tafel, Fahrt und Nahe-Duplikate bleiben zusammen. Die feste Zielaufteilung beträgt **70/15/15**; ganze Gruppen können abweichende Bildanteile ergeben. Vollbilder und daraus erzeugte Bildausschnitte verwenden dieselbe Gruppenzuordnung. `prepare_dataset.py` verpackt danach den Klassifikatorsatz für die bestehenden Trainingsskripte.

Nach dem Wechsel in den vorbereiteten Ordner `praktikum/` führen die Studierenden aus:

```sh
# Zuerst Lernsammlung herunterladen, SHA-256 prüfen und entpacken.
# Danach Beispiele prüfen und in approved/ verschieben.
python import_sorted_folders.py \
  --source data/collection --output data/reviewed \
  --include-annotations data/annotations.csv --include-images data/raw/images
python prepare_dataset.py \
  --annotations data/reviewed/classifier/annotations.csv \
  --images data/reviewed/classifier/images
python train.py --epochs 20
python evaluate.py --candidate runs/versuch-01/weights/best.pt
```

Erklären Sie auf **Folie 20** den Begriff **Fine-Tuning**: „Ein bereits trainiertes Modell lernt mit passenden, beschrifteten Bildern weiter. Dabei ändern sich seine Gewichte.“ Zeigen Sie dazu die Folge **vorhandener HF-Checkpoint → geprüfte alte Schilder und neue Ortstafeln → Kandidat mit 136 Klassen**. Die gelernte Merkmalsextraktion liefert den Ausgangspunkt. Der Classification Head übernimmt die 134 alten Zeilen namens- und indexgetreu und ergänzt zwei neu initialisierte Zeilen. Im ausgeführten TSR-Lauf waren anschließend **alle Modellgewichte trainierbar**, einschließlich des Backbones. Die Übernahme alter Zeilen garantiert deshalb keine unveränderte Qualität nach dem Fine-Tuning.

Erklären Sie eine Epoche als Durchlauf durch die Trainingsbilder. Der echte Versuch lief **20 Epochen**; die Validierung wählte den Kandidaten aus **Epoche 4**. Öffnen Sie `progress.csv` und den Ergebnisbericht, ohne den Test zur Auswahl weiterer Parameter zu verwenden. Die konkreten Messwerte gehören zu Folie 23. [Ausgeführter Trainingsversuch](TRAININGSERGEBNISSE-2026-10-20.md).

Der Kandidat `best.pt` enthält ein eigenes sicheres `state_dict`- und Metadatenformat. Für den Plattformexport muss das Modell mit `model_utils.load_candidate()` aus Baselinearchitektur, Gewichten und Metadaten rekonstruiert werden; `yolo export model=best.pt` ist dafür kein fertiger Exportweg. **Core-ML-/LiteRT-Export dieses neuen Kandidaten wurde nicht getestet.**

## Den Bestandsvergleich verbindlich machen

Das Auswerteskript vergleicht Baseline und Kandidat auf **denselben zurückgehaltenen Bildern alter Klassen**. Recall und F1 jeder der 134 Bestandsklassen sowie alte Gesamtwerte dürfen nicht sinken. Bessere Ortstafelerkennung gleicht eine Regression alter Klassen nicht aus.

| Status | Bedeutung | Verhalten |
| --- | --- | --- |
| `BESTANDEN` | Alle alten Klassen sind vertreten; im festgelegten Vergleich kein Rückgang | Rückgabecode 0; nur das Bestandsklassen-Gate ist bestanden |
| `REGRESSION` | Mindestens ein verbindlicher Bestandswert sinkt | Berichte schreiben, Rückgabecode 3 |
| `UNVOLLSTAENDIG` | Für eine vollständige alte Klassenprüfung fehlen Beispiele | Berichte schreiben, Rückgabecode 3 |

Bei gleichzeitig fehlender Abdeckung und gemessener Regression hat `REGRESSION` Vorrang. Fehlende Bilder sind keine bestandene Prüfung. Öffnen Sie für Details `regression-gate.json` und `old-only-per-class.csv`. Die beiden neuen Klassen sind zusätzlich mit Support, Precision, Recall, F1 und Fehlbildern zu beurteilen. `BESTANDEN` ist keine automatische Modellfreigabe. Der dokumentierte endliche Prüfbestand begründet keine Garantie für alle zukünftigen Bilder.

Die Validierung dient der Kandidaten- und Parameterauswahl. Erst nach deren Abschluss wird der Test einmal geöffnet:

```sh
python evaluate.py --candidate runs/versuch-01/weights/best.pt \
  --split test --output reports/abschluss
```

Nach Einsicht in diesen Test werden keine weiteren Parameter anhand desselben Tests gewählt. Kennzahlen zur Klassifikation der Bildausschnitte ersetzen keinen späteren Test des Detektors und der vollständigen App-Pipeline auf unbekannten Strecken.

### Folie 22: Precision, Recall und F1 zuerst gemeinsam berechnen

Kennzeichnen Sie die zehn Beispiele ausdrücklich als **frei erfunden**. Jeder Bildausschnitt enthält genau eine Tafel; das Beispielmodell kann nur DE:310 oder DE:311 vorhersagen. Die Box ist bereits vorgegeben. Bewertet wird hier die richtige Klasse, nicht das Finden einer Box.

| Tatsächliche Klasse | Vorhersage DE:310 | Vorhersage DE:311 |
| --- | ---: | ---: |
| 6 × DE:310 Ortseingang | 4 | 2 |
| 4 × DE:311 Ortsausgang | 1 | 3 |

Für DE:310 sind vier Zuordnungen richtig, eine falsch als DE:310 gemeldet und zwei echte Ortseingänge als DE:311 eingeordnet. **Precision** teilt die richtigen Zuordnungen durch alle Vorhersagen dieser Klasse; **Recall** durch alle tatsächlich vorhandenen Beispiele dieser Klasse. **F1** verbindet beide als `2 × P × R / (P + R)`; verwenden Sie P und R dabei als Anteile zwischen null und eins. Mit Trefferzahlen entspricht das `2 × richtig / (2 × richtig + falsch gemeldet + falsch als andere Klasse eingeordnet)`.

| Betrachtete Klasse | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| DE:310 | 4/5 = 80 % | 4/6 ≈ 67 % | 8/11 ≈ 73 % |
| DE:311 | 3/5 = 60 % | 3/4 = 75 % | 6/9 ≈ 67 % |

Lassen Sie die Studierenden die Nenner fünf und vier für DE:311 an der Matrix zeigen. Die Werte werden **je Klasse** berechnet; im echten Modell zählen alle anderen Klassen als Gegenklassen. F1 ist nicht das einfache arithmetische Mittel. Erst die folgende Folie enthält die tatsächlichen Messwerte; dort bedeutet F1 0,80 entsprechend 80 %.

#### Musterlösung zur Praktikumsübung (nur für die Lehrperson)

Die [Praktikumsanleitung](praktikum/README.md#precision-recall-und-f1-verstehen) enthält zuerst dasselbe Rechenbeispiel und danach eine **5–8-minütige Übung mit veränderten Vorhersagen**. Lassen Sie die Studierenden die Übung vor der gemeinsamen Auflösung selbst bearbeiten. Auch diese Zahlen sind frei erfunden; die Übung benötigt weder einen Trainingslauf noch Zugriff auf den Abschlusstest.

| Tatsächliche Klasse | Vorhersage DE:310 | Vorhersage DE:311 | Anzahl echter Beispiele |
| --- | ---: | ---: | ---: |
| DE:310 Ortseingang | 5 | 1 | 6 |
| DE:311 Ortsausgang | 2 | 2 | 4 |
| Anzahl Vorhersagen | 7 | 3 | 10 |

**Aufgaben 1 und 2: Anzahlen und Kennzahlen.** Für DE:310 zählen fünf richtige Zuordnungen, zwei falsch als DE:310 gemeldete Ortsausgänge und ein als DE:311 eingeordneter Ortseingang. Für DE:311 zählen zwei richtige Zuordnungen, ein falsch als DE:311 gemeldeter Ortseingang und zwei als DE:310 eingeordnete Ortsausgänge.

| Klasse | Richtig | Falsch gemeldet | Echte Beispiele als andere Klasse | Precision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DE:310 | 5 | 2 | 1 | 5/7 ≈ 71,4 % | 5/6 ≈ 83,3 % | 10/13 ≈ 76,9 % |
| DE:311 | 2 | 1 | 2 | 2/3 ≈ 66,7 % | 2/4 = 50,0 % | 4/7 ≈ 57,1 % |

Rechenwege für F1 mit den ungerundeten Anzahlen:

```text
DE:310: 2 × 5 / (2 × 5 + 2 + 1) = 10/13 ≈ 0,7692
DE:311: 2 × 2 / (2 × 2 + 1 + 2) = 4/7   ≈ 0,5714
```

**Aufgabe 3: Vergleich mit dem ersten Beispiel.** Die Gesamtgenauigkeit bleibt bei `7/10 = 70 %`: vorher `4 + 3`, jetzt `5 + 2` richtige Zuordnungen. Trotzdem steigt F1 für DE:310 von etwa **72,7 % auf 76,9 %**, während F1 für DE:311 von etwa **66,7 % auf 57,1 %** sinkt. Bei DE:310 steigt Recall, aber Precision sinkt von 80 % auf etwa 71,4 %. Bei DE:311 sinkt Recall, aber Precision steigt von 60 % auf etwa 66,7 %. Das Modell meldet häufiger DE:310, siebenmal statt fünfmal. „Besser“ oder „schlechter“ muss deshalb eine Klasse und eine Kennzahl benennen.

**Aufgabe 4: Keine Freigabe aus dieser Übung ableiten.** Das Beispiel enthält nur zwei Klassen und zehn vorgegebene Bildausschnitte. Über die 134 Bestandsklassen sagt es nichts aus. Vergleichen Sie Recall und F1 von Baseline und Kandidat auf denselben geeigneten zurückgehaltenen Beispielen. Die Boxsuche im Vollbild wurde ebenfalls nicht geprüft. Kleine erfundene Zahlen sind keine Qualitätsmessung des Kursmodells. Diese Handrechnung berechnet auch keinen Status des Bestandsklassen-Gates.

Achten Sie bei der Besprechung besonders auf vertauschte Zeilen- und Spaltensummen, falsch übernommene Trefferzahlen beim Wechsel der betrachteten Klasse und vorzeitiges Runden. Precision verwendet die **Vorhersagezahl** im Nenner, Recall die **tatsächliche Beispielzahl**. F1 ist das harmonische Mittel. Ein bloßer Hinweis auf die unveränderten 70 % beantwortet Aufgabe 3 nicht.

### Folie 23: den tatsächlichen Verbesserungs-/Regressionskonflikt erklären

| Geprüfte Bildausschnitte | Ergebnis des Kandidaten | Einordnung |
| --- | --- | --- |
| DE:310 Ortseingang | 2/3 richtig; F1 **0,80** | Nur drei Beispiele, davon zwei aus einer möglichen gemeinsamen Fahrt |
| DE:311 Ortsausgang | 12/12 richtig; F1 **1,00** | Kleine, gezielt gesuchte Stichprobe |
| 3.029 alte Klassenbeispiele | Baseline **3.015**, Kandidat **3.010** richtig | F1 sinkt bei **20 Klassen**: Gate **`REGRESSION`** |

Betonen Sie: **14/15 korrekt klassifizierte Ortstafel-Bildausschnitte sind keine Modellfreigabe.** Alle 134 alten Klassen sind im retrospektiven Prüfbestand vertreten; dennoch sinken verbindliche Werte. Die Baseline könnte Teile dieses öffentlichen Korpus bereits aus ihrem ursprünglichen Training kennen. Der Vergleich untersucht Vergessen und Regression auf diesem Bestand, keine garantiert vortrainingsfreie Generalisierung. Die neuen Testlabels stammen aus dokumentiertem Assistentenreview, nicht aus menschlich freigegebener Ground Truth. Die 98,6 % der HF-Modellkarte sind ein anderer Messwert mit anderem Prüfbestand.

Trennen Sie davon den vollständigen Ablauf **Detektor → tatsächlicher Bildausschnitt → TSR**: Er erreicht **9/15** richtig erkannte und klassifizierte Ortstafeln; sechs Ziele werden bereits vom Detektor verfehlt. Unter den neun zugeordneten Detektor-Bildausschnitten tritt kein weiterer TSR-Klassenfehler auf. Dieser bekannte Zielboxvergleich belegt wegen unvollständiger Szenenannotation keine Precision/AP und keine Gesichts-/Kennzeichenqualität. Native und projizierte Ansichten werden getrennt berichtet. [Vollständige Ergebnisse und Grenzen](TRAININGSERGEBNISSE-2026-10-20.md).

## Partnerübung: Musterlösung

**A – Die Box fehlt, der manuelle Bildausschnitt funktioniert.** Prüfen Sie die Lokalisierung. Ergänzen Sie vollständig annotierte Vollbilder und messen Sie Detektor-Recall nach Schildgröße und Blickwinkel. Der manuelle Bildausschnitt umgeht die problematische erste Stufe.

**B – Die Box stimmt, aber das alte Modell meldet `bad`.** Ergänzen Sie echte Klassifikatorausgänge und trainieren Sie mit geprüften neuen und alten Bildausschnitten. Prüfen Sie Labelreihenfolge, beide Ortstafelklassen und die verbindliche Bestandsregression. `bad` pauschal auf DE:310 abzubilden würde andere verworfene Bildausschnitte ebenfalls falsch umdeuten.

**C – Guter Test der Bildausschnitte, schlechter neuer Streckenlauf.** Prüfen Sie zuerst Split-Leakage und Aufnahmebedingungen; untersuchen Sie anschließend Box-Recall, Geometrie der Bildausschnitte und Klassifikation getrennt. Eine belastbare Antwort nennt einen konkreten unabhängigen Test, bevor sie einen größeren Trainingslauf fordert.

## Abschluss und Nachweise

Die Abgabe enthält Daten-/Splitstand, Quell- und Modellhashes, Trainingskonfiguration, Kandidat und Baselinevergleich einschließlich Fehlbildern. Der Unterricht verändert keine geschützte Geschwindigkeitsreferenz-Policy. Ein erkanntes DE:311 setzt nicht automatisch 100 km/h. Plattformexporte und eine produktive Freigabe folgen als eigene Projektschritte.

Die technische CLI-Prüfung mit Ultralytics 8.4.56, einer Epoche künstlicher Farb-Bildausschnitte und CPU-Ausführung ist in [praktikum-exact-cli-smoke.json](source/praktikum-exact-cli-smoke.json) dokumentiert. Dieser frühere Funktionstest belegt Ablauf, Speichern/Laden und den nicht bestandenen unvollständigen Vergleich. Die echten GPU-Läufe mit realen Bildern und ihre Qualitätsmessungen sind separat in [TRAININGSERGEBNISSE-2026-10-20.md](TRAININGSERGEBNISSE-2026-10-20.md) dokumentiert. Die lokalen 27 Tests des damaligen CLI-Stands sind im ersten Beleg vermerkt.

Die realen Dobel-/Bernbach-Fotos stammen von **admin / Panoramax, CC BY-SA 4.0**. Die vorhandenen Screenshots dokumentieren gespeicherte Zustände; das Bernbach-Modellergebnis stammt aus dem bezeichneten historischen Experiment. Weitere Herkunftsnachweise stehen in [ASSET_CREDITS.md](../ASSET_CREDITS.md) und den Quellen der betreffenden Folien.

Die erweiterte Sammlung und Ordnerprüfung sind mit **70 lokalen Tests** sowie einem begrenzten Live-Crawl mit zwei Vollbildern und sechs ungeprüften Bildausschnitten geprüft. Der zusätzliche synthetische Ablauf verwendet alle 136 Klassen und hält Vollbild und Bildausschnitte im gleichen Split. [Prüfbeleg](source/collection-smoke-evidence.json). Die kleine Live-Sammlung ist eine Übungsreserve für die Prüfung und das Einsortieren; sie ersetzt keinen vollständigen Kursdatensatz.
