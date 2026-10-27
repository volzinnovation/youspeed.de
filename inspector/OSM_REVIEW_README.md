# OSM-Korrekturen im YouSpeed Inspector

Öffnen: **https://osm.youspeed.de**. Der Dienst erzeugt Vorschläge für Geschwindigkeitslimits und Bedingungen. Du prüfst immer einen ursprünglichen OSM-Way und lädst dessen geprüfte JOSM-Datei herunter.

## Erklärvideo

**Hier ist Platz für das Erklärvideo.**

<!-- Video-URL, Vorschaubild und gegebenenfalls Untertitel hier ergänzen.
     Der entsprechende 16:9-Platzhalter steht in osm-help.html unter #explanation-video.
     Kein Beispielvideo oder automatisch startendes Video einsetzen. -->

## 1. Fahrt öffnen

1. In der App unter **Fahrten** die gewünschte Fahrt teilen und den **ZIP-Export** speichern. Der Export sollte den Track enthalten: `journal.json` mit GPS-Ereignissen oder `track.gpx` im ZIP. Ein verschlüsseltes App-Backup ist kein Fahrt-Export.
2. Im Inspector **Fahrt-ZIP öffnen** wählen. Mehrere Fahrt-ZIPs können nacheinander oder gemeinsam ausgewählt werden; unter **Fahrt** zwischen ihnen wechseln. Eigene Crops aus allen in derselben Sitzung geöffneten Fahrten können den ausgewählten Straßenabschnitt ergänzen, auch aus der Rückfahrt.
3. Das passende **App-Bundle** auswählen. Angezeigt werden dieselbe Region und Generation wie in den Apps. Der Dienst öffnet die unveränderten Bundle-Dateien nur lesend; er baut keine neue Kartendatenbank.
4. **Vorschläge berechnen** starten. Der Dienst vergleicht Bestand und aktuelle OSM-Daten und sucht annotierte Panoramax-Aufnahmen aller Beitragenden in beiden Richtungen. Eine selbst aufgezeichnete Rückfahrt ist nicht erforderlich.

Eigene im Export enthaltene Bilder/Crops bleiben direkte Evidenz. Originalzeit, Frame-/Crop-Identität und vorhandene OCR bleiben mit dem Bild verknüpft. Die normalen App-Exporte enthalten Medienbytes nur, wenn diese beim Teilen ausgewählt wurden und auf dem Gerät verfügbar sind. Ein Verweis auf ein fehlendes Bild wird nicht als vorhandenes Bild ausgegeben. Der öffentliche Dienst gibt keine privaten Backend-Crop-Bestände anhand einer Geräte-ID frei.

## 2. Einen Vorschlag prüfen

- **Offen** zeigt die noch zu prüfenden Änderungen. **Bereits korrekt**, **Bestätigt**, **Übersprungen** und **Klärung** sind getrennt filterbar.
- Links stehen aktueller OSM-Tag, vorgeschlagener Wert, Bedingungen und der betroffene Abschnitt. Die kleine Karte verwendet denselben Kartenbaustein wie der übrige Inspector. Er lädt Standard-OpenStreetMap-Kacheln direkt, mit sichtbarer Quellenangabe und ohne Stadia-Anmeldung. Es werden nur die aktuell angezeigten Kacheln geladen.
- Rechts zwischen **Unser Crop** und **Aufnahme** wechseln. Panoramax lässt sich für die vollständige Szene öffnen. Prüfe, ob es derselbe Standort und dieselbe Fahrtrichtung ist. Ein Ausschnitt und sein Ursprungsbild zählen als dieselbe Beobachtung.
- Zusatzzeichen gehören zum passenden Hauptzeichen. Eine Zeitplatte unter einem Lkw-Verbot darf nicht automatisch die darüber stehende Geschwindigkeitsbegrenzung einschränken. Unklare OCR, widersprüchliche Aufnahmen und unsichere Straßenbezüge bleiben unter **Klärung**.
- **Gesamten Way ändern** ändert nur die Tags. **Teilen und Abschnitt ändern** fügt die erforderliche Grenze ein und ändert nur die betroffenen Teile. Bei einer gemeinsamen Grenze mit unterschiedlichen Limits beiderseits ist die ganze Strecke keine zulässige Alternative.
- Einbahnstraßen verwenden gewöhnlich `maxspeed` bzw. `maxspeed:conditional`. Richtungsunterschiede werden nicht aus einer einzigen beobachteten Anfahrt erfunden.

## 3. Bestätigen und JOSM-Datei laden

**Bestätigen & JOSM-Datei laden** führt den aktuellen OSM-Abgleich, die Geometrie-/Relationsprüfung und den vollständigen JOSM-Core-Validator aus. Eine Datei wird nur nach erfolgreicher Prüfung angeboten. Es gibt keine Pflicht-Checkboxen oder Pflichtbegründungen.

Der Download enthält nur den ausgewählten ursprünglichen Way, seine erforderlichen Teilstücke/Knoten und gegebenenfalls angepasste Elternrelationen. `source` verlinkt die passenden öffentlichen Panoramax-Bilder. Eigene private Bildbytes, Tokens und der private Fahrt-Track werden nicht in OSM-Tags eingebaut. Der Dienst lädt selbst nichts zu OSM hoch.

Die Datei in JOSM öffnen, Änderungen ansehen, vor einem Upload erneut aktualisieren/prüfen und mit dem eigenen OSM-Konto hochladen. Die Prüfung gilt für die erzeugten Änderungen und erforderlichen geänderten Relationen mit dem angegebenen Validatorstand. Andere bereits offene Ebenen, spätere OSM-Änderungen und zusätzliche JOSM-Plugins können weitere Hinweise liefern.

Falls eine benötigte Relation schon einen Fehler oder eine Warnung hat, bleibt der Vorschlag unter **Klärung**. Der Dienst entfernt keine Tags, aktiviert keine aufgegebene Route und unterdrückt keine Warnung, um einen Download zu erzwingen.

**Überspringen** und **Klärung** wechseln ohne weitere Formulare zum nächsten offenen Vorschlag.

## Datenschutz und Sitzungsende

Fahrt-Upload, Crops, OCR, Auswahl und Ergebnisse werden ausschließlich vorübergehend im Arbeitsspeicher verarbeitet. Es gibt keine Nutzer-/Fahrtendatenbank und keine dauerhafte Ablage für Uploads, Fortschritt oder Ergebnisdateien. Der Dienst legt keine Upload-Temporärdateien an und protokolliert keine Fahrt-/Bilddaten. Öffentlich verfügbare App-Bundles und Programm-/Validator-Dateien sind davon getrennt und können unverändert zwischengespeichert werden.

Mit **Sitzung beenden** wird die Sitzung auf dem Server verworfen; erst nach der Serverbestätigung erscheint „Sitzung beendet“. Es öffnet sich kein Dateidialog und es wird keine leere Ersatzsitzung angelegt. Bei einem Fehler bleibt die Sitzung zum erneuten Schließen verfügbar. Beim Verlassen der Seite versucht der Browser ebenfalls, sie zu schließen. Bei Verbindungsabbruch oder Browserabsturz läuft sie spätestens nach 30 Minuten ab. Nach einem Neustart sind alle Sitzungen weg. Für eine neue Sitzung den Fahrt-Export erneut öffnen. Nur ein von dir angeforderter Download wird auf deinem eigenen Gerät gespeichert.

Der freigegebene Arbeitsspeicher steht dem Server wieder zur Verfügung; die Betriebssystemanzeige muss dabei nicht sofort sinken. Bereits laufende Arbeit kann Referenzen bis zum nächsten Abbruchpunkt behalten, etwa bis eine laufende JOSM-Prüfung endet. Öffentliche Bundle-Caches bleiben erhalten.

Kartenkacheln werden wie im Inspector vom Kartendienst geladen. Die Aufnahmesuche verwendet Panoramax und die OSM-Aktualisierung die öffentliche OSM-API. Es werden keine Crops an einen neuen KI-Dienst geschickt.

## Wenn etwas fehlt

- **Kein Track:** Fahrt-ZIP mit `track.gpx` oder GPS-Ereignissen teilen; eine alleinige Übersicht/PDF reicht nicht.
- **Kein eigener Crop:** Medien müssen im Export enthalten sein. Ein privater lokaler Dateipfad kann auf dem Server nicht geöffnet werden.
- **Bildsuche unvollständig:** Eine begrenzte oder fehlgeschlagene Suche ist keine Bestätigung, dass keine weiteren Schilder existieren.
- **Validator nicht verfügbar:** Kein ungeprüfter Ersatzdownload. Später erneut versuchen.
- **OSM inzwischen geändert:** Vorschläge neu berechnen; ältere Versionen werden nicht blind überschrieben.
