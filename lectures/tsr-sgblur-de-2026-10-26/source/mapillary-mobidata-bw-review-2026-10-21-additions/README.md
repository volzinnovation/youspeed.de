# Weitere Mapillary-Ortstafeln anhand MobiData BW

Am 21. Oktober 2026 wurden 70 zusätzliche Crop-/Vollbildpaare als ungeprüftes Lernmaterial zusammengestellt: 52 DE:310- und 18 DE:311-Vorschläge aus 70 Sequenzen und 66 Gemeinden. Die 69 nativen JPEGs bleiben in der über die Mapillary-API verfügbaren Originalauflösung unverändert. Eine ausdrücklich gekennzeichnete Perspektivansicht wird aus dem erhaltenen Originalpanorama erzeugt. Klassen und Boxen benötigen menschliche Freigabe; vollständige Detektorannotation fehlt noch.

Die [Publikationsquittung](../huggingface-mapillary-additions-publication.json) dokumentiert die feste HF-Revision, Prüfsumme und anonyme Downloadprüfung. Der [Lieferbericht](delivery-report.json) enthält Dateizahlen, der [Suchbericht](search-summary.json) den Suchumfang. Die [Studierendenanleitung](../../praktikum/DATEN_HERUNTERLADEN.md#5c-weitere-70-mapillary-paare-aus-der-mobidata-suche) erklärt Download und Review.

## Suchumfang und Grenzen

Der eingefrorene [Suchplan](query-plan.json) enthält 1.001 der 23.100 DE:310-/DE:311-Registereinträge, verteilt über 511 Gemeinden. Die Auswahl wechselte deterministisch zwischen Gemeinde/Klasse; neue Punkte lagen möglichst mindestens 150 Meter von bekannten Panoramax-MobiData-Kursstandorten und voneinander entfernt. Die vom Nutzer benannte Startansicht bildet eine Ausnahme. Dieser Suchplan ist eine Stichprobe, keine landesweite Vollerhebung.

Die registrierte Mapillary-Schnittstelle wurde mit 50 Metern Kameraradius abgefragt, höchstens 100 Ergebnissen je Punkt; keine Abfrage erreichte diese Grenze. Bevorzugt wurden berechnete Kamerapositionen, sonst die ursprünglichen Positionen. 656 Punkte haben mindestens eine Kamera innerhalb von 10 Metern, 756 innerhalb von 50 Metern. Diese Kameranähe belegt keine Schildsichtbarkeit und ist von den früheren 2.730 Panoramax-Katalogtreffern zu unterscheiden.

Nach Richtungsfilter und Auswahl der besten drei Bilder je Punkt blieben 2.158 verschiedene Bildkandidaten. Eine Ansicht je Standort und Sequenz wurde bevorzugt, native Perspektiven zuerst. 280 Vorschauen wurden visuell gesichtet, danach 88 verfügbare Originalauflösungen; 19 unklare, zu stark unscharfe, falsch zugeordnete oder am Bildrand abgeschnittene Ziele wurden verworfen. 69 native Perspektivbilder wurden übernommen. Das separat benannte Bad-Herrenalb-Panorama ergänzt die 70. Ansicht. Die 2.158 Kandidaten wurden nicht alle vollständig gesichtet.

Bei 42 ausgewählten Beispielen unterscheidet sich der sichtbare Klassenvorschlag vom nahen Registercode. Das kann insbesondere die andere Schildseite betreffen und bestätigt keine physische Identität. Im Bad-Herrenalb-Beispiel weist zusätzlich der Mapillary-Hinweis auf DE:311; das sichtbare Schild ohne roten Diagonalstrich ergibt DE:310. Ursprungslabels und visuelle Vorschläge bleiben getrennt. Es wurden keine SGBlur-Vorhersagen berechnet, keine Modelle trainiert und keine studentischen Modellresultate veröffentlicht.

## Herkunft und Verarbeitung

Bildbezogene Autoren, IDs, Aufnahmezeitpunkte, Sequenzen, Kamerapositionen und Lizenzen stehen im [Manifest](manifest.json). Expirierende CDN-URLs und API-Zugangsdaten gehören nicht zur Lieferung. Bilder und Crops: CC BY-SA 4.0, mit Autor, Mapillary-Fotolink, Lizenz und Änderungshinweis. Die HTML-Sichtung enthält das unveränderte offizielle Mapillary-Logo und Quellenlinks. Das Logo bleibt eine Marke von Mapillary. Register: Verkehrsministerium Baden-Württemberg / MobiData BW, dl-de/by-2-0. Projektcode: AGPL-3.0, separat vom Bildmaterial.

Die Crops entsprechen exakt den dokumentierten Pixeln der jeweiligen Vollansicht. Vorhandene Unkenntlichmachungen bleiben erhalten. Vier native JPEGs haben den undefinierten EXIF-Orientierungswert 0; ihr gespeichertes Raster wurde als aufrecht geprüft und nicht gedreht. Keine beibehaltene native Ansicht weicht von den in der API angegebenen Rastermaßen ab.

Die Panorama-Geometrie wird mit sphärischer Lochkamera und bilinearer Interpolation berechnet. Originalpanorama, Quellbox, Kameraparameter, transformierte Box und Hashes bleiben erhalten. Die Blickrichtung folgt der Zielbox; die abgeleitete Ansicht ist kein Blindtest und erzeugt keine neuen Quelldetails. Die 16 Geometrieprüfungen im [Testskript](test_project_panorama.py) betreffen Software, nicht Modellqualität.

Die 68 konservativen Gruppen verbinden gleiche Urheber/Aufnahmetage oder Registerpunkte innerhalb von 100 Metern. Zwei neue Bilder verweisen zusätzlich auf verwandte Gruppen im früheren Mapillary-Paket. Diese müssen vor einem Split zusammengeführt werden. Ein physischer Abgleich über alle Kursarchive, Plattformen und den separat bereitgestellten Bestandskorpus bleibt erforderlich. Neue Bild-IDs und Hashes beweisen keine unabhängigen Tafeln oder Fahrten.

## Wiederholung durch den Dozenten

Der benachbarte [API-Collector](../mapillary-mobidata-bw-review-2026-10-21/fetch_candidates.py) benötigt den eigenen registrierten Client-Token aus der nicht versionierten Datei `secret/MAPILLARY-CLIENT-TOKEN.txt` (Modus 600). Ein Client Secret ist für diese lesenden Abfragen nicht erforderlich. Kopieren Sie keine Zugangsdaten in Befehle, Protokolle, Archive oder Git. Die privaten API-Caches enthalten zeitlich begrenzte Bild-URLs und bleiben unter dem ignorierten `.build/`.

Verwenden Sie den eingefrorenen Suchplan mit `--max-points 1001 --max-previews 280 --workers 4` und einem neuen privaten Ausgabeordner. Der Collector verwendet `requests` und Pillow; die Kontaktsichtungen benötigen zusätzlich NumPy und `mapbox-vector-tile==2.2.0`. MVT-Hinweise werden mit `y_coord_down=True` dekodiert; ein Standard-Y-Flip liefert falsche Bildboxen. Prüfen Sie Hinweise stets am Raster.

[prepare_review.py](prepare_review.py) erzeugt den Sichtungseingang aus lokalen Bildern und einem privaten Eingabemanifest mit `local_image`, bei einer Projektion zusätzlich `local_source_image` und `projection_parameters`. Diese lokalen Pfade werden vor der Publikation entfernt. Das veröffentlichte Manifest enthält die geprüften Bild-/Crop-Pfade, Boxvorschläge und Herkunft; es enthält keine privaten Downloadpfade. Für einen erneuten Build müssen diese lokalen Eingabepfade aus einer separat entpackten Kopie ergänzt werden. Verwenden Sie einen neuen Ausgabe- und Archivpfad sowie einen vollständigen Inventarstand früherer Bild-IDs und Bild-/Crop-Hashes; überschreiben Sie keine menschlichen Reviews.

Die [Prüfquittung](verification.json) dokumentiert exakte Crop-Pixel, Hash-Abgleich, lokale HTML-Verweise und das Fehlen von Zugangsdaten und privaten Arbeitspfaden. Modelltraining, Splitfreigabe und Modellbewertung bleiben Aufgaben der Studierenden.
