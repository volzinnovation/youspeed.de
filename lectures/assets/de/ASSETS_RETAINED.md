# Wiederverwendete Projektbilder

Alle aufgeführten Dateien sind unveränderte Kopien bereits vorhandener Projektartefakte. Quellen und SHA-256 stehen in `retained-assets.json`. Keine Linien wurden für die Vorlesung erfunden oder neu gezeichnet.

## Spurerkennung

- **lane-bezier-comparison.png** (1280 × 876): Vergleich der früheren Punkt-/Kurvendarstellung und der begrenzten kubischen Bézier-Darstellung auf denselben veröffentlichten Detektionen. Grüne Linien sind echte gespeicherte Pipeline-Ausgaben. Zwei reale Straßenbilder bei Video 14:00 und 21:00. Es handelt sich um eine Offline-Visualisierung und nicht um einen Screenshot der laufenden App oder einen Genauigkeitsgewinn. Quelle: `docs/LANE_BEZIER_AND_CALIBRATION_REVIEW_2026-09-30.md`, ignoriertes Projektartefakt `inspector/logs/2026-09-30-lane-shadow-review/bezier-before-after.png`.
- **lane-live-overlay-contact.jpg** (2560 × 2520): Auswahl realer Dashcam-Frames des iPhone 14 Pro, Build 10024, 1. Oktober 2026. Grüne Linien rekonstruieren die tatsächlich protokollierten sichtbaren Grenzen. Bild/Log-Abgleich über ungefähren Aufnahme-Callback, nächste Logzeile innerhalb 80 ms; keine exakte Sensorexpositions-Synchronisierung. Quelle: `docs/LANE_DRIVE_REVIEW_2026-10-01.md`, `inspector/logs/2026-10-01-drive-review/review_video.py`. Geeignet für die Erklärung verbleibender Lücken bei gestrichelten Markierungen; keine Genauigkeitsbehauptung aus reiner Ausgabehäufigkeit ableiten.
- **lane-holdout-failure.jpg** (1920 × 1080): Vier Varianten auf einem zurückgehaltenen realen Dämmerungsbild. **Grün: menschliche Markierung; Rot: sichtbare Modell-/Pipeline-Ausgabe.** Beispiel für die falsche Auswahl der gegenüberliegenden Straßenkante, obwohl die Geometrie plausibel aussieht. Quelle: `docs/LANE_FRAGMENT_EVALUATION_2026-10-01.md` und `docs/LANE_FRAGMENT_IMPLEMENTATION_2026-10-01.md`.
- **lane-heldout-six-arm.jpg** (1920 × 1620): Sechs Varianten desselben zurückgehaltenen Tageslichtbilds. Grün sind menschliche Labels, Rot sind Pipeline-Ausgaben. Zeigt auch noch vorhandene Fehler und eignet sich für das Lernziel einer unabhängigen Evaluation. Quelle: `docs/LANE_NEXT_EVALUATION_2026-10-01.md`.

Die Rohvideos dieser Bilder wurden laut Repository-Anleitung im privaten Datensatz archiviert. Die abgeleiteten Bilder sind noch lokal vorhanden und wurden wiederverwendet. Ein optionaler 60-Sekunden-Film ist gezielt restaurierbar:

- Ursprüngliches Artefakt: `inspector/logs/2026-09-30-lane-stability-implementation/preview-comparison.mp4`
- Inhalt: Vergleich gespeicherter Offline-Polylinien; **kein** Live-UI-Video, **kein** gemessener Qualitätsbeweis.
- Remote: `device-backups/2026-10-01/objects/198697849603850e9f65f519ef704b709bf3833167cf1642746b3c5da48ed7a0.mp4`
- SHA-256: `198697849603850e9f65f519ef704b709bf3833167cf1642746b3c5da48ed7a0`
- Größe: 37.223.325 Bytes
- Datensatz: `loffenauer/youspeed.de`, Revision `bd12056313e00acc790d25ebe5486aac11f4cf79`; siehe `docs/DEVICE_EVIDENCE_BACKUP_2026-10-01.md`.

## OCR-Bildbeispiele

Die drei PNGs stammen unverändert aus den öffentlichen Panoramax-Testbildern in `tests/fixtures/tsr-ocr-32`. Sie zeigen den Hauptverkehrszeichen-Ausschnitt samt Zusatztafel. Die folgenden Texte sind der **erwartete menschliche Referenztext** aus dem Manifest, nicht als neu gemessenes OCR-Ergebnis ausgeben:

| Bild | Erwarteter Text | Panoramax picture_id |
| --- | --- | --- |
| ocr-laermschutz.png | Lärmschutz | 53ebefcf-6c89-4e34-8b83-7d1198228059 |
| ocr-time.png | 22-6h | 339527d6-2466-4476-ac67-0d477f1212d2 |
| ocr-distance.png | 150m | 59fd8c79-88fb-472e-9210-c79c82e5185b |

Quelle: `tests/fixtures/tsr-ocr-32/manifest.json` und dessen README. Diese Beispiele bleiben Vorlesungs-/Testmaterial und gehören nicht in produktive App-Ressourcen.
