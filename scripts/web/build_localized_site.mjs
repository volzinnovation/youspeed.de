#!/usr/bin/env node
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const webRoot = path.join(repoRoot, "Web");
const siteBase = "https://youspeed.de";

const locales = {
  de: {
    htmlLang: "de",
    ogLocale: "de_DE",
    route: "",
    label: "Deutsch",
    shortLabel: "DE",
    title: "YouSpeed.de - Dein Tempo immer im Blick.",
    description:
      "YouSpeed zeigt erkannte Tempolimits live, warnt unverbindlich vor Bußgeld, Punkten und Fahrverbot und funktioniert mit lokalen Offline-Kartendaten.",
    nav: {
      product: "App",
      warnings: "Warnstufen",
      offline: "Offline-Daten",
      launch: "Status",
      trust: "Vertrauen",
    },
    aria: {
      menu: "Menü öffnen",
      languages: "Sprache wechseln",
      visual: "YouSpeed App-Bildschirme",
    },
    hero: {
      badge: "Ab 29. August 2026 · iOS & Android · Offline-Karten · Keine Werbung",
      title: "YouSpeed.de",
      kicker: "„Dein Tempo immer im Blick.“",
      lead:
        "Die App zeigt dir das erkannte Tempolimit und deine Geschwindigkeit klar im Blickfeld. Hinweise zu Bußgeld, Punkten und Fahrverbot bleiben unverbindlich und laufen auf lokalen Kartendaten.",
      googlePlay: ["Android-App", "Google Play"],
      testFlight: ["iPhone-Testversion", "TestFlight"],
      facts: ["Offline im Fahrbetrieb", "Keine Werbung, kein Tracking", "Lokale Kartendaten"],
    },
    launch: {
      eyebrow: "Öffentlicher Start · 29. August 2026",
      title: "YouSpeed startet auf iOS und Android",
      body:
        "Zum Start bietet YouSpeed lokale Tempolimit-Suche, verständliche Warnstufen, optionale Spracheingabe auf dem Gerät und Offline-Datenpakete für Länder und Regionen.",
      items: [
        {
          state: "iOS & Android",
          title: "Gemeinsame App-Basis",
          body:
            "App-Oberflächen, lokalisierte Texte und Offline-Datenverträge werden plattformübergreifend geführt.",
        },
        {
          state: "Offline-Betrieb",
          title: "Lokale Tempolimit-Daten",
          body:
            "Während der Fahrt arbeitet die App mit lokalen Kartendaten; Internet wird nur für optionale Datenaktualisierungen benötigt.",
        },
        {
          state: "Offene Daten",
          title: "OSM-Attribution",
          body:
            "Geschwindigkeitsdaten basieren auf OpenStreetMap und werden mit klarer Lizenz- und Quellenangabe verwendet.",
        },
      ],
    },
    warnings: {
      eyebrow: "Live-Anzeige",
      title: "Klare Ansagen bei zu hohem Tempo",
      body:
        "YouSpeed reduziert die Fahrtansicht auf Tempo, Limit und Konsequenz. Die Farben folgen dem App-Verhalten: neutral, Geldbuße, Punkte, Fahrverbot und Autobahn frei.",
      shots: [
        ["warn-level-0-no-violation.png", "Stufe 0", "Keine Überschreitung"],
        ["warn-level-1-money.png", "Stufe 1", "Bußgeld möglich"],
        ["warn-level-2-points.png", "Stufe 2", "Punkte möglich"],
        ["warn-level-3-driving-ban.png", "Stufe 3", "Fahrverbot möglich"],
        ["autobahn-unlimited-over-130.png", "Autobahn frei", "Ohne Tempolimit über 130 km/h"],
      ],
    },
    demo: {
      eyebrow: "App-Demo",
      title: "YouSpeed in Aktion",
      body:
        "Die kurze Demo zeigt die Fahrtansicht, erkannte Tempolimits und die Warnstufen direkt in der App.",
      ariaLabel: "Video-Demo der YouSpeed App",
      caption: "YouSpeed App-Demo",
      fallback: "Demo-Video öffnen",
    },
    features: {
      eyebrow: "Was die App kann",
      title: "Gebaut für Orientierung, nicht Ablenkung",
      body:
        "Die wichtigsten Funktionen kommen direkt aus den bestehenden App-Oberflächen und Store-Metadaten.",
      items: [
        ["Live-Tempolimit", "Aktuelles Limit und Geschwindigkeit stehen im Zentrum der Fahrtansicht."],
        ["Unverbindliche Hinweise", "Bußgeld, Punkte und Fahrverbot werden als Orientierung angezeigt, nicht als Rechtsberatung."],
        ["Offline-Karten", "Kartendaten liegen lokal auf dem Gerät und funktionieren während der Fahrt ohne Netz."],
        ["Lokale Korrektur", "Erkannte Tempolimits können per Sprache lokal erfasst und später geprüft werden."],
      ],
    },
    offline: {
      eyebrow: "Daten & Betrieb",
      title: "Offline zuerst, nachvollziehbar gepflegt",
      body:
        "Die App arbeitet mit lokalen OSM-Bundles, reproduzierbaren Targets und getrennten Release-Pfaden für iOS und Android.",
      metrics: [
        ["Top bundle target", "NLD, ROU, LUX", "kleine Länder als kompakte Einzelpakete"],
        ["Länder & Regionen", "Pakete", "regionale Shards für handhabbare Downloads"],
        ["Fahrtbetrieb", "lokal", "Internet nur für optionale Datenaktualisierungen"],
      ],
    },
    trust: {
      eyebrow: "Vertrauen",
      title: "Klare Grenzen, offene Daten",
      body:
        "YouSpeed ist ein Assistenzsystem. Verkehrszeichen, Verkehrsregeln und amtliche Bescheide bleiben maßgeblich.",
      items: [
        ["OpenStreetMap", "Geschwindigkeitsdaten basieren auf OSM-Tags wie maxspeed, maxspeed:type und source:maxspeed."],
        ["ODbL 1.0", "Die Daten stehen unter der Open Database License. Attribution geht an OpenStreetMap-Mitwirkende."],
        ["Privatsphäre", "Die App-Positionierung bleibt klar: keine Werbung und kein Tracking."],
      ],
    },
    cta: {
      title: "Fragen zu YouSpeed?",
      body:
        "Moonshots Studios betreibt und vertreibt YouSpeed. Für Datenschutz-, Store- und Vertriebsfragen führt der direkte Kontakt zum Betreiber.",
      primary: "Kontakt aufnehmen",
      secondary: "Warnstufen ansehen",
    },
    guide: "Benutzerhandbuch",
    footer: {
      imprint: "Impressum",
      company: "Moonshots Studios GmbH",
      address: "Auguststr. 2, 10117 Berlin, Deutschland",
      office: "Office Berlin: Skalitzer Straße 85/86, 10997 Berlin, Germany",
      development: "Technische Entwicklung: Prof. Dr. Raphael Volz, Hochschule Pforzheim",
      privacy: "Datenschutz",
      github: "Open Source auf GitHub",
    },
  },
  en: {
    htmlLang: "en",
    ogLocale: "en_US",
    route: "en/",
    label: "English",
    shortLabel: "EN",
    title: "YouSpeed.de - Live speed-limit assistance with offline maps",
    description:
      "YouSpeed shows detected speed limits live, gives advisory fine, points, and driving-ban warnings, and works with local offline map data.",
    nav: {
      product: "App",
      warnings: "Warnings",
      offline: "Offline data",
      launch: "Status",
      trust: "Trust",
    },
    aria: {
      menu: "Open menu",
      languages: "Change language",
      visual: "YouSpeed app screens",
    },
    hero: {
      badge: "iOS & Android · Offline maps · No ads",
      title: "YouSpeed.de",
      kicker: "Live speed-limit assistance",
      lead:
        "The app keeps the detected speed limit and your current speed visible at a glance. Fine, points, and driving-ban information stays advisory and runs on local map data.",
      googlePlay: ["Android app", "Google Play"],
      testFlight: ["iPhone beta", "TestFlight"],
      facts: ["Offline while driving", "No ads, no tracking", "Local map data"],
    },
    launch: {
      eyebrow: "Public launch · 29 August 2026",
      title: "YouSpeed launches on iOS and Android",
      body:
        "At launch, YouSpeed provides local speed-limit lookup, clear warning levels, optional on-device spoken capture, and offline bundles for countries and regions.",
      items: [
        {
          state: "iOS & Android",
          title: "Shared app basis",
          body:
            "App surfaces, localized text, and offline data contracts are maintained across platforms.",
        },
        {
          state: "Offline operation",
          title: "Local speed-limit data",
          body:
            "While driving, the app uses local map data; internet access is only needed for optional data updates.",
        },
        {
          state: "Open data",
          title: "OSM attribution",
          body:
            "Speed data is based on OpenStreetMap and is used with clear license and source attribution.",
        },
      ],
    },
    warnings: {
      eyebrow: "Live display",
      title: "Warning levels that stay readable in the car",
      body:
        "YouSpeed reduces the drive view to speed, limit, and consequence. The colors follow the app behavior: neutral, fine, points, driving ban, and unrestricted Autobahn.",
      shots: [
        ["warn-level-0-no-violation.png", "Level 0", "No violation"],
        ["warn-level-1-money.png", "Level 1", "Fine may apply"],
        ["warn-level-2-points.png", "Level 2", "Points may apply"],
        ["warn-level-3-driving-ban.png", "Level 3", "Driving ban may apply"],
        ["autobahn-unlimited-over-130.png", "Autobahn clear", "No speed limit above 130 km/h"],
      ],
    },
    demo: {
      eyebrow: "App demo",
      title: "See YouSpeed in action",
      body:
        "This short demo shows the driving view, detected speed limits, and warning levels directly in the app.",
      ariaLabel: "Video demo of the YouSpeed app",
      caption: "YouSpeed app demo",
      fallback: "Open the demo video",
    },
    features: {
      eyebrow: "What the app does",
      title: "Built for orientation, not distraction",
      body:
        "The core functions come directly from the existing app surfaces and store metadata.",
      items: [
        ["Live speed limit", "Current limit and speed sit at the center of the driving view."],
        ["Advisory warnings", "Fine, points, and driving-ban information is guidance, not legal advice."],
        ["Offline maps", "Map data lives locally on the device and works while driving without connectivity."],
        ["Local correction", "Detected limits can be captured locally by voice and reviewed later."],
      ],
    },
    offline: {
      eyebrow: "Data & operation",
      title: "Offline first, reproducibly maintained",
      body:
        "The app runs on local OSM bundles, reproducible targets, and separate release paths for iOS and Android.",
      metrics: [
        ["Top bundle target", "NLD, ROU, LUX", "small countries as compact single packages"],
        ["Countries & regions", "Packages", "regional shards for manageable downloads"],
        ["Driving mode", "local", "internet only for optional data updates"],
      ],
    },
    trust: {
      eyebrow: "Trust",
      title: "Clear limits, open data",
      body:
        "YouSpeed is an assistance app. Road signs, traffic rules, and official notices remain authoritative.",
      items: [
        ["OpenStreetMap", "Speed data is based on OSM tags such as maxspeed, maxspeed:type, and source:maxspeed."],
        ["ODbL 1.0", "The data is licensed under the Open Database License. Attribution goes to OpenStreetMap contributors."],
        ["Privacy", "The app positioning remains clear: no ads and no tracking."],
      ],
    },
    cta: {
      title: "Questions about YouSpeed?",
      body:
        "Moonshots Studios operates and distributes YouSpeed. For privacy, store, and distribution questions, contact the operator directly.",
      primary: "Contact us",
      secondary: "View warnings",
    },
    guide: "User guide",
    footer: {
      imprint: "Legal notice",
      company: "Moonshots Studios GmbH",
      address: "Auguststr. 2, 10117 Berlin, Germany",
      office: "Office Berlin: Skalitzer Straße 85/86, 10997 Berlin, Germany",
      development: "Technical development: Prof. Dr. Raphael Volz, Pforzheim University",
      privacy: "Privacy",
      github: "Open source on GitHub",
    },
  },
  fr: {
    htmlLang: "fr",
    ogLocale: "fr_FR",
    route: "fr/",
    label: "Français",
    shortLabel: "FR",
    title: "YouSpeed.de - Assistant de vitesse avec cartes hors ligne",
    description:
      "YouSpeed affiche les limitations détectées en direct, fournit des alertes indicatives pour amendes, points et interdictions de conduire, et fonctionne avec des cartes locales hors ligne.",
    nav: {
      product: "App",
      warnings: "Alertes",
      offline: "Donnees hors ligne",
      launch: "Statut",
      trust: "Confiance",
    },
    aria: {
      menu: "Ouvrir le menu",
      languages: "Changer de langue",
      visual: "Écrans de l'app YouSpeed",
    },
    hero: {
      badge: "iOS & Android · Cartes hors ligne · Sans publicité",
      title: "YouSpeed.de",
      kicker: "Assistant de limitation de vitesse",
      lead:
        "L'app garde la limitation détectée et votre vitesse actuelle visibles en un coup d'oeil. Les informations d'amende, de points et d'interdiction restent indicatives et s'appuient sur des données locales.",
      googlePlay: ["App Android", "Google Play"],
      testFlight: ["Test iPhone", "TestFlight"],
      facts: ["Hors ligne en conduite", "Sans publicité, sans suivi", "Données cartographiques locales"],
    },
    launch: {
      eyebrow: "Lancement public · 29 août 2026",
      title: "YouSpeed arrive sur iOS et Android",
      body:
        "Au lancement, YouSpeed proposera la recherche locale des limitations, des niveaux d'alerte clairs, la saisie vocale optionnelle sur l'appareil et des bundles hors ligne pour pays et régions.",
      items: [
        {
          state: "iOS & Android",
          title: "Base d'app commune",
          body:
            "Les interfaces, les textes localisés et les contrats de données hors ligne sont maintenus entre plateformes.",
        },
        {
          state: "Fonctionnement hors ligne",
          title: "Données de vitesse locales",
          body:
            "En conduite, l'app utilise des données cartographiques locales ; internet n'est nécessaire que pour les mises à jour optionnelles.",
        },
        {
          state: "Données ouvertes",
          title: "Attribution OSM",
          body:
            "Les données de vitesse reposent sur OpenStreetMap et sont utilisées avec une attribution claire des licences et sources.",
        },
      ],
    },
    warnings: {
      eyebrow: "Affichage en direct",
      title: "Des niveaux d'alerte lisibles en voiture",
      body:
        "YouSpeed réduit la vue conduite à la vitesse, la limitation et la conséquence. Les couleurs suivent l'app : neutre, amende, points, interdiction et Autobahn sans limitation.",
      shots: [
        ["warn-level-0-no-violation.png", "Niveau 0", "Pas d'excès"],
        ["warn-level-1-money.png", "Niveau 1", "Amende possible"],
        ["warn-level-2-points.png", "Niveau 2", "Points possibles"],
        ["warn-level-3-driving-ban.png", "Niveau 3", "Interdiction possible"],
        ["autobahn-unlimited-over-130.png", "Autobahn libre", "Sans limitation au-dessus de 130 km/h"],
      ],
    },
    demo: {
      eyebrow: "Démo de l’app",
      title: "YouSpeed en action",
      body:
        "Cette courte démo présente la vue de conduite, les limitations détectées et les niveaux d’alerte directement dans l’app.",
      ariaLabel: "Démo vidéo de l’app YouSpeed",
      caption: "Démo de l’app YouSpeed",
      fallback: "Ouvrir la vidéo de démonstration",
    },
    features: {
      eyebrow: "Ce que fait l'app",
      title: "Conçue pour orienter, pas distraire",
      body:
        "Les fonctions principales viennent directement des interfaces existantes et des métadonnées de store.",
      items: [
        ["Limitation en direct", "La limitation actuelle et la vitesse restent au centre de la vue de conduite."],
        ["Alertes indicatives", "Amendes, points et interdictions sont des indications, pas un conseil juridique."],
        ["Cartes hors ligne", "Les données cartographiques sont locales et fonctionnent en conduite sans réseau."],
        ["Correction locale", "Les limitations détectées peuvent être saisies localement par la voix puis vérifiées plus tard."],
      ],
    },
    offline: {
      eyebrow: "Données & fonctionnement",
      title: "Hors ligne d'abord, maintenance reproductible",
      body:
        "L'app utilise des bundles OSM locaux, des cibles reproductibles et des chemins de sortie séparés pour iOS et Android.",
      metrics: [
        ["Premières cibles", "NLD, ROU, LUX", "petits pays en packages compacts"],
        ["Pays & régions", "Packages", "shards régionaux pour des téléchargements gérables"],
        ["Mode conduite", "local", "internet seulement pour les mises à jour optionnelles"],
      ],
    },
    trust: {
      eyebrow: "Confiance",
      title: "Limites claires, données ouvertes",
      body:
        "YouSpeed est une app d'assistance. Les panneaux, les règles de circulation et les avis officiels font foi.",
      items: [
        ["OpenStreetMap", "Les données de vitesse reposent sur les tags OSM comme maxspeed, maxspeed:type et source:maxspeed."],
        ["ODbL 1.0", "Les données sont sous Open Database License. L'attribution revient aux contributeurs OpenStreetMap."],
        ["Confidentialité", "Le positionnement reste clair : pas de publicité et pas de suivi."],
      ],
    },
    cta: {
      title: "Questions sur YouSpeed ?",
      body:
        "Moonshots Studios exploite et distribue YouSpeed. Pour les questions de confidentialité, de store et de distribution, contactez directement l'exploitant.",
      primary: "Nous contacter",
      secondary: "Voir les alertes",
    },
    guide: "Guide utilisateur",
    footer: {
      imprint: "Mentions legales",
      company: "Moonshots Studios GmbH",
      address: "Auguststr. 2, 10117 Berlin, Allemagne",
      office: "Office Berlin: Skalitzer Straße 85/86, 10997 Berlin, Germany",
      development: "Développement technique : Prof. Dr. Raphael Volz, Hochschule Pforzheim",
      privacy: "Confidentialite",
      github: "Open source sur GitHub",
    },
  },
  nl: {
    htmlLang: "nl",
    ogLocale: "nl_NL",
    route: "nl/",
    label: "Nederlands",
    shortLabel: "NL",
    title: "YouSpeed.de - Live snelheidslimietassistent met offline kaarten",
    description:
      "YouSpeed toont herkende snelheidslimieten live, geeft indicatieve waarschuwingen voor boetes, punten en rijverboden, en werkt met lokale offline kaartgegevens.",
    nav: {
      product: "App",
      warnings: "Waarschuwingen",
      offline: "Offline data",
      launch: "Status",
      trust: "Vertrouwen",
    },
    aria: {
      menu: "Menu openen",
      languages: "Taal wijzigen",
      visual: "YouSpeed app-schermen",
    },
    hero: {
      badge: "iOS & Android · Offline kaarten · Geen advertenties",
      title: "YouSpeed.de",
      kicker: "Live snelheidslimietassistent",
      lead:
        "De app houdt de herkende snelheidslimiet en je actuele snelheid direct zichtbaar. Boete-, punten- en rijverbodsinformatie blijft indicatief en draait op lokale kaartgegevens.",
      googlePlay: ["Android-app", "Google Play"],
      testFlight: ["iPhone-test", "TestFlight"],
      facts: ["Offline tijdens rijden", "Geen advertenties, geen tracking", "Lokale kaartgegevens"],
    },
    launch: {
      eyebrow: "Publieke lancering · 29 augustus 2026",
      title: "YouSpeed start op iOS en Android",
      body:
        "Bij de lancering biedt YouSpeed lokale snelheidslimietherkenning, duidelijke waarschuwingen, optionele spraakinvoer op het apparaat en offline bundels voor landen en regio's.",
      items: [
        {
          state: "iOS & Android",
          title: "Gedeelde appbasis",
          body:
            "App-schermen, gelokaliseerde teksten en offline datacontracten worden platformoverstijgend beheerd.",
        },
        {
          state: "Offline werking",
          title: "Lokale snelheidsdata",
          body:
            "Tijdens het rijden gebruikt de app lokale kaartgegevens; internet is alleen nodig voor optionele data-updates.",
        },
        {
          state: "Open data",
          title: "OSM-attributie",
          body:
            "Snelheidsgegevens zijn gebaseerd op OpenStreetMap en worden gebruikt met duidelijke licentie- en bronvermelding.",
        },
      ],
    },
    warnings: {
      eyebrow: "Live weergave",
      title: "Waarschuwingsniveaus die in de auto leesbaar blijven",
      body:
        "YouSpeed reduceert de rijweergave tot snelheid, limiet en gevolg. De kleuren volgen de app: neutraal, boete, punten, rijverbod en onbeperkte Autobahn.",
      shots: [
        ["warn-level-0-no-violation.png", "Niveau 0", "Geen overtreding"],
        ["warn-level-1-money.png", "Niveau 1", "Boete mogelijk"],
        ["warn-level-2-points.png", "Niveau 2", "Punten mogelijk"],
        ["warn-level-3-driving-ban.png", "Niveau 3", "Rijverbod mogelijk"],
        ["autobahn-unlimited-over-130.png", "Autobahn vrij", "Geen limiet boven 130 km/u"],
      ],
    },
    demo: {
      eyebrow: "App-demo",
      title: "Bekijk YouSpeed in actie",
      body:
        "Deze korte demo toont de rijweergave, herkende snelheidslimieten en waarschuwingsniveaus rechtstreeks in de app.",
      ariaLabel: "Videodemo van de YouSpeed-app",
      caption: "YouSpeed-app-demo",
      fallback: "De demovideo openen",
    },
    features: {
      eyebrow: "Wat de app doet",
      title: "Gebouwd voor oriëntatie, niet voor afleiding",
      body:
        "De kernfuncties komen rechtstreeks uit de bestaande app-schermen en storemetadata.",
      items: [
        ["Live snelheidslimiet", "De actuele limiet en snelheid staan centraal in de rijweergave."],
        ["Indicatieve waarschuwingen", "Boetes, punten en rijverboden zijn oriëntatie, geen juridisch advies."],
        ["Offline kaarten", "Kaartgegevens staan lokaal op het apparaat en werken onderweg zonder netwerk."],
        ["Lokale correctie", "Herkende limieten kunnen lokaal via spraak worden vastgelegd en later gecontroleerd."],
      ],
    },
    offline: {
      eyebrow: "Data & werking",
      title: "Offline eerst, reproduceerbaar onderhouden",
      body:
        "De app draait op lokale OSM-bundles, reproduceerbare doelen en aparte releasepaden voor iOS en Android.",
      metrics: [
        ["Top bundledoel", "NLD, ROU, LUX", "kleine landen als compacte pakketten"],
        ["Landen & regio's", "Pakketten", "regionale shards voor beheersbare downloads"],
        ["Rijmodus", "lokaal", "internet alleen voor optionele data-updates"],
      ],
    },
    trust: {
      eyebrow: "Vertrouwen",
      title: "Duidelijke grenzen, open data",
      body:
        "YouSpeed is een assistentie-app. Verkeersborden, verkeersregels en officiële besluiten blijven bepalend.",
      items: [
        ["OpenStreetMap", "Snelheidsgegevens zijn gebaseerd op OSM-tags zoals maxspeed, maxspeed:type en source:maxspeed."],
        ["ODbL 1.0", "De data valt onder de Open Database License. Attributie gaat naar OpenStreetMap-bijdragers."],
        ["Privacy", "De positionering blijft duidelijk: geen advertenties en geen tracking."],
      ],
    },
    cta: {
      title: "Vragen over YouSpeed?",
      body:
        "Moonshots Studios beheert en distribueert YouSpeed. Neem voor privacy-, store- en distributievragen rechtstreeks contact op met de exploitant.",
      primary: "Contact opnemen",
      secondary: "Waarschuwingen bekijken",
    },
    guide: "Gebruikershandleiding",
    footer: {
      imprint: "Juridische informatie",
      company: "Moonshots Studios GmbH",
      address: "Auguststr. 2, 10117 Berlijn, Duitsland",
      office: "Office Berlin: Skalitzer Straße 85/86, 10997 Berlin, Germany",
      development: "Technische ontwikkeling: Prof. Dr. Raphael Volz, Hochschule Pforzheim",
      privacy: "Privacy",
      github: "Open source op GitHub",
    },
  },
};

const localeCodes = Object.keys(locales);
const mailto =
  "mailto:studios@moonshots.gmbh?subject=YouSpeed";
const googlePlayUrl =
  "https://play.google.com/store/apps/details?id=de.youspeed.android";
const testFlightUrl = "https://testflight.apple.com/join/k3a1pgce";
const guideFiles = {
  de: "USER_GUIDE_DE.md",
  en: "USER_GUIDE.md",
  fr: "USER_GUIDE_FR.md",
  nl: "USER_GUIDE_NL.md",
};

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function absoluteUrl(locale) {
  return `${siteBase}/${locales[locale].route}`;
}

function prefix(locale) {
  return locale === "de" ? "./" : "../";
}

function localizedHref(fromLocale, toLocale) {
  if (toLocale === "de") {
    return fromLocale === "de" ? "./" : "../";
  }
  return fromLocale === "de"
    ? `./${locales[toLocale].route}`
    : `../${locales[toLocale].route}`;
}

function rootRelative(locale, assetPath) {
  return `${prefix(locale)}${assetPath}`;
}

function guideUrl(locale) {
  return `https://github.com/volzinnovation/youspeed.de/blob/main/docs/${guideFiles[locale]}`;
}

function navLinks(content) {
  return [
    ["#app", content.nav.product],
    ["#warnstufen", content.nav.warnings],
    ["#launch", content.nav.launch],
    ["#trust", content.nav.trust],
  ];
}

function renderLanguageSwitch(currentLocale) {
  return `
        <div class="language-switch" aria-label="${escapeHtml(locales[currentLocale].aria.languages)}">
          ${localeCodes
            .map((locale) => {
              const current = locale === currentLocale;
              return `<a href="${localizedHref(currentLocale, locale)}" ${current ? 'aria-current="page"' : ""}>${escapeHtml(locales[locale].shortLabel)}</a>`;
            })
            .join("")}
        </div>`;
}

function renderStatusItems(items) {
  return items
    .map(
      (item, index) => `
          <article class="status-item reveal reveal-d${index + 1}">
            <span>${escapeHtml(item.state)}</span>
            <h3>${escapeHtml(item.title)}</h3>
            <p>${escapeHtml(item.body)}</p>
          </article>`,
    )
    .join("");
}

function renderFeatureItems(items) {
  return items
    .map(
      ([title, body], index) => `
          <article class="feature-item reveal reveal-d${index + 1}">
            <span class="feature-index">0${index + 1}</span>
            <h3>${escapeHtml(title)}</h3>
            <p>${escapeHtml(body)}</p>
          </article>`,
    )
    .join("");
}

function renderShotItems(locale, shots) {
  return shots
    .map(
      ([file, title, body], index) => `
          <figure class="shot reveal reveal-d${index + 1}">
            <img src="${rootRelative(locale, `assets/screenshots/${file}`)}" alt="${escapeHtml(`${title}: ${body}`)}" loading="lazy" width="1179" height="2556" />
            <figcaption>
              <strong>${escapeHtml(title)}</strong>
              <span>${escapeHtml(body)}</span>
            </figcaption>
          </figure>`,
    )
    .join("");
}

function renderMetrics(metrics) {
  return metrics
    .map(
      ([label, value, body]) => `
          <div class="metric reveal">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}</strong>
            <p>${escapeHtml(body)}</p>
          </div>`,
    )
    .join("");
}

function renderTrustItems(items) {
  return items
    .map(
      ([title, body], index) => `
          <article class="trust-item reveal reveal-d${index + 1}">
            <h3>${escapeHtml(title)}</h3>
            <p>${escapeHtml(body)}</p>
          </article>`,
    )
    .join("");
}

function renderAlternates() {
  const links = localeCodes
    .map(
      (locale) =>
        `<link rel="alternate" hreflang="${locale}" href="${absoluteUrl(locale)}" />`,
    )
    .join("\n    ");
  return `${links}\n    <link rel="alternate" hreflang="x-default" href="${absoluteUrl("de")}" />`;
}

function renderStructuredData(locale, content) {
  return JSON.stringify(
    {
      "@context": "https://schema.org",
      "@type": "SoftwareApplication",
      name: "YouSpeed.de",
      applicationCategory: "NavigationApplication",
      operatingSystem: "iOS, Android",
      url: absoluteUrl(locale),
      description: content.description,
      inLanguage: content.htmlLang,
      publisher: {
        "@type": "Organization",
        name: "Moonshots Studios GmbH",
        url: "https://studios.moonshots.gmbh",
      },
      sameAs: ["https://github.com/volzinnovation/youspeed.de"],
      installUrl: [googlePlayUrl, testFlightUrl],
    },
    null,
    2,
  );
}

function renderPage(locale) {
  const content = locales[locale];
  const pageUrl = absoluteUrl(locale);
  const assetPrefix = prefix(locale);
  const nav = navLinks(content)
    .map(([href, label]) => `<a href="${href}">${escapeHtml(label)}</a>`)
    .join("");
  const socialImage = `${siteBase}/assets/social/youspeed-og-${locale}.png`;

  return `<!doctype html>
<html lang="${content.htmlLang}">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${escapeHtml(content.title)}</title>
    <meta name="description" content="${escapeHtml(content.description)}" />
    <meta name="robots" content="index,follow,max-image-preview:large" />
    <link rel="canonical" href="${pageUrl}" />
    ${renderAlternates()}
    <meta property="og:site_name" content="YouSpeed.de" />
    <meta property="og:title" content="${escapeHtml(content.title)}" />
    <meta property="og:description" content="${escapeHtml(content.description)}" />
    <meta property="og:type" content="website" />
    <meta property="og:url" content="${pageUrl}" />
    <meta property="og:locale" content="${content.ogLocale}" />
    ${localeCodes
      .filter((candidate) => candidate !== locale)
      .map((candidate) => `<meta property="og:locale:alternate" content="${locales[candidate].ogLocale}" />`)
      .join("\n    ")}
    <meta property="og:image" content="${socialImage}" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
    <meta property="og:image:alt" content="${escapeHtml(`${content.hero.title} - ${content.hero.kicker}`)}" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="${escapeHtml(content.title)}" />
    <meta name="twitter:description" content="${escapeHtml(content.description)}" />
    <meta name="twitter:image" content="${socialImage}" />
    <meta name="theme-color" content="#0b0e10" />
    <script>document.documentElement.classList.add("js");</script>
    <link rel="icon" href="${assetPrefix}assets/icons/favicon.svg" type="image/svg+xml" />
    <link rel="icon" href="${assetPrefix}assets/icons/favicon-32.png" sizes="32x32" />
    <link rel="apple-touch-icon" href="${assetPrefix}assets/icons/apple-touch-icon.png" />
    <link rel="manifest" href="${assetPrefix}site.webmanifest" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Chakra+Petch:wght@500;600;700&display=swap"
      rel="stylesheet"
    />
    <link rel="stylesheet" href="${assetPrefix}styles.css" />
    <script type="application/ld+json">
${renderStructuredData(locale, content)}
    </script>
  </head>
  <body>
    <nav class="nav" id="navbar" aria-label="YouSpeed.de">
      <a class="nav-brand" href="${localizedHref(locale, locale)}" aria-label="YouSpeed.de">
        <img class="brand-icon" src="${assetPrefix}assets/icons/app-icon-mark-192.png" alt="" width="36" height="36" />
        <span>YouSpeed.de</span>
      </a>
      <div class="nav-links" id="nav-links">${nav}</div>
${renderLanguageSwitch(locale)}
      <button class="hamburger" id="hamburger" aria-label="${escapeHtml(content.aria.menu)}" aria-controls="mobile-menu" aria-expanded="false">
        <span></span><span></span><span></span>
      </button>
    </nav>

    <div class="mobile-menu" id="mobile-menu">
      ${nav}
${renderLanguageSwitch(locale)}
    </div>

    <main>
      <section class="hero" id="app">
        <div class="hero-grid">
          <div class="hero-copy">
            <p class="eyebrow">${escapeHtml(content.hero.badge)}</p>
            <h1>${escapeHtml(content.hero.title)}</h1>
            <p class="hero-kicker">${escapeHtml(content.hero.kicker)}</p>
            <p class="lead">${escapeHtml(content.hero.lead)}</p>
            <div class="hero-actions">
              <a class="btn store-btn store-btn-google" href="${googlePlayUrl}" target="_blank" rel="noreferrer">
                <span><small>${escapeHtml(content.hero.googlePlay[0])}</small>${escapeHtml(content.hero.googlePlay[1])}</span>
              </a>
              <a class="btn store-btn store-btn-apple" href="${testFlightUrl}" target="_blank" rel="noreferrer">
                <span><small>${escapeHtml(content.hero.testFlight[0])}</small>${escapeHtml(content.hero.testFlight[1])}</span>
              </a>
            </div>
            <ul class="hero-facts" aria-label="YouSpeed facts">
              ${content.hero.facts.map((fact) => `<li>${escapeHtml(fact)}</li>`).join("")}
            </ul>
          </div>
          <div class="app-visual reveal visible" aria-label="${escapeHtml(content.aria.visual)}">
            <div class="road-lines" aria-hidden="true"></div>
            <figure class="phone-frame phone-side phone-side-left">
              <img src="${rootRelative(locale, "assets/screenshots/warn-level-1-money.png")}" alt="" width="1179" height="2556" />
            </figure>
            <figure class="phone-frame phone-main">
              <img src="${rootRelative(locale, "assets/screenshots/warn-level-2-points.png")}" alt="" width="1179" height="2556" />
            </figure>
            <figure class="phone-frame phone-side phone-side-right">
              <img src="${rootRelative(locale, "assets/screenshots/autobahn-unlimited-over-130.png")}" alt="" width="1179" height="2556" />
            </figure>
          </div>
        </div>
      </section>

      <section class="section container" id="launch">
        <div class="section-header reveal">
          <p class="eyebrow">${escapeHtml(content.launch.eyebrow)}</p>
          <h2>${escapeHtml(content.launch.title)}</h2>
          <p>${escapeHtml(content.launch.body)}</p>
        </div>
        <div class="status-grid">${renderStatusItems(content.launch.items)}</div>
      </section>

      <section class="section section-contrast" id="warnstufen">
        <div class="container">
          <div class="section-header reveal">
            <p class="eyebrow">${escapeHtml(content.warnings.eyebrow)}</p>
            <h2>${escapeHtml(content.warnings.title)}</h2>
            <p>${escapeHtml(content.warnings.body)}</p>
          </div>
          <div class="shots-grid">${renderShotItems(locale, content.warnings.shots)}</div>
        </div>
      </section>

      <section class="section demo-showcase" id="demo">
        <div class="container demo-layout">
          <div class="demo-copy reveal">
            <p class="eyebrow">${escapeHtml(content.demo.eyebrow)}</p>
            <h2>${escapeHtml(content.demo.title)}</h2>
            <p>${escapeHtml(content.demo.body)}</p>
          </div>
          <figure class="demo-player reveal reveal-d2">
            <video controls playsinline preload="metadata" aria-label="${escapeHtml(content.demo.ariaLabel)}" width="590" height="1280">
              <source src="${rootRelative(locale, "assets/video/youspeed-demo.mp4")}" type="video/mp4" />
              <a href="${rootRelative(locale, "assets/video/youspeed-demo.mp4")}">${escapeHtml(content.demo.fallback)}</a>
            </video>
            <figcaption>${escapeHtml(content.demo.caption)}</figcaption>
          </figure>
        </div>
      </section>

      <section class="section section-contrast" id="trust">
        <div class="container">
          <div class="section-header reveal">
            <p class="eyebrow">${escapeHtml(content.trust.eyebrow)}</p>
            <h2>${escapeHtml(content.trust.title)}</h2>
            <p>${escapeHtml(content.trust.body)}</p>
          </div>
          <div class="trust-grid">${renderTrustItems(content.trust.items)}</div>
          <p class="license-note reveal">
            <a href="https://opendatacommons.org/licenses/odbl/1-0/" target="_blank" rel="noreferrer">ODbL 1.0</a>
            ·
            <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>
          </p>
        </div>
      </section>

      <section class="section container">
        <div class="cta-band reveal">
          <div>
            <h2>${escapeHtml(content.cta.title)}</h2>
            <p>${escapeHtml(content.cta.body)}</p>
          </div>
          <div class="cta-actions">
            <a class="btn btn-primary" href="${mailto}">${escapeHtml(content.cta.primary)}</a>
            <a class="btn btn-secondary" href="${guideUrl(locale)}" target="_blank" rel="noreferrer">${escapeHtml(content.guide)}</a>
            <a class="btn btn-secondary" href="#warnstufen">${escapeHtml(content.cta.secondary)}</a>
          </div>
        </div>
      </section>
    </main>

    <footer class="site-footer">
      <div class="container footer-grid">
        <div>
          <p><strong>${escapeHtml(content.footer.imprint)}</strong></p>
          <p><a href="https://studios.moonshots.gmbh/" target="_blank" rel="noreferrer">${escapeHtml(content.footer.company)}</a></p>
          <p>${escapeHtml(content.footer.address)}</p>
          <p>${escapeHtml(content.footer.office)}</p>
        </div>
        <div>
          <p>${escapeHtml(content.footer.development)}</p>
          <p><a href="mailto:studios@moonshots.gmbh">studios@moonshots.gmbh</a></p>
          <p><a href="${assetPrefix}datenschutz.html">${escapeHtml(content.footer.privacy)}</a></p>
          <p><a href="${guideUrl(locale)}" target="_blank" rel="noreferrer">${escapeHtml(content.guide)}</a></p>
          <p><a href="https://github.com/volzinnovation/youspeed.de" target="_blank" rel="noreferrer">${escapeHtml(content.footer.github)}</a></p>
        </div>
      </div>
    </footer>

    <script>
      const reveals = document.querySelectorAll(".reveal");
      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              entry.target.classList.add("visible");
              observer.unobserve(entry.target);
            }
          });
        },
        { threshold: 0.14 },
      );
      reveals.forEach((element) => observer.observe(element));

      const hamburger = document.getElementById("hamburger");
      const mobileMenu = document.getElementById("mobile-menu");
      hamburger.addEventListener("click", () => {
        const isOpen = hamburger.classList.toggle("open");
        mobileMenu.classList.toggle("open", isOpen);
        hamburger.setAttribute("aria-expanded", String(isOpen));
      });
      mobileMenu.querySelectorAll("a").forEach((link) => {
        link.addEventListener("click", () => {
          hamburger.classList.remove("open");
          mobileMenu.classList.remove("open");
          hamburger.setAttribute("aria-expanded", "false");
        });
      });

      const navElement = document.getElementById("navbar");
      window.addEventListener("scroll", () => {
        navElement.classList.toggle("scrolled", window.scrollY > 32);
      });
    </script>
  </body>
</html>
`;
}

function writePage(locale) {
  const content = locales[locale];
  const dir = path.join(webRoot, content.route);
  mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(dir, "index.html"), renderPage(locale));
}

function writeSitemap() {
  const localizedUrls = localeCodes
    .map(
      (locale) => `  <url>
    <loc>${absoluteUrl(locale)}</loc>
    ${localeCodes
      .map(
        (alternate) =>
          `<xhtml:link rel="alternate" hreflang="${alternate}" href="${absoluteUrl(alternate)}" />`,
      )
      .join("\n    ")}
    <xhtml:link rel="alternate" hreflang="x-default" href="${absoluteUrl("de")}" />
  </url>`,
    )
    .join("\n");
  const urls = `${localizedUrls}
  <url>
    <loc>${siteBase}/datenschutz.html</loc>
  </url>`;

  writeFileSync(
    path.join(webRoot, "sitemap.xml"),
    `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
${urls}
</urlset>
`,
  );
}

function writeRobots() {
  writeFileSync(
    path.join(webRoot, "robots.txt"),
    `User-agent: *
Allow: /

Sitemap: ${siteBase}/sitemap.xml
`,
  );
}

function writeManifest() {
  writeFileSync(
    path.join(webRoot, "site.webmanifest"),
    `${JSON.stringify(
      {
        name: "YouSpeed.de",
        short_name: "YouSpeed.de",
        description: locales.en.description,
        start_url: "/",
        display: "standalone",
        background_color: "#0b0e10",
        theme_color: "#0b0e10",
        icons: [
          {
            src: "/assets/icons/app-icon-192.png",
            sizes: "192x192",
            type: "image/png",
          },
          {
            src: "/assets/icons/app-icon-512.png",
            sizes: "512x512",
            type: "image/png",
          },
        ],
      },
      null,
      2,
    )}
`,
  );
}

localeCodes.forEach(writePage);
writeSitemap();
writeRobots();
writeManifest();
console.log(`Built localized Web pages: ${localeCodes.join(", ")}`);
