#!/usr/bin/env node
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildReferencePages, referenceCopy, referenceRoute, youtube } from "./build_reference_pages.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const webRoot = path.join(repoRoot, "Web");
const siteBase = "https://youspeed.de";
const release = JSON.parse(readFileSync(path.join(__dirname, "release-1.3.json"), "utf8"));
const releaseUrl = "https://github.com/volzinnovation/youspeed.de/releases/tag/android-v1.3";
const apkUrl = "https://github.com/volzinnovation/youspeed.de/releases/download/android-v1.3/YouSpeed-1.3-100332.apk";
const checksumsUrl = "https://github.com/volzinnovation/youspeed.de/releases/download/android-v1.3/SHA256SUMS";

const locales = {
  de: {
    htmlLang: "de",
    ogLocale: "de_DE",
    route: "",
    label: "Deutsch",
    shortLabel: "DE",
    nav: {
      product: "App",
      warnings: "Warnstufen",
      offline: "Offline-Daten",
      trust: "Vertrauen",
    },
    aria: {
      menu: "Menü öffnen",
      languages: "Sprache wechseln",
      visual: "YouSpeed App-Bildschirme",
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
    nav: {
      product: "App",
      warnings: "Warnings",
      offline: "Offline data",
      trust: "Trust",
    },
    aria: {
      menu: "Open menu",
      languages: "Change language",
      visual: "YouSpeed app screens",
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
    nav: {
      product: "App",
      warnings: "Alertes",
      offline: "Donnees hors ligne",
      trust: "Confiance",
    },
    aria: {
      menu: "Ouvrir le menu",
      languages: "Changer de langue",
      visual: "Écrans de l'app YouSpeed",
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
    nav: {
      product: "App",
      warnings: "Waarschuwingen",
      offline: "Offline data",
      trust: "Vertrouwen",
    },
    aria: {
      menu: "Menu openen",
      languages: "Taal wijzigen",
      visual: "YouSpeed app-schermen",
    },
    warnings: {
      eyebrow: "Live weergave",
      title: "Duidelijke waarschuwingen onderweg",
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
const appStoreUrl = "https://apps.apple.com/de/app/youspeed-de/id6787469256";
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
    ["#launch", content.release.nav],
    ["#download", content.download.nav],
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
      softwareVersion: "1.3",
      downloadUrl: apkUrl,
      releaseNotes: releaseUrl,
      installUrl: [googlePlayUrl, appStoreUrl, apkUrl],
    },
    null,
    2,
  );
}

function renderPage(locale) {
  const content = { ...locales[locale], ...release[locale] };
  const pageUrl = absoluteUrl(locale);
  const assetPrefix = prefix(locale);
  const nav = [...navLinks(content),
    [rootRelative(locale, referenceRoute(locale, "signs")), referenceCopy[locale].signsNav],
    [rootRelative(locale, referenceRoute(locale, "fines")), referenceCopy[locale].finesNav],
  ]
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
              <a class="btn btn-primary" href="${apkUrl}">${escapeHtml(content.download.primary)}</a>
              <a class="btn btn-secondary" href="#launch">${escapeHtml(content.release.nav)}</a>
            </div>
            <p class="download-hint">${escapeHtml(content.download.compatibility)}</p>
            <div class="store-links">
              <a class="btn store-btn store-btn-google" href="${googlePlayUrl}" target="_blank" rel="noreferrer">
                <span><small>${escapeHtml(content.hero.googlePlay[0])}</small>${escapeHtml(content.hero.googlePlay[1])}</span>
              </a>
              <a class="btn store-btn store-btn-apple" href="${appStoreUrl}" target="_blank" rel="noreferrer">
                <span><small>${escapeHtml(content.hero.appStore[0])}</small>${escapeHtml(content.hero.appStore[1])}</span>
              </a>
            </div>
            <ul class="hero-facts" aria-label="YouSpeed facts">
              ${content.hero.facts.map((fact) => `<li>${escapeHtml(fact)}</li>`).join("")}
            </ul>
          </div>
          <figure class="release-hero-artwork reveal visible">
            <div class="hero-sign-circle" role="img" aria-label="${escapeHtml(content.release.artworkAlt)}">
              ${["de-274-50", "de-206", "de-283", "de-102", "de-205"].map((sign, index) => `<img class="hero-sign hero-sign-${index + 1}" src="${rootRelative(locale, `assets/release-1.3/signs/${sign}.png`)}" alt="" width="256" height="256" />`).join("")}
            </div>
          </figure>
        </div>
      </section>

      <section class="section container reference-discovery" id="nachschlagen">
        <div class="section-header section-header-left reveal">
          <p class="eyebrow">${escapeHtml(referenceCopy[locale].browseEyebrow)}</p>
          <h2>${escapeHtml(referenceCopy[locale].browseTitle)}</h2>
        </div>
        <div class="reference-discovery-grid">
          ${["signs", "fines"].map((type, index) => `<a class="reference-discovery-link reveal reveal-d${index + 1}" href="${rootRelative(locale, referenceRoute(locale, type))}">
            <span class="eyebrow">${escapeHtml(referenceCopy[locale][`${type}Coverage`])}</span>
            <h3>${escapeHtml(referenceCopy[locale][type])}<span aria-hidden="true"> ↗</span></h3>
            <p>${escapeHtml(referenceCopy[locale][`${type}Browse`])}</p>
            <span class="reference-discovery-action">${escapeHtml(referenceCopy[locale].browseAction)} <span aria-hidden="true">→</span></span>
          </a>`).join("")}
        </div>
      </section>

      <section class="section container release-section" id="launch">
        <div class="section-header section-header-left reveal">
          <p class="eyebrow">${escapeHtml(content.release.eyebrow)}</p>
          <h2>${escapeHtml(content.release.title)}</h2>
          <p>${escapeHtml(content.release.body)}</p>
        </div>
        <div class="release-features">${renderFeatureItems(content.release.items)}</div>
        <nav class="reference-home-links" aria-label="${escapeHtml(content.release.eyebrow)}">
          <a href="${rootRelative(locale, referenceRoute(locale, "signs"))}">${escapeHtml(referenceCopy[locale].signs)}</a>
          <a href="${rootRelative(locale, referenceRoute(locale, "fines"))}">${escapeHtml(referenceCopy[locale].fines)}</a>
        </nav>
        <div class="release-gallery">
          ${content.release.gallery.map(([file, alt], index) => `<figure class="reveal reveal-d${index + 1}">
            <img src="${rootRelative(locale, `assets/release-1.3/${locale}/${file}.webp`)}" alt="${escapeHtml(alt)}" loading="lazy" width="660" height="1434" />
          </figure>`).join("")}
        </div>
        <p class="artwork-note">${escapeHtml(content.release.artworkNote)}</p>
      </section>

      <section class="section section-contrast" id="download">
        <div class="container download-layout">
          <div class="section-header section-header-left reveal">
            <p class="eyebrow">${escapeHtml(content.download.nav)}</p>
            <h2>${escapeHtml(content.download.title)}</h2>
            <p>${escapeHtml(content.download.body)}</p>
            <div class="hero-actions">
              <a class="btn btn-primary" href="${apkUrl}">${escapeHtml(content.download.primary)}</a>
              <a class="btn btn-secondary" href="${releaseUrl}" target="_blank" rel="noreferrer">${escapeHtml(content.download.other)}</a>
            </div>
            <div class="store-links">
              <a class="btn store-btn store-btn-google" href="${googlePlayUrl}" target="_blank" rel="noreferrer"><span><small>${escapeHtml(content.hero.googlePlay[0])}</small>${escapeHtml(content.hero.googlePlay[1])}</span></a>
              <a class="btn store-btn store-btn-apple" href="${appStoreUrl}" target="_blank" rel="noreferrer"><span><small>${escapeHtml(content.hero.appStore[0])}</small>${escapeHtml(content.hero.appStore[1])}</span></a>
            </div>
            <p class="download-hint">${escapeHtml(content.download.compatibility)}</p>
            <p class="download-hint"><a href="${checksumsUrl}">${escapeHtml(content.download.checksums)}</a></p>
            <p class="download-hint">${escapeHtml(content.download.storeStatus)}</p>
          </div>
          <figure class="android-artwork reveal reveal-d2">
            <img src="${rootRelative(locale, `assets/release-1.3/${locale}/android-dashcam.webp`)}" alt="${escapeHtml(content.release.androidAlt)}" loading="lazy" width="960" height="540" />
            <figcaption>${escapeHtml(content.release.androidCaption)}</figcaption>
          </figure>
        </div>
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
        <div class="container">
          <div class="demo-copy reveal">
            <p class="eyebrow">YouTube · 1.3</p>
            <h2>${escapeHtml(referenceCopy[locale].videoTitle)}</h2>
            <p>${escapeHtml(referenceCopy[locale].videoBody)}</p>
          </div>
          <figure class="youtube-film reveal reveal-d2">
            <div class="youtube-stage" data-video-id="${escapeHtml(youtube.video_id)}" data-video-title="${escapeHtml(referenceCopy[locale].videoTitle)}">
              <button class="youtube-load" type="button" aria-label="${escapeHtml(referenceCopy[locale].videoLoad)}">
                <img src="${rootRelative(locale, "assets/release-1.3/feature-film-poster.jpg")}" alt="" width="1920" height="1080" loading="lazy" />
                <span>${escapeHtml(referenceCopy[locale].videoLoad)}</span>
              </button>
            </div>
            <figcaption>${escapeHtml(referenceCopy[locale].videoPrivacy)} <a href="${escapeHtml(youtube.url)}" target="_blank" rel="noreferrer">${escapeHtml(referenceCopy[locale].videoLink)}</a></figcaption>
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
          <p><a href="${rootRelative(locale, referenceRoute(locale, "signs"))}">${escapeHtml(referenceCopy[locale].signs)}</a> · <a href="${rootRelative(locale, referenceRoute(locale, "fines"))}">${escapeHtml(referenceCopy[locale].fines)}</a></p>
          <p><a href="https://github.com/volzinnovation/youspeed.de" target="_blank" rel="noreferrer">${escapeHtml(content.footer.github)}</a></p>
        </div>
      </div>
    </footer>

    <script>
      document.querySelectorAll(".youtube-load").forEach((button) => {
        button.addEventListener("click", () => {
          const stage = button.closest(".youtube-stage");
          const player = document.createElement("iframe");
          player.src = "https://www.youtube-nocookie.com/embed/" + stage.dataset.videoId + "?autoplay=1";
          player.title = stage.dataset.videoTitle;
          player.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
          player.allowFullscreen = true;
          player.referrerPolicy = "strict-origin-when-cross-origin";
          stage.replaceChildren(player);
        });
      });
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

function writeSitemap(referencePages) {
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
  const referenceUrls = referencePages.map((page) => `  <url>
    <loc>${siteBase}/${page.route}</loc>
    ${localeCodes.map((alternate) => `<xhtml:link rel="alternate" hreflang="${alternate}" href="${siteBase}/${referenceRoute(alternate, page.type, page.country)}" />`).join("\n    ")}
    <xhtml:link rel="alternate" hreflang="x-default" href="${siteBase}/${referenceRoute("de", page.type, page.country)}" />
  </url>`).join("\n");
  const urls = `${localizedUrls}
${referenceUrls}
  <url>
    <loc>${siteBase}/support/</loc>
  </url>
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
        description: release.en.description,
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
const referencePages = buildReferencePages(webRoot);
writeSitemap(referencePages);
writeRobots();
writeManifest();
console.log(`Built localized homepages and ${referencePages.length} reference pages: ${localeCodes.join(", ")}`);
