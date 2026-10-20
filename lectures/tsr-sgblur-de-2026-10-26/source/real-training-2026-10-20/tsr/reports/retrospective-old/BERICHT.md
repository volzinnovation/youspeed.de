# Retrospektive Prüfung der 134 Bestandsklassen

**Die Baseline kann diesen öffentlichen Korpus bereits im eigenen Training gesehen haben.** Die Daten wurden für dieses Beispiel neu nach Quellbild-/Duplikatgruppen aufgeteilt. Erfasst wird die Änderung gegenüber der Baseline auf diesem endlichen Bestand; keine unabhängige absolute Generalisierungsleistung. Alte physische Standorte/Fahrten sind nicht vollständig bekannt.

Beide Ortstafelklassen werden im separat eingefrorenen prospektiven Beispielbestand gemessen. Alle 134 Altklassen haben hier Support. Ein Rückgang wird unverändert als REGRESSION berichtet.

# Modellvergleich auf test

**Verbindliche Prüfung alter Klassen: REGRESSION.** Toleranz: 0; keine Verschlechterung von Recall/F1 je alter Klasse oder altem Gesamtwert erlaubt.

Dieser Vergleich nutzt ausschließlich Bilder, deren wahre Klasse zu den 134 alten Klassen gehört. Neue Ortstafelbilder beeinflussen diese Prüfung nicht.

- arrow_through: recall auf alten Zielbildern gesunken (-0.027778).
- arrow_through: f1 auf alten Zielbildern gesunken (-0.027027).
- bad: f1 auf alten Zielbildern gesunken (-0.003861).
- bad:buildings: recall auf alten Zielbildern gesunken (-0.025000).
- bad:buildings: f1 auf alten Zielbildern gesunken (-0.000313).
- hazard:narrow_both: recall auf alten Zielbildern gesunken (-0.024390).
- hazard:narrow_both: f1 auf alten Zielbildern gesunken (-0.000297).
- hazard:narrow_left: recall auf alten Zielbildern gesunken (-0.076923).
- hazard:narrow_left: f1 auf alten Zielbildern gesunken (-0.040000).
- hazard:narrow_right: f1 auf alten Zielbildern gesunken (-0.014857).
- lanes: recall auf alten Zielbildern gesunken (-0.142857).
- lanes: f1 auf alten Zielbildern gesunken (-0.076923).
- maxspeed:100: f1 auf alten Zielbildern gesunken (-0.014925).
- maxspeed:130: recall auf alten Zielbildern gesunken (-0.125000).
- maxspeed:130: f1 auf alten Zielbildern gesunken (-0.066667).
- maxspeed:40: f1 auf alten Zielbildern gesunken (-0.021277).
- maxspeed:50: recall auf alten Zielbildern gesunken (-0.033333).
- maxspeed:50: f1 auf alten Zielbildern gesunken (-0.016949).
- maxspeed:60: recall auf alten Zielbildern gesunken (-0.020408).
- maxspeed:60: f1 auf alten Zielbildern gesunken (-0.010309).
- no_bicycle: f1 auf alten Zielbildern gesunken (-0.015873).
- no_car: f1 auf alten Zielbildern gesunken (-0.037037).
- no_exit: f1 auf alten Zielbildern gesunken (-0.016949).
- no_overtaking: recall auf alten Zielbildern gesunken (-0.034483).
- no_overtaking: f1 auf alten Zielbildern gesunken (-0.017534).
- oneway: recall auf alten Zielbildern gesunken (-0.090909).
- oneway: f1 auf alten Zielbildern gesunken (-0.057895).
- pedestrian_crossing: f1 auf alten Zielbildern gesunken (-0.011765).
- priority:end: recall auf alten Zielbildern gesunken (-0.333333).
- priority:end: f1 auf alten Zielbildern gesunken (-0.200000).
- priority:start: f1 auf alten Zielbildern gesunken (-0.015873).
- accuracy auf alten Zielbildern gesunken (-0.001651).

| Alte Klassen, nur alte Zielbilder | Baseline | Kandidat |
| --- | ---: | ---: |
| Accuracy / Top-1 | 99.5 % | 99.4 % |
| Macro-F1, alte Klassen mit Beispielen | 99.1 % | 99.1 % |

Details je alter Klasse: old-only-per-class.csv. Ohne Beispiele für jede alte Klasse bleibt die Prüfung unvollständig.

## Gesamter Bildsatz und neue Klassen

3029 Bilder aus 2506 Quellbild-/Duplikatgruppen (physische Unabhängigkeit nicht bestätigt); dieselben Bilder für beide Modelle.

| Messwert | Baseline (134 Klassen) | Kandidat (136 Klassen) |
| --- | ---: | ---: |
| Accuracy | 99.5 % | 99.4 % |
| Macro-F1, Klassen mit Testbeispielen | 99.1 % | 99.1 % |
| Macro-F1, Ortstafelklassen mit Beispielen | nicht messbar | nicht messbar |

Die Baseline kann city:start und city:end nicht ausgeben. Sie wird trotzdem auf allen Bildern bewertet.

## Die beiden neuen Klassen

| Klasse | Beispiele | Präzision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: |
| city:start | 0 | nicht messbar | nicht messbar | nicht messbar |
| city:end | 0 | nicht messbar | nicht messbar | nicht messbar |

Alte Klassen mit niedrigerem F1 im Vergleich nur alter Zielbilder: **20**. Jede Klasse steht in old-only-per-class.csv; fehlende Beispiele sind keine bestandene Prüfung.
- priority:end: F1 100.0 % → 80.0 %; 3 Beispiele.
- lanes: F1 100.0 % → 92.3 %; 7 Beispiele.
- maxspeed:130: F1 100.0 % → 93.3 %; 8 Beispiele.
- oneway: F1 90.0 % → 84.2 %; 11 Beispiele.
- hazard:narrow_left: F1 100.0 % → 96.0 %; 13 Beispiele.
- no_car: F1 100.0 % → 96.3 %; 13 Beispiele.
- arrow_through: F1 97.3 % → 94.6 %; 36 Beispiele.
- maxspeed:40: F1 100.0 % → 97.9 %; 23 Beispiele.
- no_overtaking: F1 98.3 % → 96.6 %; 29 Beispiele.
- maxspeed:50: F1 100.0 % → 98.3 %; 30 Beispiele.
- no_exit: F1 100.0 % → 98.3 %; 29 Beispiele.
- no_bicycle: F1 100.0 % → 98.4 %; 31 Beispiele.
- priority:start: F1 100.0 % → 98.4 %; 31 Beispiele.
- maxspeed:100: F1 100.0 % → 98.5 %; 33 Beispiele.
- hazard:narrow_right: F1 98.4 % → 96.9 %; 31 Beispiele.
- pedestrian_crossing: F1 100.0 % → 98.8 %; 42 Beispiele.
- maxspeed:60: F1 100.0 % → 99.0 %; 49 Beispiele.
- bad: F1 99.2 % → 98.8 %; 127 Beispiele.
- bad:buildings: F1 98.8 % → 98.7 %; 40 Beispiele.
- hazard:narrow_both: F1 98.8 % → 98.8 %; 41 Beispiele.

Nicht bewertbare Klassen ohne Beispiele: city:start, city:end.

## Interpretation

Präzision: Wie viele als Klasse X gemeldete Bilder sind tatsächlich X? Recall: Wie viele echte X werden gefunden? F1 verbindet beide Werte.

Die Confusion-CSV zeigt wahre Klassen in den Zeilen und Vorhersagen in den Spalten. per-class.csv beschreibt den gesamten Bildsatz; old-only-per-class.csv ausschließlich die alten Zielbilder für die Regressionsprüfung. Leere CSV-Felder und null in JSON bedeuten einen nicht definierten Wert.

Dies misst Crop-Klassifikation. Detektor-Recall auf Vollbildern, Fehlalarme pro Fahrtstunde, mobile Laufzeit und bestätigte Passagen werden damit noch nicht gemessen.

Ein niedrigerer Trainings-Loss reicht nicht für eine Verbesserung. Neue Klassen getrennt prüfen und Verschlechterungen alter Klassen begründen.

Nach Einsicht in test keine Hyperparameter mehr anhand dieses Tests ändern. Weitere Änderungen brauchen einen neuen unberührten Testsatz.

Baseline SHA256: `f8277a3790fd3357b3ca31a086c7dc9f365785c7fa44bfd3b5c68834555699c7`
Kandidat SHA256: `8991ee8127f50bfb88755b2bb8b293a08433c4787c6cf96d81539e087cd87a67`
Datensatzmanifest SHA256: `e67c8699a705371b79d68ea534371e2ae0c5e74ce83be7fd62fce671a1cac9eb`
