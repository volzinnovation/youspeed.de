# Bildklassifikation mit KI

## Wie verbessere ich ein vorhandenes KI-Modell?

**Montag, 26. Oktober 2026 · 45 Minuten · Deutsch · 28 Folien · Folien v15, Praktikum v7.6**

Aktuelle Dateien: [Praktikum v7.6](output/praktikum-de310-de311-v7.6.zip) · [PowerPoint v15](output/tsr-sgblur-de-2026-10-26-v15.pptx) · [PDF v15](output/tsr-sgblur-de-2026-10-26-v15.pdf).
Prof. Dr. Raphael Volz · HSPF · Einstieg im 3. Semester ohne ML-Vorkenntnisse

Die Vorlesung erklärt überwachtes Lernen, CNNs und YOLO anhand eines konkreten Modellversuchs: **Ortseingang `DE:310`** und **Ortsausgang `DE:311`** erkennen. Folie 2 führt **Bildausschnitte (Crops)** ein. Der Kurs unterscheidet fehlende Detektorboxen von falschen Klassen eines Schild-Bildausschnitts und arbeitet ausschließlich mit Vollbildboxen und diesen Ausschnitten. Architektur, Modellquellen, Gewichte, Dateigrößen und Speicherbelege sowie die Inferenz auf Linux/Server, Android und iPhone werden am Projekt erläutert.

Folie 4 verlinkt das Ausgangsmodell; Folie 9 unterscheidet den Datensatz [Panoramax/classified_de_road_signs](https://huggingface.co/datasets/Panoramax/classified_de_road_signs) mit Bildern und Klassenlabels vom Modell [Panoramax/classify_de_road_signs](https://huggingface.co/Panoramax/classify_de_road_signs) mit gelernten Gewichten. Folie 21 verlinkt den ursprünglichen [SGBlur-YOLO11n-Checkpoint](https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/models/yolo11n_panoramax.pt) als `models/detector-baseline.pt`. Folie 22 erklärt am Panoramax-Klassifikator **Fine-Tuning**: vortrainierte Gewichte mit beschrifteten alten und neuen Bildern weiterlernen lassen, den Classification Head auf 136 Klassen erweitern und den Kandidaten anhand der Validierung auswählen. [Prüfung der Modellkarte und des verwendeten Checkpoints](source/hf-model-card-review-2026-10-20.json).

Folie 23 erklärt **Precision, Recall und F1** mit einem ausdrücklich erfundenen Rechenbeispiel mit zehn Bildausschnitten: sechs echte DE:310-Tafeln werden viermal als DE:310 und zweimal als DE:311 eingeordnet; vier echte DE:311-Tafeln einmal als DE:310 und dreimal als DE:311. Daraus folgen für DE:310 Precision 4/5, Recall 4/6 und F1 8/11, für DE:311 entsprechend 3/5, 3/4 und 6/9. Die Werte beziehen sich je Klasse auf vorgegebene Bildausschnitte, nicht auf das Finden von Boxen. Folie 24 beschreibt die eigene Auswertung der Studierenden für neue und bestehende Klassen.

Der [Crawler](praktikum/crawl_panoramax.py) sammelt vorhandene Panoramax-Annotationen in zwei getrennten Eingängen: Vollbilder mit Boxvorschlägen für den Detektor und Schild-Bildausschnitte für den Klassifikator. Die Studierenden prüfen und verschieben Beispiele in die jeweiligen Freigabeordner. Der [Importer](praktikum/import_sorted_folders.py) übernimmt die korrigierten Klassen, prüft Dateien und Herkunft und teilt beide Sätze mit denselben Bildgruppen in Training, Validierung und Test auf.

Die praktische Umsetzung enthält ausführbare [Datenvorbereitung](praktikum/prepare_dataset.py), [Training](praktikum/train.py) und [Evaluation](praktikum/evaluate.py). Der deutsche Klassifikator wird mit fester Klassenreihenfolge von **134 auf 136 Klassen** erweitert. Der Vergleich weist Verbesserungen bei den neuen Klassen und Regressionen jeder Bestandsklasse getrennt aus. Panoramax-Annotationen verändern zunächst die Daten; die Modellgewichte ändern sich beim Training.

Folie 20 und die [Downloadanleitung](praktikum/DATEN_HERUNTERLADEN.md) zeigen die konkreten Befehle für den öffentlichen Hugging-Face-Datensatz. Die feste Revision `e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8`, eine separate Download-CLI, gezielte SHA-256-Prüfungen und die tatsächlichen Archivpfade halten den Einstieg reproduzierbar. Datensatz 1 landet unter `data/collection/`, die beiden MobiData-Archive unter `data/collection-mobidata-bw/` und `data/collection-mobidata-bw-additions/`; die beiden zusätzlichen Testkandidatenpakete bleiben unter `data/teacher-reserved/` gesondert reserviert.

Folie 11 zeigt den **YOLO26s-Dashcam-Vergleich** auf drei archivierten Fahrten: 31:47 Minuten, 3.814 Eingaben und 65 vorab festgelegte Prüfbilder mit 48 durch einen Assistenten annotierten Schildinstanzen. YOLO11n findet 17/48, der kompatible YOLO26s-Zweig 14/48; es gibt 1 beziehungsweise 0 bewertete Fehlvorschläge. Die Mac-CPU-Mediane betragen 68 und 128 ms. Das ist keine unabhängige menschliche Annotation, keine App-Fehlalarmrate und keine Telefonmessung. Die Apps behalten YOLO11n. Folien 10 und 15 beschreiben die aktuelle **1024 × 1024-Mobilpipeline**; die Trainings- und Testauswertung führen die Studierenden selbst durch. [Videoversuch und Grenzen](../../docs/SGBLUR_YOLO26_DASHCAM_REPLAY_2026-10-20.md), [Messbelege](../../docs/sgblur-yolo26-dashcam-2026-10-20.evidence.json), [Checkpoint- und Exportprüfung](../../docs/SGBLUR_YOLO26_CANDIDATE_2026-10-20.md).

## Voraussetzungen und geprüfter Stand

Der **Dozent stellt Kursumgebung, GPU-Zugang, den geprüften Modellcheckpoint und kuratierte Bildausschnitte der 134 Bestandsklassen mit Labels und Gruppenkennungen bereit**. Diese Dateien sind nicht Bestandteil des neuen Praktikumsordners. Die Studierenden ergänzen geprüfte Ortstafel-Bildausschnitte. Die [Lehrvorbereitung](LEHRVORBEREITUNG.md) und die [Praktikumsanleitung](praktikum/README.md) machen diese Voraussetzung konkret. Der Dozent verwahrt Zeitplan und Übungslösungen im lokalen Dozentenleitfaden.

Die Downloadanleitung wurde am **20. Oktober 2026 als `raphael` auf `wingki01` mit Python 3.12.3** vollständig ausgeführt: frische CLI-Installation, alle vier Originalpakete, zusätzlicher HTTPS-Download, SHA-256-/ZIP-Prüfungen, Entpackpfade und Wiederholschutz. Der erste Versuch fand eine fehlende `click`-Abhängigkeit. Die korrigierte Anleitung pinnt deshalb gemeinsam `huggingface_hub==1.10.2`, `typer==0.24.1` und `click==8.3.2`; der anschließende frische Serverlauf bestand. [Server-Prüfbeleg](source/ai-server-download-test-2026-10-20.json). Dies prüft den Datenzugang und die Ordnerstruktur, keine Modellqualität.

Die erweiterte lokale Suite mit **70 automatisierten Tests** prüft Datenaufteilung, Training-/Bewertungsverträge sowie Crawler und Ordnerimport. Der Sammelablauf wurde außerdem mit zwei öffentlichen Fotos der eigenen Instanz geprüft: **2 Vollbildpakete und 6 ungeprüfte Schild-Bildausschnitte**. Ein synthetischer Durchlauf mit allen 136 Klassen prüft Crawler → Verschieben → Import → Datenvorbereitung; Vollbild und Bildausschnitte bleiben im selben Split. [Sammel- und Sortierprüfbeleg](source/collection-smoke-evidence.json). Ein **synthetischer CPU-Probelauf mit Ultralytics 8.4.56** führte die tatsächlichen Trainings- und Auswertungsbefehle aus und prüfte auch den erwarteten nicht bestandenen Vergleich bei unvollständiger Bestandsabdeckung. [Prüfbeleg und Grenzen](source/praktikum-exact-cli-smoke.json). Das ist ein Funktionstest mit synthetischen Bildern, keine Qualitätsbewertung echter Ortstafeln, kein GPU-Benchmark und keine mobile Freigabe.

Technischer Quellenstand: **19. Oktober 2026**, ergänzt am **20. Oktober** um die aktuelle 1024er Mobilpipeline und den YOLO26s-Vergleich. Dokumentierte Geräte-/Servermessungen sind mit ihrem jeweiligen Umfang gekennzeichnet. Prolix-Quellen wurden am gepinnten Deploymentstand untersucht; neuere Upstream-Beispiele werden davon unterschieden. Die ältere Einführungsvorlesung bleibt erhalten. Das frühere ausführliche Praktikumsblatt mit Pseudocode ist unter `.build/v2/PRAKTIKUM-v2.md` gesichert; für den Kurs gilt die aktuelle Anfängeranleitung.

## Quellen und erneuter Export

[slides.mjs](source/slides.mjs) enthält Inhalte, Zeitbudget und Quellen; [author.mjs](source/author.mjs) die bearbeitbaren Layouts. [build-local.mjs](source/build-local.mjs) erstellt die PowerPoint mit dem gebündelten Node-/Artifact-Tool-Laufzeitpfad, [render-pdf.py](source/render-pdf.py) die PDF aus den final gerenderten Folienbildern. Die PowerPoint enthält bearbeitbare Texte und Tabellen; die PDF bewahrt die geprüfte Darstellung. Ein neuer finaler Dateiname erhält frühere Fassungen.

Die fachlichen Belege sind getrennt nach Aussage abgelegt:

- [Modellinventar](source/model-inventory.json): Artefakte, Quellen, Revisionen und Laufzeitformate.
- [Gezählte Modellparameter](source/model-weights-evidence.json): echte Parameterzahlen und Gewichtsbytes.
- [Architekturbelege](source/network-architecture-evidence.json): tatsächlicher Klassifikationskopf, Detektionsarchitektur und Forschungsquellen.
- [Speicherbelege](source/model-memory-evidence.json): berechnete Android-Puffer und gemessene Gesamtapp-Werte mit ihren Grenzen.
- [Prolix-Quellenprüfung](source/prolix-source-study.md): tatsächliche CLI-Rollen und Einrichtung.
- [Dobel-Bildbeleg](source/panoramax-dobel-965b93dc-evidence.json): fehlende gespeicherte Ortstafelbox gegenüber dem Bernbach-Klassifikationsfehler.

Die Prüfsummen der versionierten Lieferdateien stehen in [SHA256SUMS.txt](output/SHA256SUMS.txt).
Die aktuelle Folienfassung v15 und das Praktikum v7.6 enthalten den vollständigen Lerndownload. Für den erneuten Export dient die bereinigte [Vorlage](source/lecture-template.pptx). Die sechs Datenarchive werden über Hugging Face bezogen; **drei davon bilden die Lernsammlung mit 220 Vollbildern und 334 Crops**. [Publikationsbeleg](source/huggingface-learning-collection-publication.json).

Die größere ungeprüfte Sammlung enthält 100 Vollbilder aus 27 Sequenzen und 214 Schild-Bildausschnitte, darunter nach vorhandenen Annotationen 49 DE:310- und 21 DE:311-Bildausschnitte. Die 136 Klassenordner bleiben leer für das manuelle Einsortieren. [Sammlungsbericht](output/panoramax-studenten-2026-10-19-bericht.json). Unter den unveränderten Sequenzgruppen und dem bisherigen Seed besteht noch keine Ortstafel-Testabdeckung; vor dem Training sind gleiche physische Tafeln zu gruppieren und weitere unabhängige Testgruppen zu ergänzen.

Die ergänzende Suche vom **20. Oktober** sichert **39 annotierte HD-Vollbilder und 77 Bildausschnitte aus acht weiteren Sequenzen** sowie die vollständigen **246 SD-Bilder dieser Sequenzen** mit 20 Kontaktbögen. Die HD-Bilder sind eine Teilmenge dieser 246 Aufnahmen. Bild-/Sequenz-IDs und Bild-/Ausschnitt-Hashes überschneiden sich nicht mit der bisherigen Sammlung; das belegt allein noch keine unabhängigen physischen Tafeln. Die Sichtung findet einen vollständigen neuen Ortseingangs-Bildausschnitt „Birkenfeld“, aber **keine zusätzliche eindeutige DE:311-Tafel**. Der getrennte Bestand bleibt deshalb ungeprüft für einen späteren Abschlusstest reserviert; er ist noch kein belastbarer Test beider Ortstafelklassen. Verwenden Sie ihn nicht zur Modellauswahl oder mit der normalen 70/15/15-Aufteilung. Vor einer Auswertung sind menschliche Klassen-/Boxfreigabe, Standortabgleich und ein gesonderter Testexport erforderlich; der bisherige Evaluator bindet Kandidaten an ihr ursprüngliches Datensatzmanifest. Das Gate der 134 Bestandsklassen bleibt zusätzlich notwendig.

Die anschließend autorisierte Erweiterung auf öffentliche Instanzen ergänzt **15 Zielansichten aus OpenStreetMap France, Ulm und Fulda**: **zwei visuelle DE:310-Vorschläge und 13 DE:311-Vorschläge**. Mehrere Ansichten zeigen dieselbe Tafel; die beiden Ortseingangsstandorte könnten zur selben Fahrt gehören. Es sind noch keine menschlich freigegebenen Testfälle. Originaltags wie `FR:EB20` oder `yes` bleiben erhalten; vorgeschlagene Klassen und ergänzte Boxen stehen separat. Für vier 360°-Quellen sind nachvollziehbare Perspektivprojektionen samt Mathetests enthalten; wegen der anhand der Zielbox gewählten Blickrichtung sind diese getrennt von nativen 2D-Bildern auszuwerten. Der Bestand enthält Bildausschnitte für TSR und Vollansichten mit Boxvorschlägen für SGBlur, leere Sortierordner, Herkunft, Prüfsummen und Arbeitslisten. Die zusätzliche Ortseingangsabdeckung ist weiterhin klein. [Sammlungsbericht](output/panoramax-externe-testkandidaten-2026-10-20-bericht.json).

Die MobiData-BW-gestützte Suche ergänzt einen getrennten **explorativen
Sichtungseingang mit 13 neuen Vollbildern und 13 Crops aus 13 Sequenzen**:
sieben visuelle DE:310- und sechs DE:311-Vorschläge. Diese erste Auswahl ist
vollständig im [veröffentlichten v2-Paket](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8/packages/panoramax-mobidata-bw-review-2026-10-20-v2.zip?download=true)
enthalten, einschließlich Original-JPEGs, PNG-Crops, Zielboxvorschlägen, Arbeitslisten und Herkunft.
Prüfen Sie die sichtbare Schildseite: Zwei Katasterzuordnungen betreffen die
entgegengesetzte Klasse. Zwölf Ziele haben keine gespeicherte Zielbox, eines nur
`traffic_sign=yes`. SGBlur-YOLO11n findet in diesem ausgewählten Review zwei von
13 Zielboxen; dies ist keine Recall-Messung des Gesamtbestands. Alle Freigaben
bleiben ausstehend; dieser bereits mit der Baseline gesichtete Bestand gehört
nicht in den reservierten Blindtest. [Lieferbericht](source/mobidata-bw-review-2026-10-20/delivery-report.json),
[Sichtungshinweise](source/mobidata-bw-review-2026-10-20/BITTE_ZUERST_LESEN.txt).

**MobiData-Grundbestand: [MobiData-BW-Review v2](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8/packages/panoramax-mobidata-bw-review-2026-10-20-v2.zip?download=true)**
mit **57 Original-Vollbildern und 57 Crops** (37 DE:310, 20 DE:311) aus 53
Sequenzen. Der gezielte 10-m-Abgleich ergänzt **44 neue Zielansichten**:
30 DE:310 und 14 DE:311. Dafür wurden alle 2.730 Katastereinträge der Kohorte
abgeglichen, 180 neue Ansichten gesichtet und 53 HD-Bilder mit dem festen
YOLO11n-Replay geprüft. Unter den 44 neuen Zielvorschlägen fehlen 41 gespeicherte
Zielboxen, zwei Klassen bleiben `yes`, und eine passende DE:310-Box trägt
`FR:C50` mit Score 0,92. Die nachgelagerte französische Klassifikation und der
SGBlur-Detektor werden getrennt ausgewiesen. Der lokale Replay verfehlt 37 der
44 neuen Zielvorschläge; dies ist eine gezielte Fehlersuche, keine Recall-Messung.
Öffnen Sie nach dem Entpacken `SICHTUNG.html`; Originalbilder, Überlagerungen,
Arbeitslisten und Quellen sind direkt erreichbar. Alle Freigaben bleiben
ausstehend. [Suchbericht](source/mobidata-bw-review-2026-10-20-v2/search-summary.json),
[Lieferbericht](source/mobidata-bw-review-2026-10-20-v2/delivery-report.json),
[Sichtungshinweise](source/mobidata-bw-review-2026-10-20-v2/BITTE_ZUERST_LESEN.txt).

Die weitere [veröffentlichte MobiData-Ergänzung](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8/packages/panoramax-mobidata-bw-review-2026-10-20-additions.zip?download=true)
enthält **63 zusätzliche Original-Vollbilder und 63 Crops**: 58 visuelle
DE:310-Vorschläge und fünf DE:311-Vorschläge aus 63 neuen Sequenzen. Zusammen
mit v2 sind das **120 Crop-/Vollbildpaare** (95 DE:310, 25 DE:311).
Hierfür wurden 360 zusätzliche Vorschauansichten aus 156 Gemeinden anhand von
Farbregionen gesichtet, 80 HD-Originale geprüft und 17 Kandidaten ausgeschlossen.
Der abschließende Abgleich fand acht bereits früher gesichtete Sequenzen in der
Vorschauauswahl; ein sonst geeigneter HD-Kandidat wurde deshalb entfernt.
Alle 63 behaltenen Sequenzen sind neu gegenüber dem dokumentierten Suchbestand.
Bei 62 Zielvorschlägen fehlt eine passende gespeicherte Panoramax-Schildbox;
ein Ziel ist nur als `yes` annotiert. 25 sichtbare Schildseiten weichen von der
Katasterklasse ab. Das sind Review-Hinweise; ein aktueller SGBlur-Fehler ist damit
nicht nachgewiesen. Es wurde kein Modell trainiert oder lokal ausgewertet.
Die 2.730 Einträge bleiben eine räumliche Suchkohorte und sind weiterhin nicht
vollständig visuell geprüft. Öffnen Sie die eigene `SICHTUNG.html` der Ergänzung;
alle Freigaben bleiben ausstehend. Die Studentenanleitung lädt beide MobiData-Archive zusammen mit Datensatz 1
am festen HF-Stand `e74fc1564aae8f74bc4cca0e86baf7cfd612a6c8`: **334 Crops und 220 Vollbilder**,
darunter **190 Ortstafel-Kandidaten (144 DE:310, 46 DE:311)**. [Suchbericht](source/mobidata-bw-review-2026-10-20-additions/search-summary.json),
[Herkunft und Review](source/mobidata-bw-review-2026-10-20-additions/BITTE_ZUERST_LESEN.txt).
