# KI für intelligente Mobilität

Profilprojekt IMo WS27-28 HSPF  
Prof. Dr. Raphael Volz  
19. Oktober 2026 · 90 Minuten · 42 Folien

## 1. KI für intelligente Mobilität (0–1 Min.)

Ein reales Projekt verbindet offene Geodaten, mobile Sensorik und überwacht trainierte Modelle. Das Profilprojekt beginnt mit selbst aufgenommenen Bildern und überprüften menschlichen Labels. Ziel sind nachvollziehbare Verbesserungen für Server und beide mobilen Clients.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/release/dashcam-composites-2026-10-03/README.md

## 2. Agenda (1–2 Min.)

Die Abschnitte strukturieren den Vortrag ohne Minutenangaben auf der Folie. Insgesamt sind 90 Minuten einschließlich Demonstrationen und Fragen vorgesehen. Die zwei Themen werden von jeweils zwei Teams bearbeitet.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/README.md

## 3. Das Projekt YouSpeed.de (2–4 Min.)

Die aktuelle Website beschreibt ein Smartphone-Assistenzsystem ohne Fahrzeugintegration. Kameraerkennung funktioniert auf dem Gerät; Videos bleiben lokal. Straßenfotos werden nach Auswahl und mit verbundenem Konto zu Panoramax hochgeladen. Die Website unterscheidet den direkten Android-Download von der jeweiligen Store-Version. Die beiden Links öffnen Projekt und Quellcode.

Quellen:

- https://youspeed.de/
- https://github.com/volzinnovation/youspeed.de/blob/main/README.md

## 4. OpenStreetMap (4–6 Min.)

Die vertraute Karte ist eine Darstellung einer gemeinschaftlich gepflegten Datenbank. Dieselben Objekte können in Karten, Routenplanern und Analysen genutzt werden. An Pforzheim zeigen: Straßen, Wege, Gebäude, Gewässer und Attribute. Die Datenbank ist für das Projekt wichtiger als ein Kartenhintergrund.

Quellen:

- https://www.openstreetmap.org/#map=14/48.891/8.700
- https://www.openstreetmap.org/copyright

## 5. Das OpenStreetMap-Ökosystem (6–8 Min.)

Mapper bearbeiten Objekte mit iD oder JOSM. Regionale Extrakte versorgen Anwendungen wie YouSpeed. Panoramax liefert geolokalisierte Bildbelege. Ein Mensch prüft daraus abgeleitete Vorschläge und veröffentlicht einen Changeset. So verbessern Projektbeiträge später die nächste Bundle-Generation.

Quellen:

- https://www.openstreetmap.org/about
- https://www.openstreetmap.org/copyright
- https://download.geofabrik.de/
- https://docs.panoramax.fr/
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/mapdata/README.md

## 6. OSM-Objekte und Verkehrszeichen-Tags (8–10 Min.)

Die Highway-Beispiele zeigen OSM-Carto-Renderings aus dem OSM-Wiki für motorway, primary und residential. Der Wert beschreibt die Straßenfunktion. Beim Tempo-50-Schild empfiehlt das OSM Traffic Sign Tool am Knoten traffic_sign=DE:274-50; am Way maxspeed=50, source:maxspeed=sign und traffic_sign=DE:274-50. Die Geometrie-Empfehlungen sind als Beta markiert und müssen fachlich geprüft werden. OSM benutzt Schlüssel-Wert-Paare. Der nationale Zeichencode beschreibt das Schild, der Straßen-Tag dessen geprüfte Wirkung. Eine Ortstafel ist nicht einfach eine Gemeindegrenze. Das OSM-Verkehrswende-Werkzeug hilft beim Auffinden von Zeichencodes und empfohlenen Straßen-Tags; Vorschläge vor einem OSM-Edit fachlich prüfen.

Quellen:

- https://wiki.openstreetmap.org/wiki/Elements
- https://wiki.openstreetmap.org/wiki/Key:maxspeed
- https://wiki.openstreetmap.org/wiki/Tag:traffic_sign=DE:310
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/mapdata/spec/README.md
- https://trafficsigns.osm-verkehrswende.org/DE?signs=DE:274-50
- https://wiki.openstreetmap.org/wiki/Key:highway

## 7. Panoramax: Bilder mit Annotationen (10–12 Min.)

Der Screenshot zeigt vorhandene Annotationen des realen Bernbach-Bildes. Ein Rahmen lokalisiert das Zeichen innerhalb des Bildes. Semantik kann von einem Modell oder einem Menschen stammen; beides getrennt auswerten. Panoramax-Annotationen sind noch keine OSM-Edits.

Quellen:

- https://panoramax.youspeed.de/?pic=a458609a-bbf1-413a-a039-5e0f685e9923&focus=pic
- https://docs.panoramax.fr/tags/

## 8. Drei Orakel und ihr gültiger Kontext (12–15 Min.)

Die Reihenfolge folgt der Produktvorgabe für diese Vorlesung: Nutzerkorrektur vor Kamera vor Datenbank, jeweils im gültigen Kontext. Ein bestätigter Innerorts-/Außerorts-Wechsel invalidiert die bisherige Kamera-Referenz; das Tempolimit wird im neuen Kontext bestimmt. Kurze unbekannte oder schwache Kontextzustände lösen dies nicht aus. Die Bestätigung benötigt vertrauenswürdige Siedlungsevidenz. Eine straßengebundene Sprachkorrektur kann an dieser Grenze ebenfalls enden. Hier wird bestehende Laufzeitlogik erklärt; keine Änderung am geschützten Zustandsautomaten.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/shared/tsr/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/shared/speed-limit-reference/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/shared/speed-limit-reference/AGENTS.md
- https://github.com/volzinnovation/youspeed.de/blob/main/iphone/SpeedConsumerApp/DriveSessionViewModel.swift
- https://github.com/volzinnovation/youspeed.de/blob/main/android/app/src/main/java/de/youspeed/android/alpha/ConsumerSessionController.kt
- https://github.com/volzinnovation/youspeed.de/blob/main/docs/speed-limit-reference/MODEL.md

## 9. Architektur auf dem Smartphone (15–17 Min.)

GitHub Actions baut regionale OSM-/SQLite-Bundles samt Regression und Manifest. Die Prolix-/Panoramax-Modellbasis wird für Core ML und LiteRT exportiert. Die App nutzt beides mit Standort und Kamera. Sie produziert Tempohinweise sowie Beobachtungen und Ausschnitte; vollständige Panoramax-Fotos sind ein getrennter Erfassungsweg. Die drei Orakel wurden vorher erklärt.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/main/.github/workflows/karlsruhe_bundle_build_and_release.yml
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/AGENTS.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/iphone/SpeedConsumerApp/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/android/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_SUPPLEMENTARY_OCR_2026-10-16.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/PANORAMAX_CAPTURE_FOUNDATION.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/YOUSPEED_1_4_APP_IMPLEMENTATION.md
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/docs/youspeed/COLLECTION_UPLOAD_V2.md

## 10. Server, Inspector und Rückfluss nach OSM (17–19 Min.)

Vollständige Straßenfotos gehen nach Auswahl an Panoramax mit Blur, Detektion, Prolix-Klassifikation und OCR. Beobachtungen und Crops gehen zusätzlich über die Upload-API in die Sichtungs-/Crop-Datenbank. Der Inspector macht die Daten überprüfbar. Nutzer geben geeignete Vorschläge frei, exportieren OSC und veröffentlichen im OSM-Editor einen bewussten Changeset. Kein automatischer Modell-Upload nach OSM. Die besseren OSM-Daten gelangen über neue Bundles wieder zu den Apps.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/YOUSPEED_1_4_APP_IMPLEMENTATION.md
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/docs/youspeed/BACKEND_IMPLEMENTATION.md
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/docs/youspeed/PANORAMAX_CORPUS.md
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/deploy/panoramax/README.md
- https://github.com/volzinnovation/youspeed.de/blob/main/docs/YOUSPEED_1_4_SPEC.md
- https://github.com/volzinnovation/youspeed.de/blob/main/docs/USER_GUIDE_DE.md

## 11. iPhone und Android (19–21 Min.)

Die Ansichten stammen aus den deutschsprachigen Store-Metadaten. Das Dashcam-Artwork kombiniert vorhandene native UI mit einem echten Aufnahmebild. Zwei native Implementierungen müssen dasselbe sichtbare Produktverhalten liefern. Die Bilder zeigen Fahrtfunktionen statt eines Einrichtungsdialogs.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/AGENTS.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/iphone/SpeedConsumerApp/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/android/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_SUPPLEMENTARY_OCR_2026-10-16.md

## 12. Offline-Bundles aus GitHub Actions (21–23 Min.)

Die Pipeline lädt regionale OSM-Daten, baut die SQLite-Datenbank, prüft sie und veröffentlicht versionierte Release-Assets mit Manifest. Die App lädt ein Paket bewusst herunter, validiert es und führt Map Matching lokal aus. Bundle und Modellpaket sind getrennte Artefakte. Die Karte allein beweist keine Erkennungsqualität.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/mapdata/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/mapdata/spec/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/DATA_MANAGER.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/shared/matcher/README.md
- https://github.com/volzinnovation/youspeed.de/blob/main/.github/workflows/karlsruhe_bundle_build_and_release.yml

## 13. Drei unterschiedliche Datenausgaben (23–25 Min.)

Die Kamera versorgt mehrere unabhängige Funktionen. Erkennung benötigt keine Videoaufzeichnung. Lokale Videos eignen sich für die Spurannotation. Ausgewählte vollständige Bilder versorgen Panoramax. Die integrierten 1.4-Entwicklungsstände verbinden Erkennungen und Crops mit der Upload-Warteschlange; dies ist von der öffentlich verfügbaren App-Version zu unterscheiden.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/PANORAMAX_CAPTURE_FOUNDATION.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/YOUSPEED_1_4_APP_IMPLEMENTATION.md
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/docs/youspeed/COLLECTION_UPLOAD_V2.md

## 14. KI Aufgaben in youspeed.de (25–27 Min.)

Fünf KI-Aufgaben umfassen die vier Bildverarbeitungsaufgaben und Spracherkennung. Apple Speech auf dem iPhone und Vosk auf Android wandeln eine gesprochene Nutzerkorrektur in Text um. Dies ist von der anschließenden Interpretation und Gültigkeit der Korrektur zu unterscheiden. Die Aufgaben sind nicht automatisch fünf heute installierte neuronale Netze. Die aktuelle Zeichenlokalisierung ist Objektdetektion. Die aktuelle mobile Spurbasis arbeitet mit klassischer Bildverarbeitung. Segmentierung und gelernte Spurerkennung werden als Erweiterungen sauber von vorhandenen Komponenten unterschieden.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/VIDEO_TRAFFIC_SIGN_RECOGNITION_YOLO_SPEC.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/shared/lanes/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/LANE_DETECTION_TECHNICAL_REPORT.tex
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_SUPPLEMENTARY_OCR_2026-10-16.md

## 15. Zeichen finden: Detektion und Segmentierung (27–29 Min.)

Das reale annotierte Bild zeigt die heute verfügbare Box-Lokalisierung. Die Ortstafel dient als Motiv für die zweite Stufe. Es wird keine erfundene Segmentierungsmaske gezeigt. Für späteres Maskentraining sind überprüfte Polygone oder Masken nötig; ein ausgefülltes Rechteck ist keine präzise Pixelwahrheit.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_PROLIX_ALIGNMENT_2026-09-10.md
- https://docs.panoramax.fr/backend/install/deep_dive/semantics/
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/shared/tsr/README.md

## 16. Verkehrszeichen pro Land klassifizieren (29–31 Min.)

Prolix stellt die Modellbasis und nationale Zuordnungen bereit. Länderklassifikation läuft auf Server und Smartphone. Die gepinnte deutsche Basis hat 134 Ausgaben und keine echten Ortseingangs-/Ortsausgangsausgaben. Piktogramme und Zuordnungstabellen ergänzen keine Modellparameter. Die Bildbeispiele sind Referenzzeichen und ein realer Crop, keine hier neu gemessenen Vorhersagen.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/iphone/SpeedConsumerApp/TSRModelPacks/DE.panoramax-bootstrap.tsrmodelpack/manifest.json
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/manifest.json
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/shared/tsr/prolix-de-class-catalog-v1.json
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/deploy/prolix/models.json

## 17. OCR: Zusatztafeln lesen (31–33 Min.)

Die gezeigten Texte sind menschliche Referenztexte echter Testausschnitte. Sie werden nicht als frisch gemessene OCR-Ausgaben ausgegeben. Die Server-OCR läuft seit dem bestätigten Oktober-18-Cutover resident auf dem KI-Server. Rohtext, Konfidenz und Herkunft bleiben getrennte Belege. „Bei Nässe“ zu lesen beweist nicht, dass es nass ist.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_SUPPLEMENTARY_OCR_2026-10-16.md
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/docs/youspeed/KI_OCR_SERVICE.md
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/docs/youspeed/operations-evidence/2026-10-18-ki-ocr/cutover-receipt.json

## 18. Spuren erkennen und sichtbar machen (33–36 Min.)

Der Vergleich zeigt reale Straßenbilder mit gespeicherten Pipeline-Ausgaben, keine für die Vorlesung gezeichneten Linien. Links frühere Punkt-/Kurvendarstellung, rechts begrenzte kubische Bézier-Kurven. Das ist ein Darstellungsvergleich, kein Beweis höherer Detektionsgenauigkeit. Die heutige klassische Basis ist der Vergleichspunkt für gelernte Modelle.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/LANE_DETECTION_TECHNICAL_REPORT.tex
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/shared/lanes/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/shared/tsr/path-evidence/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/store/artwork/dashcam-preview.json
- https://github.com/volzinnovation/youspeed.de/blob/main/docs/LANE_BEZIER_AND_CALIBRATION_REVIEW_2026-09-30.md

## 19. Echtzeit: Hertz, Millisekunden und Weg (36–39 Min.)

Hz beschreibt die Verarbeitungsfrequenz, Latenz die Zeit bis zur Entscheidung. 10 Hz garantiert deshalb nicht automatisch 100 ms Ende-zu-Ende-Latenz. Das TSR-Ziel ist adaptiv 2–10 Hz bei p95 unter 250 ms; mindestens 15 FPS beziehen sich auf die gemeinsame Kamera-/Vorschauanforderung. Rechenbeispiele sind abgeleitet, keine Messwerte. Bildvorbereitung, Inferenz und Nachverarbeitung zusammen messen. Alte Frames verwerfen statt eine Warteschlange aufzubauen.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/VIDEO_TRAFFIC_SIGN_RECOGNITION_YOLO_SPEC.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/ROAD_PATH_ANDROID_BENCHMARK.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/LANE_DETECTION_TECHNICAL_REPORT.tex

## 20. Überwachtes Lernen: Trainings- und Testschleife (39–41 Min.)

Menschen erzeugen die Zielwerte. Trainingsdaten verändern Gewichte; Validierungsdaten helfen bei Modell- und Parameterwahl. Der Test bleibt bis zur finalen Auswahl unberührt. Fehleranalyse fließt in neue Daten und eine nächste Version ein. Die gewählte Modellversion wird sowohl serverseitig in Prolix/PyTorch beziehungsweise OCR-Diensten als auch als Core-ML-/LiteRT-Export evaluiert. Verschiedene Fahrten und Orte zusammenhalten, damit keine Nachbarframes in Training und Test landen.

Quellen:

- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/docs/prolix-ki-server-runbook.md
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/docs/youspeed/KI_OCR_SERVICE.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_TRAINING_ROUND_TRIP.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_EXPORT_AND_SOURCE_PROVENANCE.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_TRAINING_ROUND_TRIP.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_EXPORT_AND_SOURCE_PROVENANCE.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/inspector/README.md

## 21. Ziel-Datenbank: Sichtungen, Crops und Prüfung (41–44 Min.)

Die zentrale YouSpeed-Datenbank ist PostgreSQL/PostGIS. Sie ist von Panoramax und den Smartphone-SQLite-Bundles getrennt. Events, Bilder, Modellidentität und menschliche Prüfungen bleiben nachvollziehbar. Eine GPS-Position beschreibt zunächst das Fahrzeug, nicht eine vermessene Schildposition. Der Screenshot zeigt vorhandene reale Crops. Keine Bewertung wird nur zum Erstellen der Folie gespeichert.

Quellen:

- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/commercial_backend/youspeed/migrations/001_youspeed.sql
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/commercial_backend/youspeed/migrations/002_catalog_reviews.sql
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/commercial_backend/youspeed/migrations/009_panoramax_corpus.sql
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/docs/youspeed/PANORAMAX_CORPUS.md

## 22. Datenbestand nach Modellland (44–46 Min.)

Stand 18.10.2026, 11:44 MESZ. Datensätze, keine Zahl unterschiedlicher physischer Schilder. Modellland ist die gespeicherte Zuordnung; BE* (33) weist Zuordnungskonflikte auf, Unklar* (36) eine mehrdeutige Länderzuordnung. Panoramax-Crops = importierter Bestand mit fertigem Crop; keine Anzahl aller Fotos der Instanz. App-Crops und App-Sightings einschließlich Replay/Altbestand. Panoramax und App-Bestand sind getrennte Quellen; Crops und Sightings sind nicht addierbar. Die neueste Panoramax-Synchronisation war noch nicht abgeschlossen; die Zahlen beschreiben den importierten Verwaltungsbestand am Snapshot. Die Foto-Gesamtzahl beträgt 6.467 Quellbilder mit fertigen importierten Crops. Eine deduplizierte Foto-Länderaufteilung ist im vorliegenden Export nicht verfügbar. Die Tabelle verwendet deshalb ausdrücklich Crop-Einheiten für Panoramax.

Quellen:

- Woladen.de-analytics/docs/youspeed/collection-evidence/2026-10-18/summary.json
- Woladen.de-analytics/docs/youspeed/collection-evidence/2026-10-18/panoramax/sign-statistics.json
- Woladen.de-analytics/docs/youspeed/collection-evidence/2026-10-18/mobile/sign-statistics.json
- Woladen.de-analytics/docs/youspeed/collection-evidence/2026-10-18/mobile/sighting-statistics.json

## 23. Agenda · Projektarbeit (46–47 Min.)

Übergang vom Systemverständnis zur konkreten Arbeit. Studierende müssen die Apps nutzen und Daten annotieren; eine native App selbst zu bauen ist für den Einstieg nicht erforderlich.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/README.md

## 24. Deadlines (47–49 Min.)

Die Termine sind die verbindlichen Kursvorgaben. Im wöchentlichen Standup erläutert jedes Team Fortschritt, Hindernisse und nächste Schritte. Zum Projektabschluss müssen Datenstand, Quellcode, Experimente und Modellartefakte nachvollziehbar vorliegen. Danach folgen die interne und die öffentliche Präsentation.

Quellen:

- Kursvorgaben von Prof. Dr. Raphael Volz, 18.10.2026

## 25. Projektmanagement mit Git und GitHub-Repos (49–51 Min.)

Git verwaltet lokale Historie. GitHub hostet Repositories, Issues, Reviews und automatisierte Checks. Ein Fork liegt beim Team, ein Clone auf dem Rechner. origin ist der Team-Fork; upstream das Original. Ein Pull Request schlägt Änderungen vor und ist noch keine Freigabe oder Bereitstellung.

Quellen:

- https://docs.github.com/en/get-started/using-git/about-git
- https://docs.github.com/en/pull-requests/working-with-forks/about-forks

## 26. Zwei eigene Forks je Team (51–53 Min.)

TEAM ist ein Platzhalter. Jede Gruppe nutzt eigene Konten und beide Forks. Das Analytics-Repository ist privat; die Organisation muss private Forks erlauben. Kein privates Repository veröffentlichen, um diese Einschränkung zu umgehen. Branch-Regeln beider Repositories lesen; sie sind nicht identisch.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/AGENTS.md
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/AGENTS.md
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/README.md
- https://docs.github.com/en/pull-requests/how-tos/work-with-forks/configuring-a-remote-repository-for-a-fork

## 27. Aufgaben und Ergebnisse nachvollziehbar halten (53–55 Min.)

Eine gute Abgabe ist mehr als ein Gewichtsfile. Sie benennt Frage, Datenstand, Baseline, Vorgehen und gemessene Verbesserung. Änderungen klein halten und im Review verständlich begründen. Aufnahmen, Tokens und große Artefakte gehören nicht unüberlegt in Git. Upstream-Publikation oder Serverdeployment folgt einem eigenen freigegebenen Verfahren.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/AGENTS.md
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/AGENTS.md
- https://docs.github.com/en/get-started/using-github/github-flow

## 28. Apps installieren und Version prüfen (55–57 Min.)

Für die erste Datensammlung genügt eine vom Kurs vorgesehene App-Version. Die Studierenden müssen die App nicht selbst entwickeln oder kompilieren. Vorher die tatsächlich installierte Version prüfen, weil öffentliche Stores und Entwicklungsversion unterschiedlich sein können. Ein Android-Download benötigt die zum Gerät passende Architektur.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/android/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/iphone/SpeedConsumerApp/README.md
- https://youspeed.de/
- https://github.com/volzinnovation/youspeed.de/releases/tag/android-v1.3

## 29. Vor der ersten Aufnahme (57–59 Min.)

Einrichtung im Stand durchführen. Die Kamera kann Zeichen erkennen, ohne Video zu speichern. Für Projekt A Straßenfotos, für Projekt B lokale Dashcam-Videos vorbereiten. Speicherplatz, Orientierung und Zeitbezug überprüfen. Nach der Testfahrt einen Clip beziehungsweise ein Foto öffnen, bevor größere Datensammlungen beginnen.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/FIRST_RUN_WALKTHROUGH.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/USER_GUIDE.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/MANUAL_ORIENTATION.md

## 30. Panoramax: Aufnahme und Upload (59–62 Min.)

Links ist der aktuelle Bildschirm des am 18.10.2026 angeschlossenen iPhones zu sehen, über QuickTime als Vorschau erfasst. Der Pfeil zeigt auf den zweiten Button von links: die automatische Panoramax-Fotoaufnahme ein-/ausschalten. Im Bild ist sie ausgeschaltet, erkennbar am durchgestrichenen Kamerasymbol. Der dritte Button öffnet die Galerie. Die weiteren Bilder zeigen echte native App-Galerien mit synthetischen Test-Thumbnails. iPhone: blauer Upload-Pfeil unten rechts. Android: Upload (1), im gezeigten Zustand mangels verbundenem Konto deaktiviert. Studierende verwenden ihre eigenen Kurskonten. Aufnahme stoppen, Galerie öffnen, Bilder prüfen und auswählen, Konto mit der Instanz verbinden, Upload bewusst auslösen und bestätigen. Upload startet weder beim Stoppen noch beim Verbinden eines Kontos automatisch. Fortschritt prüfen und Sequenz-IDs für die Annotation notieren. Dashcam-Videos bleiben lokal. Bilder anschließend im Panoramax-Webviewer annotieren.

Quellen:

- Aktueller Screenshot des angeschlossenen iPhones, QuickTime-Vorschau, 18.10.2026
- https://github.com/volzinnovation/youspeed.de/blob/main/iphone/SpeedConsumerApp/MainView.swift#L585
- https://github.com/volzinnovation/youspeed.de/blob/main/docs/PANORAMAX_CAPTURE_FOUNDATION.md
- https://github.com/volzinnovation/youspeed.de/blob/main/iphone/SpeedConsumerApp/Assets.xcassets/onboarding-photo-review.imageset/onboarding-photo-review.png
- https://github.com/volzinnovation/youspeed.de/blob/main/android/app/src/main/res/drawable-nodpi/onboarding_photo_review.png

## 31. Panoramax: Zeichen menschlich annotieren (62–65 Min.)

Der sichtbare Rahmen und die gespeicherte Semantik gehören zum Bild. Panoramax nutzt osm|traffic_sign; OSM selbst traffic_sign. Wo ein Rahmen bereits vorhanden ist, dessen Semantik korrigieren statt ein Duplikat anzulegen. Die erforderlichen Bearbeitungsrechte und UI-Controls vorher mit dem Kurskonto prüfen. Zum Screenshot werden keine neuen Labels oder Prüfungen gespeichert.

Quellen:

- https://docs.panoramax.fr/tags/
- https://docs.panoramax.fr/backend/install/deep_dive/semantics/
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_PROLIX_ALIGNMENT_2026-09-10.md

## 32. Inspector: Beobachtungen gemeinsam prüfen (65–67 Min.)

Der Inspector verbindet Datei- und Datenbankansichten. Eine Modellvorhersage wird nicht automatisch zur menschlichen Wahrheit. Originalerkennung, Klassenprüfung und Ausfahrtkontext bleiben unterscheidbar. Die lokale Spurannotation funktioniert auch ohne private Backend-Zugangsdaten. Im Kurs werden passende Leserechte bereitgestellt.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/inspector/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/inspector/server.py

## 33. Spuren im Inspector annotieren (67–70 Min.)

Der Editor arbeitet auf tatsächlich dekodierten Frames und PTS. Vier Punkte definieren eine kubische Bézier-Kurve. Gestrichelte Kurven beschreiben den Markierungspfad einschließlich der Lücken, keine Lack-Pixelmaske. Kopierte Annotationen bleiben Entwürfe. Nur geprüfte Samples kommen in die Split-Listen. Bei fehlendem FFmpeg das vorbereitete ZIP importieren und gespeicherte Frames öffnen.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/inspector/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/tests/inspector/fixtures/lane-dataset-v1/manifest.json

## 34. Labels, Datenaufteilung und Qualität (70–72 Min.)

Zufälliges Aufteilen von Nachbarframes überschätzt häufig die Qualität. Die gleiche physische Ortstafel oder derselbe Straßenabschnitt darf nicht unbemerkt auf beiden Seiten des Tests stehen. Seltene Klassen, schwierige Sichtverhältnisse und echte negative Bilder berücksichtigen. Menschliche Labels stichprobenartig gegenseitig prüfen.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/inspector/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/scripts/inspector/lane_dataset_loader.mjs
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_TRAINING_ROUND_TRIP.md

## 35. Wie messen wir eine Verbesserung? (72–74 Min.)

Qualität anhand der tatsächlichen Zielrepräsentation messen. Boxen, Klassen, Kurven und Masken benötigen unterschiedliche Metriken. Die reale Fehlerauswertung zeigt, warum eine plausible Linie trotzdem die falsche Straßenkante sein kann. Zahlen stets mit Fallzahlen und Datenbedingungen berichten. Der Test bleibt unabhängig; kein Nachjustieren am Testergebnis.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_TRAINING_ROUND_TRIP.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_EXPORT_AND_SOURCE_PROVENANCE.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/inspector/README.md
- https://github.com/volzinnovation/youspeed.de/blob/main/docs/LANE_FRAGMENT_EVALUATION_2026-10-01.md

## 36. Dieses Semester: zwei Projekte, vier Teams (74–76 Min.)

Jeweils zwei Teams bearbeiten dasselbe Problem mit eigenen Experimenten. Die Gruppen vereinbaren gemeinsame Label-Regeln, teilen überprüfte Daten nach Kursvorgabe und vergleichen unter identischen Testbedingungen. Ein gemeinsam festgelegter Test wird nicht für Training oder Modellauswahl benutzt. Am Ende Ergebnisse und Fehlerbilder zwischen den Teams diskutieren.

Quellen:

- https://github.com/volzinnovation/youspeed.de
- https://github.com/volzinnovation/Woladen.de-analytics

## 37. Modelle auf Server und Geräten erproben (76–78 Min.)

Das Servermodell gehört ausdrücklich zum Ergebnis: Gewichte und Pipeline in Prolix beziehungsweise passendem KI-Dienst. Mobile Exporte müssen Labelreihenfolge, Preprocessing und Geometrie erhalten. Erst auf gespeicherten Beispielen, dann auf bereitgestellten Testgeräten prüfen. Native App-Entwicklung ist kein Einstiegserfordernis; die Integration erfolgt mit der vorhandenen Projektstruktur. Produktion wird separat freigegeben.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/AGENTS.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_EXPORT_AND_SOURCE_PROVENANCE.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/shared/tsr/model-pack.schema.json
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/shared/lanes/README.md

## 38. Projekt A · Ortstafeln menschlich labeln (78–81 Min.)

A1 und A2 starten mit menschlichen Labels auf eigenen Bildern. Den sichtbaren Schildtyp und die Fahrtrichtung korrekt unterscheiden. Verdeckte, kleine oder rückseitige Schilder als unsicher oder passende Negativbeispiele behandeln. Die Bernbach-Aufnahme ist ein vorhandenes historisches Fehlerbeispiel, kein unabhängiger Genauigkeitsnachweis. Abgabe umfasst Manifest, Labelprotokoll, Gegenprüfung und Splitübersicht.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_PROLIX_ALIGNMENT_2026-09-10.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/android/app/src/androidTest/assets/tsr-city310-bernbach.json
- https://wiki.openstreetmap.org/wiki/Tag:traffic_sign=DE:310

## 39. Projekt A · Erkennung verbessern (81–83 Min.)

Klassenvokabular und tatsächliche Gewichte müssen erweitert werden. Die vorhandenen Piktogramme reichen dafür nicht. Detector-Recall und Klassifikation getrennt untersuchen. Masken entstehen erst mit geeigneter zusätzlicher Annotation. Tests umfassen Fehlalarme, neue Klassen und bekannte Verkehrszeichen. Geltende Laufzeitregeln werden nicht nebenbei umgeschrieben.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/shared/tsr/prolix-de-class-catalog-v1.json
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_PROLIX_ALIGNMENT_2026-09-10.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/TSR_EXPORT_AND_SOURCE_PROVENANCE.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/shared/speed-limit-reference/AGENTS.md

## 40. Projekt B · Menschliche Spur-Labels (83–86 Min.)

B1 und B2 beginnen mit überprüften Kurvenlabels statt mit Modelltraining ohne Zielwerte. Alle relevanten sichtbaren Markierungen konsistent annotieren, kopierte Kurven erneut prüfen. Das exportierte ZIP ist die portable Sicherung; die Originalvideos bleiben getrennt. Schatten, Dämmerung und abgefahrene Markierungen liefern besonders interessante Fehlerfälle.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/inspector/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/scripts/inspector/lane_dataset_loader.mjs
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/shared/lanes/README.md

## 41. Projekt B · Lernen, testen und bereitstellen (86–88 Min.)

Zielrepräsentation passend zu den vorhandenen Kurven wählen. Abgeleitete Rasterlabels sind von echten manuell geprüften Pixelmasken zu unterscheiden. Jede Verbesserung muss auf unabhängigen Daten sowie unter Laufzeitbedingungen bestehen. Teams liefern nachvollziehbaren Quellcode in ihren Forks und dokumentierte Modellartefakte.

Quellen:

- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/shared/lanes/README.md
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/docs/LANE_DETECTION_TECHNICAL_REPORT.tex
- https://github.com/volzinnovation/youspeed.de/blob/c1ee94a68c6e13b9371d64b15aa758379746896d/AGENTS.md
- https://github.com/volzinnovation/Woladen.de-analytics/blob/db87b591e8a0ded8435925077f769f20d1a8b037/AGENTS.md

## 42. Nur Fragen? (88–90 Min.)

Offene Fragen der Studierenden klären.

Quellen:



