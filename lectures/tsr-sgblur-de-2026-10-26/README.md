# Bildklassifikation mit KI

## Wie verbessere ich ein vorhandenes KI-Modell?

**Montag, 26. Oktober 2026 · 45 Minuten · Deutsch · 27 Folien · Folien v9.2, Praktikum v7.4**
Prof. Dr. Raphael Volz · HSPF · Einstieg im 3. Semester ohne ML-Vorkenntnisse

- [Bearbeitbare PowerPoint mit Sprechernotizen · v9.2](output/tsr-sgblur-de-2026-10-26-v9.2.pptx)
- [PDF zur Projektion · v9.2](output/tsr-sgblur-de-2026-10-26-v9.2.pdf)
- [Sprechernotizen und Quellen je Folie](SPRECHERNOTIZEN.md)
- [Praktikum: Überblick und konkrete Befehle](PRAKTIKUM.md)
- [Praktikum: Schritt-für-Schritt-Anleitung und Code](praktikum/README.md)
- [Precision, Recall und F1: Rechenbeispiel und kurze Übung](praktikum/README.md#precision-recall-und-f1-verstehen)
- [Panoramax-Beispiele sammeln, prüfen und einsortieren](praktikum/SAMMELN_UND_SORTIEREN.md)
- [Datenpakete direkt auf den KI-Server herunterladen](praktikum/DATEN_HERUNTERLADEN.md)
- [Echte Trainings- und Testergebnisse vom 20. Oktober](TRAININGSERGEBNISSE-2026-10-20.md)
- [Messbelege, Reviews, Skripte und tatsächliche Pipeline-Bildausschnitte als ZIP](output/trainingsbelege-2026-10-20.zip)
- [Praktikum mit Kennzahlenübung und servergeprüfter Downloadanleitung als ZIP herunterladen](output/praktikum-de310-de311-v7.4.zip)
- [Kleiner Panoramax-Beispielsatz zum Prüfen und Einsortieren](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/6837ae4fae0d1d216612afa739c9dfefd6b277ab/packages/panoramax-beispiele-v6.zip?download=true)
- [Alle vier Datenpakete öffentlich auf Hugging Face herunterladen](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo)
- [Publikationsbeleg: öffentlicher Zugriff und SHA-256 geprüft](source/huggingface-publication.json)
- [Große Sammlung vom 19.10.: 100 Vollbilder und 214 Bildausschnitte](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/6837ae4fae0d1d216612afa739c9dfefd6b277ab/packages/panoramax-studenten-2026-10-19.zip?download=true)
- [Sichtungsübersicht der großen Sammlung](output/panoramax-studenten-2026-10-19-crops.csv)
- [Zusätzliche Testkandidaten vom 20.10.: acht neue Sequenzen](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/6837ae4fae0d1d216612afa739c9dfefd6b277ab/packages/panoramax-testkandidaten-2026-10-20.zip?download=true)
- [Status und Grenzen des zusätzlichen Testbestands](output/panoramax-testkandidaten-2026-10-20-bericht.json)
- [Externe Testkandidaten: 15 Zielansichten aus öffentlichen Instanzen](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo/resolve/6837ae4fae0d1d216612afa739c9dfefd6b277ab/packages/panoramax-externe-testkandidaten-2026-10-20.zip?download=true)
- [Sichtungsanleitung und Grenzen der externen Kandidaten](output/panoramax-externe-testkandidaten-2026-10-20-hinweise.txt)
- [Arbeitsliste der externen Ortstafel-Bildausschnitte](output/panoramax-externe-testkandidaten-2026-10-20-crops.csv)
- [Lehrvorbereitung: Kursumgebung, Modell und Daten bereitstellen](LEHRVORBEREITUNG.md)

Die Vorlesung erklärt überwachtes Lernen, CNNs und YOLO anhand eines konkreten Modellversuchs: **Ortseingang `DE:310`** und **Ortsausgang `DE:311`** erkennen. Folie 2 führt **Bildausschnitte (Crops)** ein. Der Kurs unterscheidet fehlende Detektorboxen von falschen Klassen eines Schild-Bildausschnitts und arbeitet ausschließlich mit Vollbildboxen und diesen Ausschnitten. Architektur, Modellquellen, Gewichte, Dateigrößen und Speicherbelege sowie die Inferenz auf Linux/Server, Android und iPhone werden am Projekt erläutert.

Folie 4 verlinkt das Ausgangsmodell; Folie 9 unterscheidet den Datensatz [Panoramax/classified_de_road_signs](https://huggingface.co/datasets/Panoramax/classified_de_road_signs) mit Bildern und Klassenlabels vom Modell [Panoramax/classify_de_road_signs](https://huggingface.co/Panoramax/classify_de_road_signs) mit gelernten Gewichten. Folie 20 erklärt daran **Fine-Tuning**: vortrainierte Gewichte mit beschrifteten alten und neuen Bildern weiterlernen lassen, den Classification Head auf 136 Klassen erweitern und den Kandidaten anhand der Validierung auswählen. [Prüfung der Modellkarte und des verwendeten Checkpoints](source/hf-model-card-review-2026-10-20.json).

Vor den echten Ergebnissen erklärt Folie 22 **Precision, Recall und F1** mit einem ausdrücklich erfundenen Rechenbeispiel mit zehn Bildausschnitten: sechs echte DE:310-Tafeln werden viermal als DE:310 und zweimal als DE:311 eingeordnet; vier echte DE:311-Tafeln einmal als DE:310 und dreimal als DE:311. Daraus folgen für DE:310 Precision 4/5, Recall 4/6 und F1 8/11, für DE:311 entsprechend 3/5, 3/4 und 6/9. Die Werte beziehen sich je Klasse auf vorgegebene Bildausschnitte, nicht auf das Finden von Boxen. Folie 23 zeigt anschließend den tatsächlich gemessenen TSR-Versuch samt gescheitertem Bestandsklassen-Gate.

Der [Crawler](praktikum/crawl_panoramax.py) sammelt vorhandene Panoramax-Annotationen in zwei getrennten Eingängen: Vollbilder mit Boxvorschlägen für den Detektor und Schild-Bildausschnitte für den Klassifikator. Die Studierenden prüfen und verschieben Beispiele in die jeweiligen Freigabeordner. Der [Importer](praktikum/import_sorted_folders.py) übernimmt die korrigierten Klassen, prüft Dateien und Herkunft und teilt beide Sätze mit denselben Bildgruppen in Training, Validierung und Test auf.

Die praktische Umsetzung enthält ausführbare [Datenvorbereitung](praktikum/prepare_dataset.py), [Training](praktikum/train.py) und [Evaluation](praktikum/evaluate.py). Der deutsche Klassifikator wird mit fester Klassenreihenfolge von **134 auf 136 Klassen** erweitert. Der Vergleich weist Verbesserungen bei den neuen Klassen und Regressionen jeder Bestandsklasse getrennt aus. Panoramax-Annotationen verändern zunächst die Daten; die Modellgewichte ändern sich beim Training.

Folie 19 und die [Downloadanleitung](praktikum/DATEN_HERUNTERLADEN.md) zeigen die konkreten Befehle für den öffentlichen Hugging-Face-Datensatz. Die feste Revision `6837ae4fae0d1d216612afa739c9dfefd6b277ab`, eine separate Download-CLI, gezielte SHA-256-Prüfungen und die tatsächlichen Archivpfade halten den Einstieg reproduzierbar. Die Lernsammlung landet unter `data/collection/`; die beiden zusätzlichen Testkandidatenpakete bleiben unter `data/teacher-reserved/` gesondert reserviert.

## Voraussetzungen und geprüfter Stand

Am **20. Oktober 2026** wurden beide Modelle auf den RTX-A5000-GPUs des KI-Servers tatsächlich trainiert und ausgewertet. TSR klassifiziert 14/15 geprüfte Ortstafel-Bildausschnitte richtig; der F1 sinkt jedoch bei 20 der 134 Bestandsklassen, sodass der Kandidat das Bestandsklassen-Gate nicht besteht. Die vollständige Kette aus SGBlur-Box und TSR-Klasse erkennt 9/15 Ortstafeln. Für SGBlur wurde wegen unvollständiger Vollbildannotation nur der Schild-Ausgang angepasst; Precision/mAP und Qualität auf unverpixelten Gesichtern/Kennzeichen bleiben ungeprüft. [Ergebnisse, Methodik und Artefakte](TRAININGSERGEBNISSE-2026-10-20.md).

Der **Dozent stellt Kursumgebung, GPU-Zugang, den geprüften Modellcheckpoint und kuratierte Bildausschnitte der 134 Bestandsklassen mit Labels und Gruppenkennungen bereit**. Diese Dateien sind nicht Bestandteil des neuen Praktikumsordners. Die Studierenden ergänzen geprüfte Ortstafel-Bildausschnitte. Die [Lehrvorbereitung](LEHRVORBEREITUNG.md) und die [Praktikumsanleitung](praktikum/README.md) machen diese Voraussetzung konkret. Der Dozent verwahrt Zeitplan und Übungslösungen im lokalen Dozentenleitfaden.

Die Downloadanleitung wurde am **20. Oktober 2026 als `raphael` auf `wingki01` mit Python 3.12.3** vollständig ausgeführt: frische CLI-Installation, alle vier Originalpakete, zusätzlicher HTTPS-Download, SHA-256-/ZIP-Prüfungen, Entpackpfade und Wiederholschutz. Der erste Versuch fand eine fehlende `click`-Abhängigkeit. Die korrigierte Anleitung pinnt deshalb gemeinsam `huggingface_hub==1.10.2`, `typer==0.24.1` und `click==8.3.2`; der anschließende frische Serverlauf bestand. [Server-Prüfbeleg](source/ai-server-download-test-2026-10-20.json). Dies prüft den Datenzugang und die Ordnerstruktur, keine Modellqualität.

Die erweiterte lokale Suite mit **70 automatisierten Tests** prüft Datenaufteilung, Training-/Bewertungsverträge sowie Crawler und Ordnerimport. Der Sammelablauf wurde außerdem mit zwei öffentlichen Fotos der eigenen Instanz geprüft: **2 Vollbildpakete und 6 ungeprüfte Schild-Bildausschnitte**. Ein synthetischer Durchlauf mit allen 136 Klassen prüft Crawler → Verschieben → Import → Datenvorbereitung; Vollbild und Bildausschnitte bleiben im selben Split. [Sammel- und Sortierprüfbeleg](source/collection-smoke-evidence.json). Ein **synthetischer CPU-Probelauf mit Ultralytics 8.4.56** führte die tatsächlichen Trainings- und Auswertungsbefehle aus und prüfte auch den erwarteten nicht bestandenen Vergleich bei unvollständiger Bestandsabdeckung. [Prüfbeleg und Grenzen](source/praktikum-exact-cli-smoke.json). Das ist ein Funktionstest mit synthetischen Bildern, keine Qualitätsbewertung echter Ortstafeln, kein GPU-Benchmark und keine mobile Freigabe.

Technischer Quellenstand: **19. Oktober 2026**. Dokumentierte Geräte-/Servermessungen sind mit ihrem jeweiligen Umfang gekennzeichnet. Prolix-Quellen wurden am gepinnten Deploymentstand untersucht; neuere Upstream-Beispiele werden davon unterschieden. Die ältere Einführungsvorlesung bleibt erhalten. Das frühere ausführliche Praktikumsblatt mit Pseudocode ist unter `.build/v2/PRAKTIKUM-v2.md` gesichert; für den Kurs gilt die aktuelle Anfängeranleitung.

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
Die aktuelle Folienfassung v9.1, das Praktikum v7.3 und die kleine Ausgangs-PowerPoint
v8 für den erneuten Export liegen im Repository. Der bestehende
[Prüfbeleg der finalen PowerPoint](source/presentation-validation-v9.1.json) gehört
zur unveränderten Datei. Die vier Datenarchive werden über die oben gepinnten
Hugging-Face-Downloads bezogen; ihre Prüfsummen stehen im Publikationsbeleg.
Ältere Exporte und lokale Archivkopien bleiben erhalten, werden aber nicht in
Git dupliziert. Ihre bisherigen Prüfsummen sind unter
[OUTPUT-HISTORY-SHA256SUMS.txt](source/OUTPUT-HISTORY-SHA256SUMS.txt) dokumentiert.

Die größere ungeprüfte Sammlung enthält 100 Vollbilder aus 27 Sequenzen und 214 Schild-Bildausschnitte, darunter nach vorhandenen Annotationen 49 DE:310- und 21 DE:311-Bildausschnitte. Die 136 Klassenordner bleiben leer für das manuelle Einsortieren. [Sammlungsbericht](output/panoramax-studenten-2026-10-19-bericht.json). Unter den unveränderten Sequenzgruppen und dem bisherigen Seed besteht noch keine Ortstafel-Testabdeckung; vor dem Training sind gleiche physische Tafeln zu gruppieren und weitere unabhängige Testgruppen zu ergänzen.

Die ergänzende Suche vom **20. Oktober** sichert **39 annotierte HD-Vollbilder und 77 Bildausschnitte aus acht weiteren Sequenzen** sowie die vollständigen **246 SD-Bilder dieser Sequenzen** mit 20 Kontaktbögen. Die HD-Bilder sind eine Teilmenge dieser 246 Aufnahmen. Bild-/Sequenz-IDs und Bild-/Ausschnitt-Hashes überschneiden sich nicht mit der bisherigen Sammlung; das belegt allein noch keine unabhängigen physischen Tafeln. Die Sichtung findet einen vollständigen neuen Ortseingangs-Bildausschnitt „Birkenfeld“, aber **keine zusätzliche eindeutige DE:311-Tafel**. Der getrennte Bestand bleibt deshalb ungeprüft für einen späteren Abschlusstest reserviert; er ist noch kein belastbarer Test beider Ortstafelklassen. Verwenden Sie ihn nicht zur Modellauswahl oder mit der normalen 70/15/15-Aufteilung. Vor einer Auswertung sind menschliche Klassen-/Boxfreigabe, Standortabgleich und ein gesonderter Testexport erforderlich; der bisherige Evaluator bindet Kandidaten an ihr ursprüngliches Datensatzmanifest. Das Gate der 134 Bestandsklassen bleibt zusätzlich notwendig.

Die anschließend autorisierte Erweiterung auf öffentliche Instanzen ergänzt **15 Zielansichten aus OpenStreetMap France, Ulm und Fulda**: **zwei visuelle DE:310-Vorschläge und 13 DE:311-Vorschläge**. Mehrere Ansichten zeigen dieselbe Tafel; die beiden Ortseingangsstandorte könnten zur selben Fahrt gehören. Es sind noch keine menschlich freigegebenen Testfälle. Originaltags wie `FR:EB20` oder `yes` bleiben erhalten; vorgeschlagene Klassen und ergänzte Boxen stehen separat. Für vier 360°-Quellen sind nachvollziehbare Perspektivprojektionen samt Mathetests enthalten; wegen der anhand der Zielbox gewählten Blickrichtung sind diese getrennt von nativen 2D-Bildern auszuwerten. Der Bestand enthält Bildausschnitte für TSR und Vollansichten mit Boxvorschlägen für SGBlur, leere Sortierordner, Herkunft, Prüfsummen und Arbeitslisten. Die zusätzliche Ortseingangsabdeckung ist weiterhin klein. [Sammlungsbericht](output/panoramax-externe-testkandidaten-2026-10-20-bericht.json).
