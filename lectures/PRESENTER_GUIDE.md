# Hinweise zur Lehrveranstaltung

**KI für intelligente Mobilität**  
**Profilprojekt IMo WS27-28 HSPF**  
**Prof. Dr. Raphael Volz**  
19. Oktober 2026 · 42 Folien · 90 Minuten

Die Folien führen vom OSM-Ökosystem über YouSpeed und seine Modelle zur Datenerhebung und zum überwachten Lernen. [STUDENT_GUIDE.md](STUDENT_GUIDE.md) enthält Befehle und Arbeitsschritte. Die sichtbare Agenda verwendet Abschnitte ohne Minutenangaben. Dieser Leitfaden enthält relative Richtzeiten und setzt keine bestimmte Startuhrzeit voraus.

## Ablauf für 90 Minuten

| Abschnitt | Richtzeit | Schwerpunkt |
| --- | ---: | --- |
| Projekt und OpenStreetMap | 12 Minuten | YouSpeed-Webseite, Pforzheim-Karte, Anwendungen, Tags, annotierte Panoramax-Bilder |
| App- und Serverarchitektur | 15 Minuten | Drei Orakel, Bundles/Modelle, Erfassung, Inspector und Rückfluss nach OSM |
| KI-Modelle und Lernen | 20 Minuten | Lokalisierung/Segmentierung, Landesmodelle, OCR, Spuren, Spracherkennung, Hz-Rechnung, Training/Validierung/Test |
| Projektmanagement und Datenerhebung | 17 Minuten | Termine, Git/GitHub, Team-Forks, App installieren, Fotos, Panoramax-Annotationen |
| Datensätze und Semesterprojekte | 23 Minuten | Inspector-Labels, unabhängige Splits, zwei Projekte mit je zwei Teams, Modellkandidaten und Abgaben |
| Fragen | 3 Minuten | Offene Fragen und erste konkrete Aufgabe je Team |

Demonstrationen liegen innerhalb der Abschnitte. Die 42 Folien sind auf insgesamt 90 Minuten angelegt; die Richtzeiten dienen als Orientierung innerhalb dieses Rahmens. Beim Wechsel zum Projektmanagement die zweite Agenda als Orientierung verwenden. Den Schluss für Fragen freihalten. Neue Uploadverarbeitung und Modelltraining müssen nicht während der Einführung fertig werden.

## Termine

Die Terminfolie im Projektmanagement-Abschnitt erläutern:

| Termin | Anlass |
| --- | --- |
| 19.10.2026 | Projekt Kick-Off |
| Montags 11:30–13:00 | Status Standup + Fragen |
| 21.12.2026 | Projektabschluss |
| 11.1.2027 | Interne Präsentation |
| 18.1.2027 | Öffentliche Präsentation (WI-TAG) |

## Vorbereitung

- App-Version und Länderpakete auswählen. Öffentliche 1.3-Versionen und integrierte 1.4-Entwicklungsstände unterscheiden sich. Region, Standort, Kamerafunktionen und Probeaufnahme vorher prüfen.
- Vier Team-Forks von [YouSpeed](https://github.com/volzinnovation/youspeed.de) und dem privaten [Woladen.de-analytics-Repository](https://github.com/volzinnovation/Woladen.de-analytics) ermöglichen. Private Fork-Regeln vorab prüfen.
- Panoramax-Konten und gemeinsame Lesesichtbarkeit vorbereiten. [panoramax.youspeed.de](https://panoramax.youspeed.de/) ist ein Alias von [panoramax.woladen.de](https://panoramax.woladen.de/). Sichtbarkeit je Upload und Kurskonto ausdrücklich prüfen und die Kursvorgabe anwenden; dokumentierte Voreinstellungen können abweichen. Die vorbereitete Administratorsicht zeigte „Public“ als Auswahl, ohne dass ein Upload oder eine Einstellungsänderung ausgeführt wurde.
- Echte Panoramax-/Inspector-Screenshots und lokales Spurdataset bereithalten. Die autorisierte Administratorsitzung darf zur Erstellung der Lehrbilder verwendet werden. Auf der Projektion keine Zugangsdaten, Tokens oder Administrationsgeheimnisse zeigen. Studierende verwenden eigene Konten.
- Einen angeschlossenen iPhone-Bildschirm bei Bedarf mit **QuickTime Player → Neue Filmaufnahme** ansehen und das iPhone als Kameraquelle wählen. Keine Aufnahme zum bloßen Betrachten starten. QuickTime bietet Ansicht, keine Touch-Steuerung. Kein iPhone Mirroring verwenden.
- `ffmpeg -version` und `ffprobe -version` ausführen. Bei der ersten Vorbereitung am 18. Oktober fehlte `libx265.216`; Decoder testen und gespeichertes Dataset als Alternative bereithalten.

Lokalen Inspector entsprechend dem Studierendenleitfaden starten:

```sh
python3 inspector/server.py --port 8080
```

[http://127.0.0.1:8080/inspector/](http://127.0.0.1:8080/inspector/) öffnen. Ein statischer Server reicht für Videodekodierung nicht aus.

## Inhaltliche Leitlinien

### OpenStreetMap als Ökosystem und Ziel

Die Pforzheim-Karte zeigt einen Anwendungsfall derselben offenen Daten. Mit den danebenstehenden Feldern Karten, Routenplanung und Datenbank den Blick erweitern. Danach Erhebung, Editor, Datenbank, Extrakte und Anwendungen einordnen. Den [Verkehrszeichen-Tag-Katalog](https://trafficsigns.osm-verkehrswende.org/DE) sichtbar verlinken.

`traffic_sign` ist ein OSM-Schlüssel; `osm|traffic_sign` gehört zur Panoramax-Semantik. Foto, Annotation, Sichtung, physisches Schild und OSM-Objekt unterscheiden. Das Ziel ausdrücklich nennen: **Menschen verbessern offene Kartendaten auf Grundlage gesammelter, geprüfter Beobachtungen.** Ein Modelloutput oder eine Datenbankaufnahme veröffentlicht noch keine OSM-Änderung.

### Drei Orakel vor der Architektur

Die vom Projektverantwortlichen gewünschte Reihenfolge erklären:

1. Gesprochene Nutzerkorrektur; iPhone verwendet Apple Speech, Android gebündeltes Vosk.
2. Kamera-/Vision-Erkennung.
3. OSM-Datenbank-Bundle.

Gültigkeit, Richtung und Lebensdauer der Evidenz bleiben relevant. Bei einem **bestätigten Übergang In-Stadt ↔ Außer-Stadt** wird die alte visuelle Zeichenreferenz verworfen und der neue Ortskontext ausgewertet. Kurze unbekannte oder schwache Kontextzustände lösen dies nicht aus; die Bestätigung benötigt vertrauenswürdige Siedlungsevidenz. Eine an den bisherigen Kontext gebundene Sprachkorrektur kann an der bestätigten Grenze ebenfalls enden. An diesem Beispiel erklären, warum Priorität keine unbegrenzte Gültigkeit bedeutet. Die Folienkorrektur ändert keine geschützten Interpreter. Der bisherige Konfliktfall mit drei Zahlen entfällt.

### App und Server getrennt erklären

Zuerst den lokalen App-Weg zeigen: GitHub Actions bereitet regionale Bundles vor, Prolix-/Panoramax-Modelle liefern die Erkennung, die Apps nutzen beides auf dem Gerät und erzeugen Beobachtungen. Die Fahrtfunktionen benötigen keine permanente Serververbindung.

Danach die Server-Seite: Panoramax verarbeitet beigetragene Straßenbilder und Annotationen. Die Crops-/Sichtungsdatenbank hält Erkennungsbelege und Herkunft; der Inspector unterstützt Prüfung und Diagnose. Nutzergesteuerte OSM-Beiträge schließen den Kreislauf. Automatisches 1.4-Signsharing und ausdrücklich bestätigter Panoramax-Fotoupload sind getrennte Wege.

### Fünf KI-Aufgaben erklären

- **Detektion/Segmentierung:** aktuelle mobile Lokalisierung liefert Boxen; genaue Masken erfordern eigene geprüfte Supervision.
- **Klassifikation:** Ausschnitt → passendes Landesmodell → Klasse/Code. Mappingtabellen und Piktogramme erzeugen keine neuen Modellausgänge.
- **OCR:** Textregion → Text/Konfidenz. Das Lesen von „bei Nässe“ stellt die Bedingung nicht fest.
- **Spurerkennung:** am vorhandenen Bild mit hervorgehobenen Spuren sichtbare Markierung, Korridor und angenommene Trajektorie unterscheiden. Klassische native Bildverarbeitung/Tracking ist der Ausgangsvergleich für gelernte Kandidaten.
- **Spracherkennung:** Apple Speech auf dem iPhone und Vosk unter Android erkennen die gesprochene Zahl für eine bewusste Nutzerkorrektur. Diese fünfte Aufgabe mit einem Korrekturbeispiel erläutern und dem ersten Orakel zuordnen.

### Zeitbudget gemeinsam rechnen

`T = 1 / f`: **10 Hz = 100 ms**, **5 Hz = 200 ms**, **2 Hz = 500 ms**. Bei **50 km/h = 13,89 m/s** werden in **250 ms rund 3,47 m** zurückgelegt. Mehr Kamerabilder beseitigen keine langsame Verarbeitung oder veraltete Warteschlangen.

≥15 FPS Kamera, adaptive 2–10 Hz TSR und p95 unter 250 ms sind Spezifikationsziele. Leistung braucht reale Messungen mit Gerät, Build, Last und Dauer. Inferenzzeit, Aktualisierungsintervall und Ergebnisalter trennen.

### Überwachtes Lernen als Schleife

Menschliche Labels, Annotationsregeln und unabhängige Fahr-/Ortsgruppen zuerst festlegen. Auf Training lernen, auf Validierung auswählen, auf eingefrorenem Test abschließend bewerten. Fehlbeispiele führen zu gezielter Datenarbeit oder neuer Modellversion; nicht fortlaufend auf dem Testbestand optimieren.

Auslieferungsziele sind **serverseitiges Modell**, **Core ML** und **LiteRT**. Vorverarbeitung und Labels müssen nachvollziehbar bleiben. Ein guter Serverwert beweist weder mobile Laufzeit noch Plattformparität.

## Demonstrationshinweise

### GitHub

An vorbereiteten Forks Eigentümer, Verlauf, Issues und Änderungen zeigen. Lokal `git remote -v`, `git status --short` und Standardbranch aufrufen. `origin` ist der Team-Fork, `upstream` das Original. Auf die Analytics-Policy für Standardbranch, Branchwechsel und Pull Requests hinweisen. Für die Einführung sind weder neuer Push noch Merge oder produktiver Rollout erforderlich. Studierende benötigen zum Einstieg keine App-Buildumgebung.

### App und Panoramax

Hochwertige Website-/Store-Bilder für die Fahroberfläche verwenden. Den Fotoupload mit App-Screenshots erklären: Aufnahme beenden, lokale Fotos **in der App** prüfen und auswählen, eigenes Panoramax-Konto verbinden und den Upload in der App ausdrücklich starten. Danach zur bereits verarbeiteten Panoramax-Sequenz im Webviewer wechseln. An einem echten annotierten Schild Box und Semantik erklären und die gespeicherte Annotation erneut öffnen. IDs für Bild, Sequenz und Annotation benennen. Für Änderungen vorgesehene Lehrbilder verwenden; zur Screenshot-Erstellung ist kein echter neuer OSM-Upload nötig.

Den lokalen Korrekturexport als Vorschlag erklären: aktuelle OSM-Objekte laden, Beobachtung prüfen, bestätigte Änderungen übertragen und bewusst veröffentlichen. Keine persönliche OSM-Anmeldung aus älteren Dokumentationsscreenshots für Studierende übernehmen.

### Inspector und Spurframes

Echte Crop-/Sichtungsansichten verbinden Bild, Vorhersage, Zeit, Quelle und Prüfung. In der Spurannotation vier Kontrollpunkte, Klasse, Track-ID und Prüfstatus demonstrieren. Ein Screenshot illustriert das Werkzeug und ist keine Modellbewertung. Vorhandene Panoramax-Annotationsautoren und Modellherkunft exakt erhalten. Bei wiederverwendeten Regressionsbildern die dokumentierte Bedeutung der farbigen Labels und Ausgaben beibehalten; daraus keine neue menschliche Pixelmasken-Annotation ableiten.

Alternative ohne neue Dekodierung: [assets/lane-demo.zip](assets/lane-demo.zip) importieren. Das synthetische Beispiel enthält neun gespeicherte 128×72-Frames: sechs geprüfte Samples und drei Entwürfe, jeweils zwei geprüfte Samples pro Split. Es ist kein echter Trainingsbestand.

1. Lokale Arbeit vor Import exportieren.
2. Dataset importieren und gespeicherten Frame öffnen.
3. Kontrollpunkt verschieben; der Frame wird erneut Entwurf.
4. Klasse, Track-ID und **Frame geprüft bestätigen** erläutern.
5. **Drive-Gruppe / Split** und portablen ZIP-Export zeigen.

## Zwei Projekte mit je zwei Teams

| Teams | Thema | Gemeinsame Grundlage | Eigenständige Leistung |
| --- | --- | --- | --- |
| A1 und A2 | Ortstafeln DE:310 / DE:311 | Annotationsprotokoll, vergleichbare Testkriterien | Eigene Daten, Modellansatz, Evaluation und Fehlanalyse |
| B1 und B2 | Spurerkennung | Kurven-/Trackregeln, vergleichbare Testkriterien | Eigene Daten, Modellansatz, Evaluation und Fehlanalyse |

Die Teams bearbeiten dasselbe Thema parallel, um Entscheidungen und Ergebnisse vergleichen zu können. Gemeinsame Regeln bedeuten keine Vermischung von Training und Test. Erster Meilenstein ist ein kleiner sauber geprüfter eigener Datenbestand; danach wird die Erhebung skaliert.

Je Projekt Datenkarte, Annotationen, unabhängige Splits, Training/Code, Ausgangsvergleich, serverseitige und vorgesehene mobile Artefakte, Messwerte und Demonstration verlangen. Produktiver Rollout braucht eigene Freigabe. Modellarbeit ändert keine geschützte Geschwindigkeitsreferenz-Policy.

Mit der Schlussfolie **„Nur Fragen?“** enden. Jedes Team sollte anschließend Zugang, Projekt und den ersten konkret zu erstellenden menschlichen Labelstand benennen können.
