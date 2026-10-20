# Training und Evaluation von TSR und SGBlur

**20. Oktober 2026 · Bildklassifikation mit KI · explorativer Lehrversuch**

Beide Trainingsläufe mit echten Bildern sind auf `wingki01` abgeschlossen. **TSR klassifiziert 14 von 15 zurückgehaltenen Ortstafel-Crops richtig, besteht aber den Vergleich der 134 Bestandsklassen nicht:** Bei 20 Klassen sinkt der F1-Wert. SGBlur findet mehr der bekannten Zielboxen. Die vollständige Kette aus Box-Erkennung und Klassifikation erkennt **9 von 15 Ortstafeln** korrekt. Die Kandidaten sind als Offline-Artefakte gespeichert.

## Datenprüfung und getrennte Aufgaben

Alle **214 Crops der Lernsammlung** wurden visuell durch KI-Assistenten geprüft: **188 plausible Klassenzuordnungen, 26 Ausschlüsse** wegen Bildqualität, unklarer Taxonomie oder redundanter Ansichten. Hinzu kommen die gesichteten 77 Crops des zusätzlichen eigenen Bestands und 15 externe Ansichten. Das ist ein dokumentierter Assistentenreview, keine menschlich freigegebene Ground Truth. Originalbilder, Quelltags und ursprüngliche Freigabefelder bleiben unverändert. Die Althof-Klarstellung unterscheidet zwei Tafeln derselben Ortsgrenze von tatsächlich überlappenden Crop-Annotationen. [Gesamtreview](source/real-training-2026-10-20/review-learning/assistant-review-all.csv), [Prüfbericht](source/real-training-2026-10-20/review-learning/review-audit.json), [Klarstellung](source/real-training-2026-10-20/review-learning/city-review-clarification.json).

Für TSR wurden vor der Ergebnissichtung **38 Ortstafel-Crops zum Training** festgelegt, davon 28 `city:start` und 10 `city:end`. **Acht weitere Crops dienen der Validierung**, davon fünf Start und drei Ende. Ganze Fahrttage und wiederholt aufgenommene Standorte wurden konservativ verbunden: drei Routengruppen im Training, eine andere Gruppe in der Validierung. Aufnahmen vom 14. Oktober und damit räumlich verbundene Aufnahmen vom 17. Oktober bleiben reserviert. Es wurde kein Seed gewechselt, um eine günstigere Aufteilung zu erzeugen. [Feste Auswahl](source/real-training-2026-10-20/review-learning/city-train-val.json).

Für den getrennten Abschlusstest gelten zwei Umfänge:

| Aufgabe | Vorab festgelegte Zielbeispiele | Aussage |
|---|---:|---|
| TSR: Cropklasse | **42:** 15 Ortstafeln, 27 alte Klassenbeispiele | Drei Ortseingänge und zwölf Ortsausgänge; fünf unklare oder nicht unterstützte alte Unterklassen ausgeschlossen |
| SGBlur: Vollbildbox | **47:** dieselben 15 Ortstafeln, 32 weitere Schildziele | Die fünf für TSR ungeeigneten Unterklassen bleiben erkennbare generische Schilder |

Alle verbleibenden alten TSR-Testlabels wurden unabhängig visuell gegengeprüft; darunter wurde eine H-Haltestelle nicht mit der Modellklasse `bus:start` für Busspuren gleichgesetzt. Die Testlabels wurden vor Einsicht in TSR-Vorhersagen festgelegt. Native Fotos und aus 360°-Quellen projizierte Ansichten werden getrennt ausgewiesen. Mehrere Bilder können dieselbe Tafel oder Fahrt zeigen; die Bildzahl ist keine Anzahl unabhängiger Fahrten. [Abschließender Labelreview mit 42 IDs](source/real-training-2026-10-20/review-learning/test-peer-review/final-label-qa.json).

## SGBlur: gemessener Versuch

Der Lauf verwendete **YOLO11n mit `sign`, `plate`, `face`** auf `wingki01`, einer **NVIDIA RTX A5000** und Ultralytics **8.4.56**. Trainiert wurden 20 Epochen bei 1280 Pixeln und Batchgröße zwei. Von 20 geprüften Vollbildern gingen **neun Bilder mit 15 bekannten Schildboxen ins Training**, vier mit acht Boxen in die Validierung; sieben reservierte Bilder wurden ausgeschlossen. Diese Bilder sind nicht vollständig für alle sichtbaren Objekte annotiert. [Laufzeit und Quellen](source/real-training-2026-10-20/sgblur/source-and-runtime-evidence.json).

Deshalb wurde nur die letzte Ausgabezeile für `sign` auf den drei Detektionsgrößen angepasst: **195 trainierbare Skalare**. Bekannte Schildziele erhielten ein positives Lernsignal. Außerhalb dieser Ziele sollte das Modell die weichen Vorhersagen der unveränderten Baseline beibehalten; fehlende Annotationen wurden nicht als sichere Negativbeispiele behandelt. Backbone, Boxregression, Gesichts-/Kennzeichenausgaben und BatchNorm-Zustände blieben eingefroren. Es handelt sich somit um eine Anpassung der Schildwahrscheinlichkeiten, nicht um ein vollständig neu trainiertes Detektionsmodell. [Versuchsparameter](source/real-training-2026-10-20/sgblur/run-01/experiment.json).

Gemessen wurde ausschließlich der **Anteil bekannter Zielboxen mit einer passenden Schildvorhersage**, bei IoU ≥ 0,5 und Konfidenz ≥ 0,25:

| Reservierte Zielboxen | Baseline | Kandidat |
|---|---:|---:|
| Alle 47 Ziele | 27/47 · **57,4 %** | 35/47 · **74,5 %** |
| Davon 15 Ortstafeln | 4/15 · **26,7 %** | 9/15 · **60,0 %** |
| DE:310 Ortseingang | 2/3 · **66,7 %** | 2/3 · **66,7 %** |
| DE:311 Ortsausgang | 2/12 · **16,7 %** | 7/12 · **58,3 %** |
| Davon 32 weitere Schildziele | 23/32 · **71,9 %** | 26/32 · **81,3 %** |
| Externe native Ansichten | 2/11 | 7/11 |
| Zusätzliche eigene native Ansichten | 24/33 | 27/33 |
| Projizierte Ansichten | 1/3 | 1/3 |

Es gab acht zusätzliche Treffer und keinen verlorenen Treffer unter diesen bekannten Zielen. Der Kandidat aus **Epoche 9** wurde allein anhand der Validierung gewählt: Der Recall blieb dort bei **4/8**, die vorab festgelegte IoU-Regel entschied bei Gleichstand. Die Testbilder dienten nicht zur Modellauswahl. [Abschlussbeleg](source/real-training-2026-10-20/sgblur/run-01/training-complete.json), [Testbeleg](source/real-training-2026-10-20/sgblur/test-01/receipt.json).

Die Zustandsprüfung fand ausschließlich die 195 erlaubten Änderungen. Auf den geprüften Testbildern blieben rohe Box-/Gesichts-/Kennzeichenausgaben unverändert; auch nach NMS wurden keine veränderten Gesichts-/Kennzeichenlisten beobachtet. **Daraus folgt kein Qualitätsnachweis für Gesichter oder Kennzeichen:** Ein geeigneter unverpixelter Datensatz fehlt. Unvollständige Vollbildannotationen erlauben zudem keine Aussage über Precision, AP oder zusätzliche Fehlalarme. [Unabhängiger Methodenreview](source/real-training-2026-10-20/review-learning/sgblur-method-peer-audit.json).

## TSR und die 134 Bestandsklassen

Der YOLO26l-Klassifikator wurde von **134 auf 136 Klassen** erweitert und auf GPU 0, einer weiteren RTX A5000, **20 Epochen** trainiert. Zu den 38/8 neuen Ortstafeln kamen **13.603/3.077 alte Crops für Training/Validierung**. AdamW verwendete Lernrate 0,0001, Batchgröße 64 und Seed 20261026. Ganze RGB-Crops wurden auf 224 × 224 Pixel skaliert und durch 255 geteilt. Die Auswahl nach dem mittleren Validierungs-F1 entschied für **Epoche 4**. [Konfiguration](source/real-training-2026-10-20/tsr/config.json), [Fortschritt](source/real-training-2026-10-20/tsr/progress.csv).

| Klasse im geprüften Crop | Richtig | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| DE:310 Ortseingang | 2/3 | 100 % | 66,7 % | 0,80 |
| DE:311 Ortsausgang | 12/12 | 100 % | 100 % | 1,00 |

Die ursprüngliche Baseline hat keine eigenen Ausgänge für diese beiden Klassen. Die Precision berücksichtigt zusätzlich die alten Zielbilder: Unter **3.071 gemeinsam ausgewerteten Crops** gab es keine falsche Ortstafelvorhersage auf den 3.056 alten Zielbildern. Die einzige falsche City-Klassifikation betrifft eine kleine, schräge, aus einem Panorama projizierte Eingangstafel bei Fulda; beide Klassifikatoren geben `bad` aus. Auf den 27 zusätzlich geprüften alten Panoramax-Crops sind beide Modelle korrekt. [Getrennter Beispielvergleich](source/real-training-2026-10-20/tsr/reports/prospective-final/BERICHT.md), [gemeinsame Nenner](source/real-training-2026-10-20/tsr/reports/joint-final/BERICHT.md).

Der separate retrospektive Bestand enthält **3.029 Crops mit Unterstützung aller 134 alten Klassen**. Quellbild-UUIDs und Bildduplikate wurden gruppiert. Alte Sequenzen und physische Standorte sind nicht durchgängig verfügbar. Die Baseline kann Teile dieses öffentlichen Korpus bereits beim ursprünglichen Training gesehen haben; seine alten Labels wurden übernommen und nur gezielt auf mögliche Ortstafel-Konflikte gesichtet. Die folgenden Werte messen deshalb die Änderung auf diesem Bestand, keine vortrainingsfreie allgemeine Erkennungsqualität.

| Bestandsvergleich auf denselben 3.029 Crops | Baseline | Kandidat |
|---|---:|---:|
| Richtige Vorhersagen | 3.015 | 3.010 |
| Accuracy | 99,54 % | 99,37 % |
| Mittlerer F1 der 134 Klassen | 99,09 % | 99,12 % |

**Das Bestandsklassen-Gate meldet REGRESSION.** Es gibt elf neu falsche und sechs korrigierte Beispiele, netto fünf zusätzliche Fehler. Der Recall sinkt bei elf Klassen, der F1 bei 20 Klassen. Der leicht höhere mittlere F1 verdeckt diese Einzelrückgänge. Die vorab festgelegte Toleranz beträgt null; fehlende Klassenabdeckung ist hier kein Grund, denn alle 134 Klassen haben Prüfbeispiele.

| Beispiele mit sinkendem Recall | Baseline richtig | Kandidat richtig |
|---|---:|---:|
| `priority:end` | 3/3 | 2/3 |
| `lanes` | 7/7 | 6/7 |
| `maxspeed:130` | 8/8 | 7/8 |
| `no_overtaking` | 29/29 | 28/29 |

Die kleinen Klassennenner machen einzelne Fehler besonders sichtbar. Alle 134 Zeilen mit Support, Precision, Recall, F1 und Differenzen stehen in der [sortierten Klassentabelle](source/real-training-2026-10-20/tsr/reports/retrospective-old/old-deltas-sorted.csv). Der [Fehlerkontaktbogen](source/real-training-2026-10-20/tsr/error-analysis.jpg) zeigt die elf neuen Fehler und sechs Korrekturen mit unveränderten Upstream-Labels. [Vollständiger Bestandsbericht](source/real-training-2026-10-20/tsr/reports/retrospective-old/BERICHT.md).

## Vollständige Erkennungskette

Ein zusätzlicher, vor seiner Ausführung festgelegter Pipelinetest verbindet die bereits gewählten Kandidaten. SGBlur erzeugt Boxen; TSR klassifiziert sämtliche tatsächlich daraus ausgeschnittenen Schildbilder. Die Zielboxen werden erst anschließend zum Zuordnen verwendet. Die Klassifikation verwendet ausschließlich Ausschnitte aus erkannten Boxen.

| Zurückgehaltene Ortstafeln | Box gefunden und richtig klassifiziert | Box fehlt | Nach gefundener Box falsch klassifiziert |
|---|---:|---:|---:|
| DE:310 | 2/3 | 1 | 0 |
| DE:311 | 7/12 | 5 | 0 |
| Zusammen | **9/15 · 60,0 %** | **6** | **0** |

Der Kandidat klassifiziert alle neun zugeordneten Detektor-Crops richtig. Der Unterschied zu 14/15 bei perfekten Crops zeigt die Bedeutung der Box-Erkennung. Die Baseline-Kette liefert keine der neuen City-Klassen, weil ihr Klassifikator diese Ausgänge nicht besitzt.

Auf den 15 Vollbildern erzeugt die Kandidatenkette insgesamt **37 Schildvorschläge**, die Baseline 22. Davon passen neun beziehungsweise vier zu den geprüften Ortstafelzielen. Ohne vollständige Szenenannotation ist offen, welche übrigen Vorschläge zusätzliche echte Schilder oder Fehlalarme sind. Die kleine Anpassung erhöht Schildwahrscheinlichkeiten; Boxgeometrie und Backbone wurden dabei nicht neu gelernt. [Plan und Methoden](source/real-training-2026-10-20/sgblur/pipeline-fixed-city-v1/plan.json), [vollständige Pipeline-Ergebnisse](source/real-training-2026-10-20/sgblur/pipeline-fixed-city-v1/output/results-01/pipeline-results.json).

## Reproduktion und Aussagekraft

Beide Läufe verwendeten das vorhandene, unveränderte Image mit Python 3.12.3, Torch 2.6.0+cu126 und Ultralytics 8.4.56 in getrennten Containern ohne Netzwerk. Modellwahl und Hyperparameter wurden nach den Testwerten nicht mehr verändert. Die Komponententests und der zusätzliche feste Pipelinetest sind getrennte Auswertungen. Der TSR-Kandidat besteht die Anforderung zum Erhalt der bisherigen Klassen nicht.

Die 15 Ortstafelansichten entsprechen 14 Standortkandidaten und 13 konservativen Gruppen. Nur drei Ansichten betreffen Eingänge; zwei davon stammen aus einer möglichen gemeinsamen Fulda-Fahrt. Drei Ansichten sind zielzentrierte Perspektivprojektionen. Die Stichprobe trägt einen explorativen Lehrversuch und keine allgemeine Qualitätsfreigabe. Bei weiterer Modellauswahl darf dieser inzwischen ausgewertete Bestand nicht erneut als unangetasteter Abschlusstest bezeichnet werden.

Die Modellartefakte liegen auf dem Server unter `/home/raphael/youspeed-training-20261020/`: TSR in `tsr/runs/versuch-01/weights/best.pt`, SGBlur in `sgblur/run-01/best.pt`. Ihre vollständigen Hashes stehen im [TSR-Ergebnisbeleg](source/real-training-2026-10-20/tsr/results-summary.json) beziehungsweise im [SGBlur-Abschlussbeleg](source/real-training-2026-10-20/sgblur/run-01/training-complete.json). Beide Kandidaten verwenden sichere State-Dict-/Metadatenformate der mitgelieferten Skripte; zum Laden benötigen sie jeweils den gehashten Originalcheckpoint und den passenden Modelllader. Sie sind keine unmittelbar mit `yolo export model=best.pt` exportierbaren Appmodelle.
