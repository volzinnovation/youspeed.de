# YouSpeed-gebruikershandleiding voor iPhone

Deze handleiding laat zien hoe je offline kaartgegevens downloadt, een correctie van een snelheidslimiet vastlegt, deze als OpenStreetMap-wijzigingsbestand exporteert en controleert voordat je de wijziging naar OpenStreetMap (OSM) uploadt.

De schermafbeeldingen zijn gemaakt met YouSpeed in de iPhone 17-simulator en tonen de Duitse interface. Toestemming voor de microfoon en spraakherkenning wordt als verleend beschouwd. Omdat er geen live spraakinvoer beschikbaar was, gebruikt het voorbeeld het aangenomen herkenningsresultaat **30**. De vermelding van de Durlacher Allee is demonstratiegegevens en geen bewijs dat de echte weg moet worden gewijzigd.

> **Veiligheid:** stel de app vóór vertrek in. Leg een correctie alleen vast wanneer je veilig stilstaat of als passagier. YouSpeed is een hulpmiddel; verkeersborden en verkeersregels hebben altijd voorrang.

## 1. Rijscherm

![YouSpeed-rijscherm in de iPhone-simulator](user-guide/ios-driving-screen.png)

Het grote bord toont de snelheidslimiet die op basis van de lokale kaart aan de huidige locatie is gekoppeld. Het getal eronder is de actuele GPS-snelheid. Met de insectknop linksboven open je **Lokale Erfassungen** (lokale registraties); met het tandwiel rechtsonder open je de instellingen.

## 2. Regionale kaarten downloaden

Open de instellingen met het tandwiel en scrol naar **Kartendaten-Download** (kaartgegevens downloaden). Landen staan alfabetisch. Landen met regionale pakketten, zoals **Deutschland**, tonen elke regio afzonderlijk.

![YouSpeed-instellingen met Duitse regionale kaartdownloads](user-guide/ios-regional-map-downloads.png)

1. Maak verbinding met internet, open **Einstellungen → Kartendaten-Download** en zoek het gewenste land of de gewenste regio.
2. Tik op de pijl omlaag naast de regio, bijvoorbeeld **Baden-Württemberg** of **Bayern**.
3. Houd YouSpeed geopend totdat de voortgangsindicator klaar is. Het pakket is daarna beschikbaar voor offline kaartmatching.
4. Herhaal dit voor andere regio’s die je nodig hebt. Elk pakket kan afzonderlijk worden beheerd.
5. Gebruik de verwijderfunctie van een gedownload pakket om opslagruimte vrij te maken. Met **Heruntergeladene Datenbanken loeschen (Seed behalten)** verwijder je alle downloads maar behoud je de ingebouwde basisgegevens.

De schermafbeelding gebruikt testgegevens uit de simulator en toont daarom de statussen `ready screenshot` en `screenshot`. Een normale installatie toont het actieve pakket en de werkelijke downloadstatus.

## 3. Een correctie via spraak vastleggen

1. Wacht tot YouSpeed de juiste weg en de bijbehorende snelheidslimiet toont en controleer of het GPS-signaal goed is.
2. **Tik tweemaal op het grote snelheidsbord.**
3. Geef bij het eerste gebruik toegang tot de microfoon en spraakherkenning. In deze handleiding worden beide toestemmingen als verleend beschouwd.
4. Wanneer het bord `?` toont en de app **Jetzt sprechen** (“Nu spreken”) weergeeft, spreek je alleen de nieuwe waarde uit, bijvoorbeeld **“30”**. Voor stapvoets rijden kun je ook **“Fussgaengerzone”** zeggen.
5. YouSpeed slaat het resultaat lokaal op. OpenStreetMap wordt niet automatisch gewijzigd.

![YouSpeed wacht op een uitgesproken correctie van de snelheidslimiet](user-guide/ios-correction-listening.png)

## 4. De lokale registratie controleren en exporteren

Open **Lokale Erfassungen** met de insectknop. Controleer tijdstip, straat, OSM-way-ID, oude waarde (**alt**) en nieuwe waarde (**neu**). Verwijder de registratie wanneer de verkeerde weg is gekoppeld of de waarde verkeerd is herkend.

![Lokale YouSpeed-registratie met een correctie van 50 naar 30](user-guide/ios-local-recordings.png)

Tik op **changes.osc exportieren** en kies **In Dateien sichern** om `changes.osc` in de Bestanden-app op te slaan. Je kunt het bestand ook met AirDrop of een andere deelactie naar de Mac overzetten.

![iOS-deelvenster voor het geëxporteerde changes.osc-bestand](user-guide/ios-osc-export.png)

De export is een voorstel met OSM-way-ID’s en voorgestelde `maxspeed`-waarden. Het is geen volledig gecontroleerde OSM-gegevensset.

## 5. Het OSC-voorstel controleren en naar OSM uploaden

Gebruik het speciale OSM-account:

- E-mailadres voor aanmelden: `raphael.volz@pm.me`
- OSM-gebruikersnaam: `youspeed DOT de - mapping speed limits`

De gebruikersnaam in het Safari-accountmenu bevestigt welk account actief is. Zet het e-mailadres of wachtwoord nooit in de changeset-opmerking.

![OpenStreetMap in Safari met het YouSpeed-mappingaccount aangemeld](user-guide/osm-account.png)

### Veilige werkwijze met JOSM

De huidige YouSpeed-export `changes.osc` bevat alleen het ID van elke way en de voorgestelde `maxspeed`-tag. De volledige geometrie, actuele objectversie en andere tags ontbreken. **Upload de geïmporteerde OSC-laag niet rechtstreeks.** Gebruik deze als controlelijst en pas elke bevestigde wijziging toe op nieuw gedownloade OSM-gegevens:

1. Installeer en open [JOSM](https://josm.openstreetmap.de/) en inspecteer `changes.osc` via **Bestand → Openen…**.
2. Gebruik voor elke vermelde way **Bestand → Object downloaden…** (`Ctrl+Shift+O`), selecteer **way**, voer het ID in en download het actuele object van OSM. Download ook de omgeving en verwijzende objecten wanneer die voor de weg relevant zijn. Zie de [JOSM-handleiding “Download Object”](https://josm.openstreetmap.de/wiki/Help/Action/DownloadObject).
3. Vergelijk de voorgestelde waarde met een echte waarneming ter plaatse. Controleer of de way het juiste wegvak beslaat en of de limiet over de volledige lengte geldt.
4. Bewerk de nieuw gedownloade way en behoud de geometrie en alle niet-gerelateerde tags. Stel `maxspeed=30` alleen in wanneer 30 in beide richtingen geldt. Gebruik voor een richtingsafhankelijk of voorwaardelijk bord de juiste OSM-tags; raadpleeg de [OSM-documentatie voor `maxspeed`](https://wiki.openstreetmap.org/wiki/Key%3Amaxspeed).
5. Start OAuth-autorisatie in de verbindingsinstellingen van JOSM. Safari hoort de OSM-autorisatiepagina te openen. Controleer of **youspeed DOT de - mapping speed limits** wordt weergegeven en autoriseer daarna JOSM.
6. Voer de JOSM-validatie uit en los fouten of conflicten op. Werk de gegevens opnieuw bij als een andere mapper ze tijdens je controle heeft gewijzigd.
7. Kies **Bestand → Gegevens uploaden** (`Ctrl+Shift+↑`). Controleer de exacte lijst met gewijzigde objecten. Voeg een duidelijke changeset-opmerking toe, bijvoorbeeld `Aangegeven snelheidslimieten bijgewerkt na controle ter plaatse met YouSpeed`, en gebruik `survey` alleen als bron wanneer er werkelijk ter plaatse is gecontroleerd. De [JOSM-uploadhandleiding](https://josm.openstreetmap.de/wiki/Help/Action/Upload) beschrijft de validatie en het uploadvenster.
8. Klik pas na de laatste controle op **Wijzigingen uploaden**. Hiermee publiceer je de wijziging onder het geselecteerde account in OSM; dit is geen privétest.

Het gesimuleerde voorbeeld 50 → 30 in deze handleiding is bewust **niet geüpload**.

## Problemen oplossen

- **“Jetzt sprechen” verschijnt niet:** open in iOS **Instellingen → Privacy en beveiliging → Microfoon** en **Spraakherkenning** en schakel YouSpeed in. Duitse spraakherkenning op het apparaat moet beschikbaar zijn.
- **Verkeerde waarde of weg herkend:** verwijder de lokale registratie en leg deze opnieuw vast zodra de juiste weg gekoppeld is.
- **De exportknop levert geen bruikbaar bestand op:** controleer of er minstens één geldige lokale registratie in de lijst staat.
- **JOSM meldt onvolledige gegevens of conflicten:** forceer de upload niet. Download de actuele way en omgeving opnieuw, pas de gecontroleerde tag toe op dit volledige object en voer de validatie nogmaals uit.
- **De regionale lijst of download is niet beschikbaar:** controleer de internetverbinding, open de instellingen opnieuw en probeer het nogmaals. Reeds gedownloade kaarten blijven offline werken.
