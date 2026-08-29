# Guide utilisateur YouSpeed pour iPhone

Ce guide explique comment télécharger des cartes hors ligne, enregistrer une correction de limitation de vitesse, l’exporter sous forme de fichier de modification OpenStreetMap et la vérifier avant de l’envoyer à OpenStreetMap (OSM).

Les captures d’écran ont été réalisées avec YouSpeed dans le simulateur d’un iPhone 17 et avec l’interface allemande. Les autorisations du microphone et de la reconnaissance vocale sont considérées comme accordées. Aucune saisie vocale en direct n’étant disponible, l’exemple utilise le résultat de reconnaissance supposé **30**. L’entrée « Durlacher Allee » est une démonstration et ne prouve pas que la route réelle doit être modifiée.

> **Sécurité :** configurez l’app avant le trajet. N’enregistrez une correction qu’à l’arrêt, dans un endroit sûr, ou en tant que passager. YouSpeed est une aide à la conduite ; les panneaux et le code de la route priment toujours.

## 1. Écran de conduite

![Écran de conduite YouSpeed dans le simulateur iPhone](user-guide/ios-driving-screen.png)

Le grand panneau affiche la limitation actuellement associée à la position à partir de la carte locale. Le nombre en dessous correspond à la vitesse GPS actuelle. Le bouton en forme d’insecte, en haut à gauche, ouvre **Lokale Erfassungen** (enregistrements locaux) ; la roue dentée, en bas à droite, ouvre les réglages.

## 2. Télécharger des cartes régionales

Ouvrez les réglages avec la roue dentée, puis faites défiler jusqu’à **Kartendaten-Download** (« Téléchargement des données cartographiques »). Les pays sont classés par ordre alphabétique. Les pays proposant des lots régionaux, comme **Deutschland**, affichent chaque région séparément.

![Réglages YouSpeed montrant les téléchargements régionaux allemands](user-guide/ios-regional-map-downloads.png)

1. Connectez l’iPhone à Internet, ouvrez **Einstellungen → Kartendaten-Download**, puis recherchez le pays ou la région nécessaire.
2. Touchez la flèche vers le bas à côté de la région, par exemple **Baden-Württemberg** ou **Bayern**.
3. Laissez YouSpeed ouvert jusqu’à la fin de la progression. Le lot devient ensuite disponible pour la correspondance cartographique hors ligne.
4. Répétez l’opération pour les autres régions nécessaires. Chaque lot peut être géré indépendamment.
5. Pour libérer de l’espace, utilisez la commande de suppression du lot téléchargé ou **Heruntergeladene Datenbanken loeschen (Seed behalten)** afin de supprimer tous les téléchargements tout en conservant les données initiales intégrées.

La capture utilise les données de test du simulateur ; ses états affichent donc `ready screenshot` et `screenshot`. Une installation normale affiche le lot actif et l’état réel du téléchargement.

## 3. Enregistrer une correction par la voix

1. Attendez que YouSpeed affiche la bonne route et la limitation concernée, avec une réception GPS correcte.
2. **Touchez deux fois le grand panneau de limitation.**
3. Lors de la première utilisation, autorisez l’accès au microphone et à la reconnaissance vocale. Dans ce guide, ces deux autorisations sont déjà considérées comme accordées.
4. Lorsque le panneau affiche `?` et que l’app indique **Jetzt sprechen** (« Parlez maintenant »), prononcez uniquement la nouvelle valeur, par exemple **« 30 »**. Vous pouvez également dire **« Fussgaengerzone »** pour une vitesse au pas.
5. YouSpeed enregistre le résultat localement. OpenStreetMap n’est jamais modifié automatiquement.

![YouSpeed attend la correction de limitation prononcée](user-guide/ios-correction-listening.png)

## 4. Vérifier et exporter l’enregistrement local

Ouvrez **Lokale Erfassungen** avec le bouton en forme d’insecte. Vérifiez l’heure, la rue, l’identifiant du chemin OSM, l’ancienne valeur (**alt**) et la nouvelle (**neu**). Supprimez l’entrée si la route ou la valeur reconnue est incorrecte.

![Enregistrement local YouSpeed montrant une correction de 50 à 30](user-guide/ios-local-recordings.png)

Touchez **changes.osc exportieren**, puis **In Dateien sichern** pour enregistrer `changes.osc` dans l’app Fichiers. Vous pouvez aussi transférer le fichier vers le Mac avec AirDrop ou une autre action de la feuille de partage.

![Feuille de partage iOS pour le fichier changes.osc exporté](user-guide/ios-osc-export.png)

L’export est une proposition qui contient des identifiants de chemins OSM et les valeurs `maxspeed` prévues. Il ne constitue pas un jeu de données OSM entièrement vérifié.

## 5. Vérifier la proposition OSC et l’envoyer à OSM

Utilisez le compte OSM dédié :

- Adresse de connexion : `raphael.volz@pm.me`
- Nom d’utilisateur OSM : `youspeed DOT de - mapping speed limits`

Le nom affiché dans le menu du compte Safari permet de confirmer quel compte est actif. Ne placez jamais l’adresse électronique ou le mot de passe dans le commentaire du groupe de modifications.

![OpenStreetMap dans Safari avec le compte de cartographie YouSpeed connecté](user-guide/osm-account.png)

### Procédure sûre avec JOSM

Le fichier `changes.osc` actuellement produit par YouSpeed contient uniquement l’identifiant de chaque chemin et le tag `maxspeed` proposé. Il ne contient ni la géométrie complète, ni la version actuelle de l’objet, ni ses autres tags. **N’envoyez pas directement la couche OSC importée.** Utilisez-la comme liste de contrôle et appliquez chaque modification confirmée à des données OSM fraîchement téléchargées :

1. Installez et ouvrez [JOSM](https://josm.openstreetmap.de/), puis inspectez `changes.osc` avec **Fichier → Ouvrir…**.
2. Pour chaque chemin indiqué, utilisez **Fichier → Télécharger un objet…** (`Ctrl+Maj+O`), sélectionnez **chemin**, saisissez son identifiant et téléchargez l’objet actuel depuis OSM. Téléchargez aussi la zone environnante et les objets parents lorsqu’ils concernent la route. Consultez le [guide JOSM « Download Object »](https://josm.openstreetmap.de/wiki/Help/Action/DownloadObject).
3. Comparez la valeur proposée à une observation réelle sur place. Vérifiez que le chemin représente le bon tronçon et que la limitation s’applique sur toute sa longueur.
4. Modifiez le chemin fraîchement téléchargé en conservant sa géométrie et tous les tags sans rapport avec la correction. N’utilisez `maxspeed=30` que si 30 s’applique dans les deux sens. Pour un panneau directionnel ou conditionnel, utilisez les tags OSM adaptés ; consultez la [documentation OSM de `maxspeed`](https://wiki.openstreetmap.org/wiki/Key%3Amaxspeed).
5. Dans les paramètres de connexion de JOSM, lancez l’autorisation OAuth. Safari doit ouvrir la page d’autorisation OSM. Vérifiez qu’elle affiche **youspeed DOT de - mapping speed limits**, puis autorisez JOSM.
6. Lancez la validation JOSM et corrigez les erreurs ou conflits. Actualisez les données si un autre contributeur les a modifiées pendant votre vérification.
7. Choisissez **Fichier → Envoyer les données** (`Ctrl+Maj+↑`). Vérifiez la liste exacte des objets modifiés. Ajoutez un commentaire explicite, par exemple `Mise à jour des limitations signalées après relevé sur place avec YouSpeed`, et indiquez `survey` comme source uniquement si un relevé sur place a réellement été effectué. Le [guide d’envoi JOSM](https://josm.openstreetmap.de/wiki/Help/Action/Upload) décrit la validation et la fenêtre d’envoi.
8. Ne cliquez sur **Envoyer les modifications** qu’après la vérification finale. Cette action publie la modification dans OSM sous le compte sélectionné ; ce n’est pas un test privé.

L’exemple simulé 50 → 30 de ce guide n’a volontairement **pas été envoyé**.

## Dépannage

- **L’écran « Jetzt sprechen » n’apparaît pas :** dans iOS, ouvrez **Réglages → Confidentialité et sécurité → Microphone** et **Reconnaissance vocale**, puis activez YouSpeed. La reconnaissance allemande sur l’appareil doit être disponible.
- **Mauvaise valeur ou mauvaise route :** supprimez l’entrée locale et recommencez lorsque la bonne route est associée.
- **Le bouton d’export ne produit pas de fichier utilisable :** vérifiez qu’au moins un enregistrement local valide est affiché.
- **JOSM signale des données incomplètes ou conflictuelles :** ne forcez pas l’envoi. Téléchargez à nouveau le chemin actuel et sa zone, appliquez le tag vérifié à cet objet complet, puis relancez la validation.
- **La liste régionale ou le téléchargement est indisponible :** vérifiez la connexion, rouvrez les réglages et réessayez. Les cartes déjà téléchargées restent utilisables hors ligne.
