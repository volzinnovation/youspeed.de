# Prospektiver TSR-Beispielvergleich

**Sichtprüfung durch KI-Assistenten, keine menschliche Ground-Truth-Freigabe.**

Gezielt gesammelte Beispiele; kein repräsentativer Blindtest und kein Nachweis einer allgemeinen Modellfreigabe.

42 primäre Crops; 41 Standortkennungen und 20 konservative Gruppen.
Die Standort-/Fahrtunabhängigkeit ist nicht abschließend menschlich bestätigt. Die zielzentrierten Panoramaprojektionen werden getrennt ausgewiesen.

Vor Vorhersagen ausgeschlossene zweifelhafte Labels: 5. Originalmanifest und Trainingsbindung bleiben erhalten.

| Primärer Cropvergleich | Baseline134 | Kandidat136 |
| --- | ---: | ---: |
| Accuracy | 64.3 % | 97.6 % |

## Neue Ortstafelklassen

| Klasse | Support | Präzision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: |
| city:start | 3 | 100.0 % | 66.7 % | 80.0 % |
| city:end | 12 | 100.0 % | 100.0 % | 100.0 % |

Die Baseline besitzt keine eigenen city:start/city:end-Ausgänge. Höhere Werte dort belegen zunächst die neue Ausgabefähigkeit auf diesen Beispielen.

## Getrennte Bildarten

| Teilmenge | Bilder | Baseline Accuracy | Kandidat Accuracy |
| --- | ---: | ---: | ---: |
| native | 11 | 0.0 % | 100.0 % |
| own_native | 28 | 96.4 % | 100.0 % |
| projected | 3 | 0.0 % | 66.7 % |

## Standorte und konservative Gruppen

Mehrere Ansichten einer Tafel zählen hier zusätzlich als ein Standort: zuerst der mittlere Anteil korrekter Ansichten innerhalb jedes Standorts, dann der ungewichtete Mittelwert dieser Standorte.

Standortgewichtete City-Accuracy des Kandidaten: 92.9 %; alle Ansichten korrekt bei 13/14 Standorten.

## Bestehende Klassen

Dieser externe Teilbestand deckt nur 12 alte Klassen ab. Sein separates Altklassen-Gate lautet UNVOLLSTAENDIG; das ersetzt keinen Vergleich aller 134 Klassen.
Der vollständig abgedeckte Altklassenvergleich steht im gesonderten retrospektiven Bericht. Dessen öffentlicher Ursprungskorpus kann bereits dem Baseline-Training bekannt gewesen sein und ist keine unabhängige absolute Qualitätsmessung.

## Bindung und Grenzen

Trainingsmanifest SHA256: `e67c8699a705371b79d68ea534371e2ae0c5e74ce83be7fd62fce671a1cac9eb`
Originaltestmanifest SHA256: `01f6701be9fcc86f089709a24901a91285386467413224a290c8f97e245fcddc`
Ausschluss-Overlay SHA256: `b719af8f1a29b378ddd946cdc0d340405157e0fce206f038438760b94e94a17c`
Kandidat SHA256: `8991ee8127f50bfb88755b2bb8b293a08433c4787c6cf96d81539e087cd87a67`

Keine Detektor-Recall-Messung, kein Mobilplattformtest und keine Garantie für weitere Straßenbilder. Nach dieser Testeinsicht werden keine Hyperparameter anhand dieses Bestands geändert.
