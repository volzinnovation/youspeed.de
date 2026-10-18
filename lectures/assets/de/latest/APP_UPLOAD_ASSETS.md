# Wiederverwendete App- und Aufnahmebilder

Alle Dateien sind bytegleiche Kopien bereits vorhandener Projektdateien. Keine UI wurde gezeichnet oder verändert.

## Upload-Ablauf (Textvorschlag auf Deutsch)

1. Recorder nach der Fahrt stoppen und die Bildergalerie öffnen.
2. Fotos groß öffnen, prüfen und unerwünschte Bilder abwählen oder lokal löschen.
3. Gewünschte Fotos auswählen; Favoriten schützen vor automatischer Bereinigung.
4. Eigenes Panoramax-Konto in den Einstellungen mit der Instanz verbinden.
5. Upload-Pfeil (iPhone) bzw. „Hochladen (n)“ (Android) betätigen und bestätigen.
6. Fortschritt je Serie in der Galerie verfolgen; unterbrochene/fehlgeschlagene Uploads später fortsetzen.

Der Upload beginnt ausdrücklich durch die Nutzeraktion nach dem Aufnahmestopp. Er startet nicht automatisch beim Stoppen, bei wiederkehrender Verbindung oder beim Verbinden des Kontos. Dashcam-Videos bleiben lokal; Panoramax erhält ausgewählte Fotos mit GPS-Standort.

Quellen: `docs/PANORAMAX_CAPTURE_FOUNDATION.md:30–37`; `iphone/SpeedConsumerApp/de.lproj/Localizable.strings:341–357`; `android/app/src/main/res/values-de/strings.xml:81–87`.

## Bilder

### iphone-panoramax-review-upload.png

Echte native iPhone-Galerie: ausgewähltes Foto und Upload-Pfeil rechts unten. UI Englisch; Thumbnail ist eine synthetische Testaufnahme. Zeigt Auswahl und Upload-Steuerung, keinen erfolgreichen Upload.

- Quelle: `iphone/SpeedConsumerApp/Assets.xcassets/onboarding-photo-review.imageset/onboarding-photo-review.png`
- Größe: 1320 × 2868
- SHA-256: `3e45c84678b51363a587d36f34bea6e0510e2d3130068d02760558bc63b923a7`

### android-panoramax-review-upload.png

Echte native Android-Galerie: ausgewähltes Foto und Upload (1). UI Englisch; synthetische Testaufnahme. Upload-Schaltfläche ist deaktiviert; kein verbundenes Konto und kein erfolgreicher Upload dargestellt.

- Quelle: `android/app/src/main/res/drawable-nodpi/onboarding_photo_review.png`
- Größe: 1080 × 1920
- SHA-256: `be0d43a2495e89f501ce189dd7d73382c30631c4bce5b5f340e71357bbfc8a56`

### android-panoramax-review-de.png

Echter Screenshot des Android-Geräts vom 26.09.2026: deutsche Fotogalerie mit Prüfen/Favorit/Auswahl und Hochladen (0). Kein Bild ausgewählt; Vorschau dunkel; Upload deaktiviert. Älterer UI-Stand.

- Quelle: `.codex-tmp/device-diagnosis-2026-09-25/android/deployment/final-ui/gallery-portrait.png`
- Größe: 1220 × 2712
- SHA-256: `fd257668ec696b35c9a1e367a229b2176edd90ce79d13a938eb0969ff85bc143`

### iphone-local-video-gallery.png

Echte native iPhone-Galerie, Videos-Tab: lokales Video, Teilen, Löschen. UI Englisch. Passt zu Spalte Dashcam/lokale Videos; kein Panoramax-Upload.

- Quelle: `iphone/SpeedConsumerApp/Assets.xcassets/onboarding-dashcam.imageset/onboarding-dashcam.png`
- Größe: 1320 × 2868
- SHA-256: `b26199b76819321f97c965eb590b75b247368450b62fc1cc3bf6bc029ba26f08`

### android-local-video-gallery.png

Echte native Android-Galerie, Videos-Tab: lokales Video, Play und Share. UI Englisch. Alternative für Spalte Dashcam/lokale Videos.

- Quelle: `android/app/src/main/res/drawable-nodpi/onboarding_video_library.png`
- Größe: 1080 × 1920
- SHA-256: `783bd4bbd326a023a814bb11373f94a89264a86f04a4a10250552ce737d65e9d`

### dashcam-real-road-frame.png

Unveränderter vorhandener Bildausschnitt aus einer echten Dashcam-Aufnahme, 5,5 Sekunden; keine App-Steuerelemente. Als anschauliches Ergebnis eines lokalen Videos geeignet.

- Quelle: `store/artwork/source/real-dashcam-5.5s.png`
- Größe: 3840 × 2160
- SHA-256: `d9b504dc1ca06a9f144d83ef65e18c40b9880425b386ff1d24128ec7701a5e7f`

### inspector-crops-existing.png

Bereits im Vortrag vorhandener echter Inspector-Screenshot mit Backend-Crops und Zeichenklasse prüfen; deutsch. Als Bild für Sichtungen/Ausschnitte geeignet.

- Quelle: `lectures/assets/de/inspector-crops.png`
- Größe: 1280 × 720
- SHA-256: `c70ac9aca4f0a2f3523e6ed8bf55c4144a36bd7529ad956187d47f187134ce55`


## Neuer aktueller Gerätescreenshot

### iphone-live-panoramax-camera-2026-10-18.png

Am 18.10.2026 vom angeschlossenen iPhone über QuickTime als Vorschau erfasst, ohne neue Filmaufnahme. Unveränderte Originaldatei, 1004 × 2168 Pixel. Der zweite untere Button von links steuert die automatische Panoramax-Fotoaufnahme. Der Screenshot zeigt den ausgeschalteten Zustand mit durchgestrichenem Kamerasymbol. Der Pfeil auf Folie 30 ist ein separates bearbeitbares Folienelement.

- Funktionsquelle: `iphone/SpeedConsumerApp/MainView.swift:585–620`, zweite Position bei Zeile 681
- SHA-256: `10523c4748cc108894184f075ea37f2b03c5231791287ddc4ffe69c3caba2ecc`
