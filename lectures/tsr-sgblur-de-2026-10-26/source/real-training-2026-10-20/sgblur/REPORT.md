# SGBlur: ausgeführter Adaptionsversuch vom 20. Oktober 2026

20 Epochen wurden tatsächlich auf `wingki01`, GPU 2 (RTX A5000), ausgeführt. Der ausschließlich anhand der Validierung gewählte Kandidat aus Epoche 9 wurde danach einmal gemeinsam mit der Baseline auf 47 eingefrorenen Zielboxen geprüft.

| Bekannte Zielboxen | Baseline | Kandidat | Neu erkannt | Zuvor erkannt, jetzt verfehlt |
|---|---:|---:|---:|---:|
| Alle | 27/47 = 57,45 % | 35/47 = 74,47 % | 8 | 0 |
| Ortstafeln | 4/15 = 26,67 % | 9/15 = 60,00 % | 5 | 0 |
| DE:310 / Ortseingang | 2/3 = 66,67 % | 2/3 = 66,67 % | 0 | 0 |
| DE:311 / Ortsausgang | 2/12 = 16,67 % | 7/12 = 58,33 % | 5 | 0 |
| Bisherige Schildarten | 23/32 = 71,88 % | 26/32 = 81,25 % | 3 | 0 |

Das ist **Recall bekannter Zielboxen** bei vorher festgelegtem IoU ≥ 0,5, Konfidenz ≥ 0,25, NMS-IoU 0,7 und Eingabegröße 1280. Die Bilder sind nicht vollständig annotiert. Daraus folgen keine Vollbild-Präzision, keine AP/mAP und keine verlässliche Aussage zur Erkennung unverpixelter Gesichter oder Kennzeichen. Die Auswahl ist klein und gezielt. Keine menschliche Freigabe oder allgemeine Nichtregression wird behauptet.

## Daten und Modellaufgabe

SGBlur behält seine drei Detektorklassen `0=sign`, `1=plate`, `2=face`. DE:310 und DE:311 sind hier Teilgruppen der Klasse `sign`; der Detektor wird nicht um zwei Ausgänge erweitert.

Die 100er-Lernsammlung enthält 214 vorhandene `sign`-Boxen, aber keine `plate`- oder `face`-Ground-Truth. Davon tragen 65 Crops ungeprüfte City-Vorschläge: 46 Eingänge und 19 Ausgänge. Für den Adaptionsversuch wurden 20 Vollbilder visuell auf bekannte Zielboxen geprüft. Der gemeinsame, anhand von Fahrten und räumlicher Nähe gebildete Lernsplit lässt **neun Trainingsbilder mit 15 bekannten Schildboxen** und **vier Validierungsbilder mit acht bekannten Schildboxen** zu. Sieben weitere Bilder mit 14 Boxen bleiben reserviert und wurden vor dem Bildladen ausgeschlossen. Fehlende Zusatzzeichen, entfernte Schilder und anonymisierte Kennzeichen wurden ausdrücklich als unvollständige Szenenannotation dokumentiert. Quelltags und Originalboxen wurden nicht überschrieben.

Die 47 Abschlussziele sind 15 Ortstafeln und 32 andere Schild-Ziele. Fünf Bilder mit für TSR unklarer oder nicht abgedeckter Unterklasse bleiben korrekte generische `sign`-Ziele. Ihre ursprünglichen Auswahlindizes sind 1, 54, 75, 36 und 62. Sie werden im Abschlussbericht unter `known_sign_subclass_unresolved` zusammengefasst; vier dieser fünf Zielboxen werden von beiden Detektoren erkannt. Die ursprünglichen, teilweise zurückgezogenen Unterklassennamen bleiben ausschließlich als Rohprovenienz in `frozen_subclass_label` erhalten. Die übrigen 27 alten Ziele und 15 Ortstafeln verwenden die überprüften Gruppierungslabels. Diese Gruppierungsnamen sind keine SGBlur-Ausgaben. Die neue Klassenprüfungsüberlagerung v3 verändert weder die eingefrorenen generischen Schildboxen noch Vorhersagen, Schwellwerte oder Modellwahl.

## Konservative Trainingsmethode

Baseline ist `yolo11n_panoramax.pt` mit SHA256 `698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a`. Der auf dem Server vorhandene offizielle Checkpoint wurde unverändert aus dem bestehenden SGBlur-Container kopiert.

Es durften nur die `sign`-Zeile der Gewichte und der Bias in den drei abschließenden `cv3`-Klassifikationskonvolutionen verändert werden: insgesamt **195 Skalare**. Backbone, Boxregression, gemeinsame Klassifikationsmerkmale, `face`-/`plate`-Zeilen und alle BatchNorm-Puffer blieben eingefroren. Das gesamte Netz blieb während jedes Vorwärtslaufs im Eval-Modus; Autograd war für die sechs betreffenden Parametertensoren aktiv. Gradientenmasken sperrten deren andere Klassenzeilen.

Bekannten positiven Schild-Ankern wird Zielwert 1 zugewiesen. Außerhalb dieser Anker stabilisiert ein unveränderter Baseline-Teacher die bisherigen `sign`-Wahrscheinlichkeiten mit weichen BCE-Zielen, vorab festem Gewicht 1. Fehlende Annotationen werden dadurch nicht als harte negative Labels verwendet. Eine feste L2-Regularisierung des `sign`-Parameterdeltas hat Gewicht 0,0001. Optimierung: AdamW, Lernrate 0,001, Weight Decay 0, Batch 2, 20 Epochen, Seed 20261026. Es gibt keine zufällige Bildaugmentation; verwendet wird ausschließlich eine quadratische RGB-Letterbox auf 1280 Pixel mit unveränderter Boxgeometrie.

Dies ist eine kleine, partiell überwachte **Anpassung des Schild-Ausgangs** mit Teacher-Stabilisierung. Es ist kein vollständiges Nachtraining des dreiklassigen Detektors.

## Auswahl ohne Test-Tuning

Vor dem Start wurde das Lernmanifest mit SHA256 `bf2cb432ca7b144e0c7c9822f065ac964d1f9ae579059234bf5f9129a281137e` festgehalten. Der gemeinsame Split hat SHA256 `b44f2a22edb8fac41d569f1b7329f18d9b1b9045ea31d5209fc4baab3ffc4ca6`. Die Validierung entscheidet zuerst nach Zielrecall, dann mittlerem besten GT-IoU, dann minimaler mittlerer `sign`-Wahrscheinlichkeitsdrift zum Teacher. Auch die unveränderte Baseline aus Epoche 0 war wählbar.

Baseline und ausgewählter Kandidat erreichen auf der Validierung jeweils 4/8 bekannte Zielboxen. Der vorab definierte Tie-Break wählt Epoche 9. Die Testergebnisse wurden erst danach erzeugt und führten zu keiner weiteren Modell-, Schwellen- oder Hyperparameterwahl.

Der eingefrorene Testmanifest-Hash ist `01f6701be9fcc86f089709a24901a91285386467413224a290c8f97e245fcddc`. Der ausgewählte Checkpoint hatte vor der Testauswertung bereits SHA256 `63cebe1bc4372ccdd9a4f3bdb525ed6a8094d8b05f0a27a39dfbb46fa0e1b5dd`.

## Aufnahmearten und Mehrfachansichten

| City-Teilgruppe | Anzahl | Baseline erkannt | Kandidat erkannt |
|---|---:|---:|---:|
| Externe native 2D-Aufnahmen, DE:311 | 11 | 2 | 7 |
| Eigene native 2D-Aufnahme, DE:310 | 1 | 1 | 1 |
| Perspektivprojektionen aus Panoramen, DE:310 | 2 | 1 | 1 |
| Perspektivprojektion aus Panorama, DE:311 | 1 | 0 | 0 |

Die fünf zusätzlichen City-Treffer betreffen native 2D-Ortsausgänge. Bei den drei Perspektivansichten und den drei Ortseingängen steigt der Recall nicht.

Die 15 City-Ansichten gehören zu 14 Standortkandidaten und 13 konservativen Gruppen. Zwei Putlitz-Ansichten werden gemeinsam gezählt; zwei Fulda-Eingänge liegen in derselben möglichen Fahrtgruppe. Bei gleichem Gewicht je Standortkandidat und mittlerem View-Recall innerhalb des Standorts ergibt sich 28,57 → 64,29 %. Bei gleichem Gewicht je konservativer Gruppe sind es 26,92 → 65,38 %. Diese Gruppen sind keine zertifizierten unabhängigen physischen Standorte oder Fahrten. Ihre Einzelwerte und Nenner stehen in `results-analysis.json`; es wurden keine neuen Inferenzen durchgeführt.

## Alte Ziele und eingefrorene Zweige

Unter den 32 alten Schild-Zielen gibt es drei zusätzliche Treffer und keinen verlorenen Baseline-Treffer. Die zusätzlichen Treffer liegen in den geprüften Gruppierungslabels `give_way`, `maxspeed:80` und `no_overtaking`, jeweils ein Fall. Alle anderen geprüften alten Gruppierungslabels bleiben unverändert. Die fünf taxonomisch ungeklärten generischen Schildziele bleiben bei vier Treffern. Diese kleine Stichprobe ist keine Abdeckung aller bisherigen Schildarten.

Ein State-Dict-Vergleich nach jeder Epoche und am ausgewählten Kandidaten bestätigt bitweise unveränderte Werte außerhalb der 195 zulässigen `sign`-Skalare, einschließlich aller BatchNorm-Puffer. Zusätzlich sind Boxregressionswerte und `face`-/`plate`-Logits vor NMS auf sämtlichen Abschlussbildern bitweise gleich. Im beobachteten Test ändern sich auch die `face`-/`plate`-Listen nach NMS nicht. Das wird separat geprüft, weil ein anderer `sign`-Score grundsätzlich Argmax und nachgelagerte Auswahl ändern kann. Ohne unverpixelte, vollständige Ground Truth ist die fachliche Gesichts-/Kennzeichenregression trotzdem **nicht prüfbar**.

## Umgebung und Artefakte

Das bestehende, unveränderte Trainingsimage `youspeed-tsr-fr-end-training:20260924` hat Image-ID `sha256:886be2a4e18d52e587acf3ebfeaa7cbf2da92c1c26d2355e83b94217c474faca`. Es enthält Python 3.12.3, Torch 2.6.0+cu126, torchvision 0.21.0+cu126, Ultralytics 8.4.56, NumPy 2.4.4 und Pillow 11.1.0. Es wurde kein Paket installiert. Die isolierten Container hatten kein Netzwerk, ein nur lesbares Root-Dateisystem, vier CPUs und 12 GiB RAM-Limit. CUDA war ausschließlich für die A5000 mit UUID `GPU-adb614d2-9deb-869b-8b35-a789c7e95cf4` freigegeben; im Container war sie `cuda:0`.

Der Trainingscontainer lief von 10:44:34 bis 10:45:09 UTC, die Abschlussauswertung von 10:46:05 bis 10:46:28 UTC, beide mit Exitcode 0. Beide Container sind beendet. GPU 2 liegt beim abschließenden Snapshot wieder bei 499 MiB und 0 % Auslastung; bestehende Dienste wurden nicht verändert.

- `frozen_sign_adapt.py`: ausgeführter Trainer und Evaluator, SHA256 `4d8d9b6480cddbdd3357776d133b5eafa972a3dcca668378abaf8ca0b5d0d0a1`.
- `run-01/progress.csv`, `experiment.json`, `training-complete.json`: alle 20 Epochen, Konfiguration, Auswahl und Checkpointhashes.
- `run-01/best.pt`: 10.547.623 Bytes, SHA256 `63cebe1bc4372ccdd9a4f3bdb525ed6a8094d8b05f0a27a39dfbb46fa0e1b5dd`.
- `run-01/last.pt`: 10.547.623 Bytes, SHA256 `4f26a977525b8c46f8e5bc58734d81174bb695ede0c6a862813d1a7bd7c02f72`.
- `test-01/`: eingefrorener State-Nachweis, beide vollständigen Zielrecall-Berichte und Receipt.
- `known-target-comparison.csv` und `results-analysis.json`: alle 47 GT-Ziele mit Baseline-/Kandidatentreffer, Einzelverlusten/-gewinnen und Gruppenaggregation.
- `source-and-runtime-evidence.json`: Checkpoints, begrenzte Suche nach Originaldaten, Versionen, GPU und Laufzeitnachweise.

`best.pt` und `last.pt` verwenden ein eigenes, mit `weights_only=True` ladbares State-Dict-/Metadatenformat. Sie sind kein direkt mit `yolo export model=best.pt` nutzbarer Ultralytics-Checkpoint. Die Rekonstruktion erfolgt mit `load_model(baseline, device, candidate)` aus dem beigefügten Skript und der gehashten Baseline. Ein Mobileexport oder ein Produktionseinsatz wurde nicht durchgeführt.

Der ursprüngliche vollständige SGBlur-Trainings-/Prüfkorpus wurde bei der begrenzten Suche nicht gefunden. Der Nutzer hat bestätigt, dass auf dem Server kein zusätzlicher vollständig annotierter, unverpixelter Bestand verfügbar ist. Die Checkpointmetadaten nennen `smartphones.yaml` und einen auf diesem Server nicht vorhandenen Trainingspfad. [Die öffentliche Modellablage](https://huggingface.co/Panoramax/detect_face_plate_sign/tree/main) enthält Checkpoints und Validierungsabbildungen, aber keinen identifizierten vollständigen Bild-/Label-Download. Das ist eine Grenze dieses Versuchs und keine Behauptung, dass dieser Korpus nirgends existiert.
