# Build 10053 — 19 October 2026

This update fixes driving-control visibility, the manual-photo layout and the iPhone speed-limit sign size. Ordinary controls require the phone to be face-up within ±10° of horizontal and speed at or below 20 km/h. The driving photo occupies the Settings position without shifting the action row.

Camera traffic-sign recognition now pauses after sunset and uses the installed map bundles; daylight is calculated offline from location and UTC time. The Gernsbach tunnel matcher now follows normalized tunnel portal connections in existing bundles.

Bitte bei der nächsten Testfahrt prüfen: Bedienelemente nur bei flach liegendem Telefon und höchstens 20 km/h, Foto anstelle von Einstellungen, große Geschwindigkeitsanzeige auf dem iPhone, Gernsbacher Tunnel sowie Karten-Fallback bei Nacht. Einstellungen vor der Fahrt vornehmen; Aufnahmen und Logs nach sicherem Anhalten prüfen.

Validation: Android unit tests (715, one existing skip), 18 attached-device tests, 18 focused iPhone unit/controller tests and three iPhone UI test methods passed. Protected reference-policy checks passed (39 scenarios, 171 steps). Recorded Gernsbach replay recovered 86 tunnel matches. Fresh drive verification remains pending.

---

# YouSpeed 1.4 alpha

18 October 2026 · iPhone **1.4 (10052)** · Android **1.4-alpha**, base build **10052**

This prerelease prepares YouSpeed 1.4 for three further test drives in daylight and at night. It is a testing build; the final 1.4 production release has not been submitted.

## English

### What changed

- **Clearer capture controls:** control dashcam recording, sign recognition and Panoramax photo capture independently. Manual street-photo capture is available again without stopping an active dashcam session.
- **Supplementary-sign OCR:** capture text associated with supplementary traffic signs and retain its diagnostic evidence. Readability and recognition still depend on the scene, device and installed models; OCR does not guarantee that a condition has been interpreted correctly.
- **Traffic-sign contributions:** with contribution permission, share sightings and automatically selected cropped sign photos with the private sign database. The daily collection plan selects useful crop classes; negative examples are always selected. Collection can use mobile data, and offline crops can wait locally for up to seven days. Recognition remains available if contribution permission is declined.
- **More reliable photo review and uploads:** improved Panoramax batch visibility, upload state handling and capture transitions. Full street photos still require review, selection and an explicit Panoramax upload. Sign-database contributions and Panoramax photo publication are separate flows.
- **Better data management:** improved map/list views, download and storage information, queued/failed status labels and source attribution.
- **iPhone/Android consistency:** aligned capture controls, daily crop selection, startup behavior and canonical traffic-sign class identifiers.
- **Updated reference material:** refreshed app screenshots, localized store notes and teaching material for the student test programme.

### Please test

Before starting, install the intended build, download the route's maps and recognition models, and check storage and camera permissions while parked. Record the platform, build, route, start/end time and whether the drive was in daylight, dusk or darkness.

For each of the three drives, check speed-limit changes, town entry/exit, supplementary text, and recognition stability. Where practical, compare both phones on the same route. Set the required recording modules before departure; a passenger may observe, but the driver must not operate the app while moving.

After stopping safely, check that dashcam videos play, manually captured photos exist, galleries retain the expected batches, and selected Panoramax uploads complete. Note the collection IDs and keep diagnostic logs for any crash, missing recording, unexpected warning or platform difference. Check contribution consent and offline/reconnection behavior separately from Panoramax uploads.

### Current limits

- Camera recognition, OCR, map data and penalty estimates can be incomplete or wrong. Road signs and traffic rules take precedence.
- Simulator and unit checks do not establish real-device camera performance or night-drive acceptance. Those remain the purpose of this alpha test.
- External TestFlight distribution requires Apple's beta approval. The invitation link can show the previously approved build until 1.4 is approved.
- This release does not change the protected speed-limit-reference state-machine policy.

## Deutsch

### Was ist neu?

- **Klarere Aufnahmesteuerung:** Dashcam, Schilderkennung und Panoramax-Fotoaufnahme lassen sich unabhängig steuern. Manuelle Straßenfotos sind wieder möglich, ohne eine laufende Dashcam-Aufnahme zu beenden.
- **OCR für Zusatzschilder:** Text zu Zusatzschildern wird zusammen mit Diagnosebelegen erfasst. Lesbarkeit und Erkennung hängen weiterhin von Situation, Gerät und Modellen ab; erkannter Text garantiert keine korrekte Auslegung einer Bedingung.
- **Beiträge zur Zeichendatenbank:** Mit Zustimmung werden Sichtungen und automatisch ausgewählte Zeichen-Crops an die private Datenbank übertragen. Der tägliche Sammelplan wählt relevante Klassen; Negativbeispiele werden immer ausgewählt. Der Upload kann mobile Daten nutzen. Offline können Crops bis zu sieben Tage lokal warten. Schilderkennung funktioniert auch ohne Beitragsfreigabe.
- **Verbesserte Fotogalerie und Uploads:** besser sichtbare Panoramax-Batches, überarbeitete Upload-Zustände und Aufnahmeübergänge. Vollständige Straßenfotos werden weiterhin erst nach Prüfung, Auswahl und ausdrücklich gestartetem Panoramax-Upload übertragen. Zeichendatenbank und Panoramax sind getrennte Abläufe.
- **Verbesserter Datenmanager:** Karten- und Listenansichten, Angaben zu Downloads und Speicher, Warteschlangen-/Fehleranzeigen sowie Quellenangaben wurden verbessert.
- **Abgestimmtes Verhalten auf iPhone und Android:** Aufnahmefunktionen, tägliche Crop-Auswahl, Startverhalten und eindeutige Zeichenklassen wurden angeglichen.
- **Aktualisierte Unterlagen:** neue App-Screenshots, lokalisierte Store-Hinweise und Lehrmaterial für die studentischen Testfahrten.

### Bitte bei den drei Testfahrten prüfen

Im Stand den richtigen Build installieren, Karten und Modelle laden sowie Speicher und Berechtigungen kontrollieren. Gerät, Build, Strecke, Beginn/Ende und Lichtverhältnisse dokumentieren. Auf Tempowechsel, Ortseingang/-ausgang, Zusatztexte und stabile Erkennung achten; nach Möglichkeit beide Geräte auf derselben Strecke vergleichen. Während der Fahrt bedient der Fahrer die App nicht.

Nach sicherem Anhalten Videos abspielen, manuelle Fotos und erhaltene Galerie-Batches prüfen sowie ausgewählte Panoramax-Uploads abschließen. Collection-IDs und Diagnoseprotokolle für Fehler sichern. Beitragsfreigabe und Offline-/Wiederverbindungsverhalten getrennt vom Panoramax-Upload prüfen.

Erkennung, OCR, Kartendaten und Bußgeldschätzungen können falsch oder unvollständig sein. Die Nachtfahrten und die Prüfung auf echten Geräten stehen noch aus. Für externe TestFlight-Tester muss Apple 1.4 erst freigeben; bis dahin kann der Einladungslink den bisherigen freigegebenen Build anbieten. Die geschützte Tempolimit-Referenzrichtlinie bleibt unverändert.

## Installation and distribution

- Android alpha: [GitHub prerelease](https://github.com/volzinnovation/youspeed.de/releases/tag/android-v1.4-alpha).
- iPhone: [TestFlight invitation](https://testflight.apple.com/join/k3a1pgce).
- Course photo service: [panoramax.youspeed.de](https://panoramax.youspeed.de).

For actual publication and verification status, use the dated [release handoff](RELEASE_1.4_ALPHA_2026-10-18.md). These release notes describe the alpha scope, not a claim of completed field acceptance.
