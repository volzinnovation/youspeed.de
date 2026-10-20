# Fester Pipeline-Test: SGBlur → TSR, 20.10.2026

Die ausgewählte Modellkette erkennt und klassifiziert **9 von 15 bekannten Ortstafel-Zielen korrekt (60 %)**. Sechs Ziele verfehlt bereits SGBlur. TSR klassifiziert alle neun passenden, tatsächlich erkannten Ausschnitte richtig. Es wurden keine GT-Ausschnitte als TSR-Eingabe verwendet.

| Bekannte Ziele | Unterstützung | SGBlur trifft | Kette korrekt | Detektor verfehlt | TSR falsch nach Detektortreffer |
|---|---:|---:|---:|---:|---:|
| DE:310 / city:start | 3 | 2 | 2 (66,7 %) | 1 | 0 |
| DE:311 / city:end | 12 | 7 | 7 (58,3 %) | 5 | 0 |
| Insgesamt | 15 | 9 | 9 (60,0 %) | 6 | 0 |

Externe native Perspektivbilder: 7/11 korrekt; eigenes natives Perspektivbild: 1/1; lokal aus Kugelpanoramen projizierte Bilder: 1/3. Gleichgewichtung der 14 Standortkandidaten ergibt 64,29 %, der 13 konservativen Gruppen 65,38 %. Diese Gruppierung belegt keine physische Unabhängigkeit.

Die Baseline-Kette trifft vier Zielboxen und klassifiziert keine Ortstafel korrekt. Der ursprüngliche TSR-Klassifikator besitzt keine Ausgänge für city:start/end; sein Nullwert ist daher durch den Wortschatz vorgegeben. Der Kandidat nutzt den vorher auf Validierungsdaten ausgewählten SGBlur-Checkpoint aus Epoche 9 und TSR aus Epoche 4. Alle 20 Trainingsepochen waren vor diesem Lauf abgeschlossen. Kein Modell, Schwellenwert oder Verarbeitungsschritt wurde anhand dieser Pipeline-Ergebnisse ausgewählt oder angepasst.

Der einzige zusätzliche Auswertungslauf lief am 20.10.2026 von 11:03:46 bis 11:04:03 UTC auf GPU 2 (RTX A5000), isoliert im unveränderten Containerabbild. Quellen und Gewichte waren nur lesbar eingebunden. Fixe Schwellen: SGBlur 1280 px, Konfidenz 0,25, NMS-IoU 0,70; eindeutige Zielzuordnung bei IoU ≥ 0,50. Alle Post-NMS-Schilder wurden vor dem GT-Abgleich klassifiziert. Ausschnitte: tatsächliche native Modellbox, links/oben abrunden, rechts/unten aufrunden und auf das Bild begrenzen; RGB, bilinear 224×224, float32/255.

Die 15 Detektor-Trefferentscheidungen stimmen für beide Modellstände einzeln exakt mit den vorherigen SGBlur-Komponentenberichten überein (4 Baseline, 9 Kandidat). Aufbewahrt werden alle Post-NMS-Boxen einschließlich plate/face, 22 Baseline- und 37 Kandidaten-Schilderausschnitte, sämtliche TSR-Logits, Wahrscheinlichkeiten, Klassen, GT-Zuordnungen und Prüfsummen. Diese 59 Ausschnitte umfassen auch zusätzliche, nicht als Ziel annotierte Schilder. Ihre Anzahl erlaubt keine Präzisionsaussage.

Der separat gemessene TSR-Test der bisherigen 134 Klassen meldet **REGRESSION**. Der Ortstafel-Erfolg hebt diesen Befund nicht auf; es liegt keine allgemeine Modell- oder App-Freigabe vor. Die kleine, gezielt gewählte und durch den Assistenten geprüfte Stichprobe besitzt keine vollständige Szenenannotation und erlaubt weder AP/Präzision noch eine Aussage zur vollständigen face/plate-Regression. Native und projizierte Quellen bleiben getrennt auswertbar.

## Belege

- `output/results-01/pipeline-results.json`: vollständige unveränderte Modellvorhersagen und Zielzuordnungen.
- `known-city-pipeline-comparison.csv`: ein Datensatz je bekanntem Ziel.
- `summary.json`: Zusammenfassungen und exakter Abgleich mit den Komponentenberichten.
- `plan.json`, `pipeline_city15.py`, `launch-receipt.json`, `completion-receipt.json`: vorab fixierter Plan, ausgeführter Code und Laufbelege.
- `city15-source-provenance.json`: Urheber, Quelllinks, Lizenz, Originaltags und Bearbeitung der Bildquellen. Ausschnitte stehen unter CC BY-SA 4.0; sie sind Modellvorschläge und keine vollständige Ground Truth.
- `output/results-01/artifact-sha256.json`: originale Prüfsummen des Auswertungslaufs. Die separaten Komponentenberichte wurden unverändert belassen.
