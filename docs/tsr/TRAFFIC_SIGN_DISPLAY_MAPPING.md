# Verkehrszeichenanzeige während der Fahrt

| Kategorie | Beispiele und Zuordnung | Anzeige |
| --- | --- | --- |
| Ende einer Geschwindigkeitsbeschränkung | Ende eines Zahlenlimits, Ende sämtlicher Streckenverbote, Ende einer Tempozone oder Fußgängerzone, Ende von Autobahn oder Kraftfahrstraße | Zwei Sekunden im Hauptschild an der Stelle des Tempolimits. Bei fehlendem geprüftem Piktogramm erscheint ein Texthinweis. |
| Ortseingang und Ortsausgang | DE 310/311, FR EB10/EB20, BE F1/F3, NL H01/H02, erkannte Klassen `city:*` | Adressanzeige Innerorts/Außerorts und Kontext für die Bußgeldregeln. |
| Gefahrzeichen als aufrechtes rotes Dreieck | Baustelle, Kinder, Glätte, Wildwechsel, Gefahrenstelle, Kreuzung. DE 101, 102, 103, 105, 112, 114, 117, 120, 121, 123–125, 131, 136, 138, 142, 151 und 301, FR A/AK-Gefahrzeichen sowie AB1/AB2/AB25, BE A-Gefahrzeichen, NL J-Gefahrzeichen und B03/B04/B05, CH Gefahrzeichen 1.x sowie 3.05/3.06. | Bleiben auf der Nebenposition bis zur nächsten dort anzeigbaren Erkennung oder bis zum Ablauf des Fahrtkontexts. |
| Sonstige Nebenschilder | Stop, Vorfahrt gewähren, Vorfahrtstraße, Kreisverkehr, Parken, Halteverbot, Überholverbot und dessen Aufhebung, Durchfahrtsverbote, bauliche Beschränkungen. | Drei Sekunden auf der Nebenposition. Wiederholte Kamerabilder desselben Zeichens verlängern das Zeitfenster nicht. |
| Blaue Richtungspfeile | Klassen `arrow_*`, DE 209/211/214/222, FR B21, BE D1/D3, NL C04 und D02–D07, CH 2.32–2.41. | Ausgeblendet. Die Erkennung allein verdrängt kein Gefahrzeichen. |
| Bedingtes Tempolimit ohne aktuelle Anwendung | Numerische Grenze mit ausgewerteter OSM-Bedingung oder verifiziertem OCR-Zusatzschild, etwa `20–7 Uhr` tagsüber oder `bei Nässe` bei unbekanntem Straßenzustand. | Grauer Ring mit Bedingung darunter. Der Platz links unten ist derselbe wie für die rote Vorschau einer vorausliegenden Grenze. Kameranachweis hat Vorrang vor Bundle-Nachweis, die graue Anzeige hat Vorrang vor der roten Vorschau. |

Die Apps verwenden dieselben geprüften Piktogramme aus
[`shared/tsr/sign-pictograms`](../../shared/tsr/sign-pictograms/). Die
Anzeigedauer für ein Piktogramm und die Gültigkeit der zugrunde liegenden
Geschwindigkeitsregel werden getrennt bestimmt.

Mapillary-Nebenschilder werden nur mit gültigem GPS-Kurs und einem Winkelabstand
unter 30° zur Leserichtung angezeigt. Der rohe Mapillary-Winkel
`aligned_direction` beschreibt die Schildfläche und wird dafür einmal um 180°
gedreht. Maßgeblich für das Alter ist ausschließlich `last_seen_at`. Das letzte
Sichtungsdatum muss innerhalb der vergangenen zwölf Kalendermonate in UTC
liegen und darf keine zukünftige Zeit angeben. Fehlende Richtungs- oder
Sichtungsdaten verhindern die Anzeige. Auch bereits gehaltene Mapillary-Zeichen
werden bei Richtungswechsel oder Ablauf erneut geprüft.

Beide nativen Leser übernehmen diese Angaben aus
`traffic_sign_inventory.raw_properties_json`. Ältere Datenbanken ohne diese
Metadaten können ihre Mapillary-Zeichen nicht zur Anzeige freigeben.
`scripts/map/filter_mapillary_last_seen.py` erzeugt für lokale Neubauten eine
Quellkopie, aus der Mapillary-Einträge mit fehlendem oder ungültigem
`last_seen_at` entfernt werden.
