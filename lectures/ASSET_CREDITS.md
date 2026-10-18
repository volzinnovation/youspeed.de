# Bildnachweise und Quellenstand

**KI für intelligente Mobilität · Prof. Dr. Raphael Volz · 19. Oktober 2026 · Neufassung v6**

Die Sprechernotizen enthalten pro Folie die fachlichen Quellen. Grundlagen wurden am 18. Oktober 2026 gegen das Projekt geprüft. Neue Bildschirmaufnahmen stammen ebenfalls vom 18. Oktober. Quellstände: YouSpeed `c1ee94a68c6e13b9371d64b15aa758379746896d`, Analytics `db87b591e8a0ded8435925077f769f20d1a8b037`. Die vorhandene lokale Änderung am OCR-Bericht wurde nicht verändert.

## Neue Bildschirmaufnahmen

- `assets/de/youspeed-website.png`: aktuelle [Projektwebsite](https://youspeed.de/), unveränderte Browseraufnahme.
- `assets/de/osm-pforzheim.png`: [OpenStreetMap-Karte Pforzheim](https://www.openstreetmap.org/#map=14/48.891/8.700), © OpenStreetMap-Mitwirkende, [ODbL](https://www.openstreetmap.org/copyright). Attribution bleibt auf Screenshot und Folie sichtbar.
- `assets/de/panoramax-annotations.png` und `panoramax-annotation-detail.png`: echte vorhandene Objektannotation im [Bernbach-Bild](https://panoramax.youspeed.de/?pic=a458609a-bbf1-413a-a039-5e0f685e9923&focus=pic). Bildautor/Provider **admin / panoramax.youspeed.de**, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Der aktuelle gespeicherte Tag `DE:310` und die ursprüngliche generische Detektion sind gemeinsam sichtbar. Es wurden zum Erstellen dieser Bilder keine Annotationen verändert.
- `assets/de/panoramax-upload.png`: Uploadansicht aus der angemeldeten Admin-Sitzung. Es wurde kein Foto ausgewählt oder hochgeladen. Die sichtbare Sprachauswahl wurde für die Aufnahme auf Deutsch gestellt.
- `assets/de/inspector-crops.png` und `inspector-detail.png`: echter lesender Zugriff auf den vorhandenen privaten Inspector und gespeicherte Projekt-Crops. Keine Prüfung oder Datenänderung wurde für den Screenshot gespeichert. Die abgebildeten Klassen sind Originalvorhersagen und nicht automatisch menschlich bestätigte Labels.

## Ergänzungen der Neufassung v6

`assets/de/latest/osm-tempo50-node-way.png` ist eine Browseraufnahme vom **18.10.2026** aus dem [OSM-Verkehrszeichenwerkzeug mit DE:274-50](https://trafficsigns.osm-verkehrswende.org/DE?signs=DE:274-50), sichtbarer Werkzeugstand **3.1.1**. Sie zeigt Tempo 50 und die im Werkzeug vorgeschlagenen Tags für Node und Way. Die Tag-Vorschläge sind ein Lehrbeispiel; das Bild belegt keine Änderung eines konkreten OSM-Objekts.

Die drei Highway-Renderingbilder stammen aus der Spalte „Rendering carto“ von [Key:highway im OpenStreetMap-Wiki](https://wiki.openstreetmap.org/wiki/Key:highway), abgerufen am **18.10.2026**. Die Originaldateien sind jeweils **125 × 125 Pixel**; die lokalen Dateinamen dienen nur der Zuordnung im Vortrag.

| Lokale Datei unter `assets/de/latest/` | Originaldatei und Nachweis |
| --- | --- |
| `highway-motorway.png` | [Rendering-highway_motorway_neutral.png](https://wiki.openstreetmap.org/wiki/File:Rendering-highway_motorway_neutral.png), Bildpfad `/w/images/6/6a/Rendering-highway_motorway_neutral.png` |
| `highway-primary.png` | [Rendering-highway_primary_neutral.png](https://wiki.openstreetmap.org/wiki/File:Rendering-highway_primary_neutral.png), Bildpfad `/w/images/d/d9/Rendering-highway_primary_neutral.png` |
| `highway-residential.png` | [Rendering-highway_residential.png](https://wiki.openstreetmap.org/wiki/File:Rendering-highway_residential.png), Bildpfad `/w/images/5/57/Rendering-highway_residential.png` |

Die Dateiseiten sind die jeweiligen Herkunfts- und Lizenznachweise. Die Primary-Dateiseite führt **Mabull** als Bearbeiter und kennzeichnet das einfache geometrische Rendering als **Public Domain**. Kartenattribution: © OpenStreetMap-Mitwirkende; [OSM-Urheberrechts- und Datenlizenzhinweise](https://www.openstreetmap.org/copyright). Die Renderingbeispiele zeigen den dokumentierten Kartenstil; andere Renderer können dieselben Tags anders darstellen.

Die vorhandenen nativen App-Galerien, lokalen Videoansichten, das reale Dashcam-Bild und die wiederverwendete Inspector-Ansicht sind mit ursprünglichen Projektpfaden in [APP_UPLOAD_ASSETS.md](assets/de/latest/APP_UPLOAD_ASSETS.md) dokumentiert. Die App-Galerien zeigen Auswahl und Upload-Steuerung, keinen nachgewiesenen erfolgreichen Upload. Teilweise sind synthetische Test-Thumbnails, englische Oberflächen oder deaktivierte Upload-Schaltflächen sichtbar; diese Einschränkungen bleiben bei der Erklärung erhalten. Der aktuelle Fotoupload wird durch die Nutzeraktion **in der App** ausgelöst.

## Statistikquelle der Neufassung v6

Die Tabelle zum Datenbestand verwendet [country-statistics.json](source/country-statistics.json), Snapshot **18.10.2026, 11:44 MESZ** aus den lokalen, quellkontrollierten Analytics-Exporten desselben Tages. Für die Vorlesung wurde keine zusätzliche Produktionsabfrage ausgeführt. Die vollständigen Definitionen und Provenienznachweise stehen in der JSON-Datei.

- **Modellland:** gespeicherte Modell-/Klassifikatorzuordnung; kein verifiziertes geographisches Aufnahmeland. Belgien hat Zuordnungskonflikte, „Unklar“ eine mehrdeutige Zuordnung.
- **Panoramax-Crops:** unterschiedliche importierte Crop-IDs aktiver Annotationen auf aktiven Quellbildern mit Status `ready`, aktuellem Crop-/Objektverweis und vorhandener Bildgeometrie; alle gespeicherten Sichtbarkeiten. Die Werte zählen fertige importierte Ausschnitte und keine Länderstatistik aller Panoramax-Fotos.
- **App-Crops:** alle gespeicherten mobilen Crop-Datensätze, einschließlich Replay-Installationen und inaktiver beziehungsweise abgelaufener Altbestände. Eine Sichtung kann mehrere Crops haben.
- **App-Sightings:** alle gespeicherten mobilen Beobachtungsereignisse mit `kind=sighting`, einschließlich Replay und Sichtungen ohne gespeicherten Crop. Der Bestand ist nicht auf aktive Galerieeinträge beschränkt.

Panoramax und App-Bestand sind getrennte Quellen. Crops und Sightings sind nicht addierbar und entsprechen keiner Anzahl unterschiedlicher physischer Schilder. Die letzte Panoramax-Synchronisation war beim Snapshot noch nicht abgeschlossen; die Tabelle beschreibt den damaligen importierten Verwaltungsbestand.

## Wiederverwendete Bilder

Die deutschen iPhone-/Android-Bilder kommen aus den bestehenden Store-Metadaten: `store/apple/screenshots/de-DE/iphone-6.9/02-camera-speed-limit.png`, `03-secondary-sign.png` und `store/android/listing/de-DE/phone-screenshots/02-dashcam.png`. Sie sind als Produktansichten gekennzeichnet. Das Dashcam-Artwork kombiniert echte Aufnahmepixel mit nativer Demonstrationsoberfläche; es ist kein neu aufgenommener Live-Screenshot.

Die echten Spurbilder und OCR-Ausschnitte wurden vor jeder Neuerstellung in vorhandenen Projektartefakten gesucht. Detaillierte Herkunft, historische Builds und Einschränkungen stehen in [ASSETS_RETAINED.md](assets/de/ASSETS_RETAINED.md), die Quellpfade und Prüfsummen in [retained-assets.json](assets/de/retained-assets.json). Grüne Linien im Darstellungsvergleich sind gespeicherte Pipeline-Ausgaben; Grün/Rot im zurückgehaltenen Fehlerbeispiel bedeutet menschliche Referenz/Pipeline-Ausgabe. Die drei OCR-Texte sind menschliche Referenztexte vorhandener Testausschnitte, keine neu gemessenen Erkennungsergebnisse.

Das Straßenfoto auf dem Titel stammt unverändert aus `store/artwork/source/real-dashcam-5.5s.png`; die Folie beschneidet lediglich den sichtbaren Bildbereich. Aufnahmeherkunft und Prüfsumme stehen in [dashcam-preview.json](../store/artwork/dashcam-preview.json). Die unveränderte Bernbach-Quelldatei und ihre frühere Versuchserwartung sind in [city-entry-source.json](assets/city-entry-source.json) dokumentiert.

Die DE:310-/DE:311-Piktogramme sind unveränderte gemeinsame Projektassets. **Mediatus**, nach amtlichen Vorgaben, Straßenverkehrs-Ordnung/DIN/Verkehrsblatt; laut geprüftem Quellmanifest gemeinfrei als amtliches Werk. [DE:310](https://commons.wikimedia.org/w/index.php?curid=61817186&oldid=972995612), [DE:311](https://commons.wikimedia.org/w/index.php?curid=61817370&oldid=906770477). Vollständige Herkunft: [gemeinsames Manifest](../shared/tsr/sign-pictograms/manifest.json). Keine Verkehrszeichen wurden für die Vorlesung neu gezeichnet.

Der Screenshot des Lane-Editors verwendet den vorhandenen synthetischen Lehrdatensatz und ist entsprechend beschriftet. `lane-demo.zip` enthält neun gespeicherte synthetische Frames, davon sechs geprüft und drei Entwürfe; es ist kein Genauigkeitsbeleg.

## Prüfsummen der neuen und wiederverwendeten deutschen Assets

SHA-256 identifiziert die konkreten Bytes dieser Fassung.

```text
13e90a6ee227eadc3fa2cf3224035efb0f0b8df5167738d2606c28c71d0f2ba8  assets/de/android-store.png
c70ac9aca4f0a2f3523e6ed8bf55c4144a36bd7529ad956187d47f187134ce55  assets/de/inspector-crops.png
00adf9a0d72d76593ebd07fe24f3c758b66fad240e33e4d006185cd81947feea  assets/de/inspector-detail.png
ceeacef793f666d5b657182567c90e3ade324a032774bbb889512047c4363efd  assets/de/iphone-signs-store.png
81aab88601362a891da3cc32af9ca3d19504b8c32652b6af7f7693644c5fdeef  assets/de/iphone-store.png
609c9207f9d8b9f4f371d54900518004013322fc999e705e86dae8d4486ee035  assets/de/lane-bezier-comparison.png
4f45491028e18fb666a1e0a17c5fdcd1c8d9c748d8188c2f00419f4a29592929  assets/de/lane-heldout-six-arm.jpg
dcf2c09a78a826aeba016c9959a102e2f695e24c4fb6d4ddc69e35057d98d8c5  assets/de/lane-holdout-failure.jpg
35a84f6039c2ef27fda65991a33b6d3b69703b5229b5277f8057c64f631fdbc6  assets/de/lane-live-overlay-contact.jpg
2ec57424dc3cec2ec920af7c0b26d88b6063bcee2ef3ab4cfedecc77bbdd9e9b  assets/de/ocr-distance.png
8940ca79c70b356b88a2c547514d25b0303f78a991a9485a2cd3e23a660b153a  assets/de/ocr-laermschutz.png
592c715d09304581eb1e4bb7436f3ff3e87c0d82d701d5088ae4383bc5b969c3  assets/de/ocr-time.png
ac9c3011c5feaa67d4a5a7275c060489b32ba062dcea0cd4891b5ddd6eb0cec4  assets/de/osm-pforzheim.png
850e6f7622d059fcbd56e1aecc16ee3ef9fc1975aa0c09153f6cd78128b3bd50  assets/de/panoramax-annotation-detail.png
9b247f30af4536bd3672c271f3fb58cd8c278a4cd81b6fda304d6b29a53f5054  assets/de/panoramax-annotations.png
dffc4b186d9c0211d06c1b0e9f224553b8095149734ef41791abd34e63ad7edf  assets/de/panoramax-town-overview.png
c08ff2fafe2d8084f493bbad318e5dba1287a4894110d8caa753775ef4d8d021  assets/de/panoramax-upload.png
953725f7abd0e6968798b0337d21420eb0b9599267de687dde531d424907744a  assets/de/youspeed-website.png
```

## Aktueller iPhone-Screenshot auf Folie 30

`assets/de/latest/iphone-live-panoramax-camera-2026-10-18.png` zeigt den am 18.10.2026 angeschlossenen echten iPhone-Bildschirm. Erfasst über die QuickTime-Vorschau mit dem iPhone als Bildschirmquelle, ohne Filmaufnahme. Die Datei ist unverändert; der Pfeil liegt als separates bearbeitbares PowerPoint-Element darüber. Er markiert den zweiten Button von links, der die automatische Panoramax-Fotoaufnahme ein-/ausschaltet. Das durchgestrichene Symbol zeigt den ausgeschalteten Zustand. Quelle der Funktion: `iphone/SpeedConsumerApp/MainView.swift:585–620` und Einfügung an zweiter Position bei Zeile 681.
