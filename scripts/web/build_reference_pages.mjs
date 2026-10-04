import { copyFileSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const readJson = (file) => JSON.parse(readFileSync(path.join(repoRoot, file), "utf8"));
const penalty = require("../../shared/penalty-documentation/renderer.js");
const catalogue = require("../../shared/traffic-sign-documentation/renderer.js");
const penaltyText = readJson("shared/penalty-documentation/translations.json");
const signText = readJson("shared/traffic-sign-documentation/translations.json");
export const referenceCopy = readJson("scripts/web/reference-copy.json");
export const storeUrls = {
  google: "https://play.google.com/store/apps/details?id=de.youspeed.android",
  apple: "https://apps.apple.com/de/app/youspeed-de/id6787469256",
};
export const youtube = readJson("store/android/metadata/youtube-preview-1.3.json");
const countryCodes = { DEU: "DE", FRA: "FR", CHE: "CH", BEL: "BE", NLD: "NL", GBR: "GB", LUX: "LU", LIE: "LI", MCO: "MC", ROU: "RO", SWE: "SE", ISL: "IS" };
const signCountries = ["DE", "FR", "CH", "BE", "NL"];
const base = "https://youspeed.de/";
const languages = Object.keys(referenceCopy);
export const html = (value) => String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const countryName = (lang, code) => new Intl.DisplayNames([lang], { type: "region" }).of(code);
const slug = (name) => name.toLowerCase().replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
export const homeRoute = (lang) => lang === "de" ? "" : `${lang}/`;
export const referenceRoute = (lang, type, country) => `${homeRoute(lang)}${referenceCopy[lang][`${type}Slug`]}${country ? `/${slug(countryName(lang, country))}` : ""}.html`;
const localHref = (route, target) => path.posix.relative(path.posix.dirname(route), target || ".") || "./";
const rootPrefix = (route) => "../".repeat(route.split("/").length - 1) || "./";
const link = (url, text) => `<a href="${html(url)}" rel="noreferrer">${html(text)}</a>`;

export function storeBanner(lang = "de", route = "index.html") {
  const text = referenceCopy[lang] || referenceCopy.de;
  return `<!-- app-store-banner:start --><aside class="app-store-banner" aria-label="YouSpeed App"><a class="app-banner-icon" href="${localHref(route, homeRoute(lang))}" aria-label="YouSpeed"><img src="${rootPrefix(route)}assets/icons/app-icon-mark-192.png" alt="YouSpeed" width="40" height="40" /></a><div><strong>YouSpeed · ${html(text.banner)}</strong><p>${html(text.bannerBody)}</p></div><a class="btn store-btn store-btn-google" href="${storeUrls.google}" target="_blank" rel="noreferrer"><span><small>Android</small>Google Play</span></a><a class="btn store-btn store-btn-apple" href="${storeUrls.apple}" target="_blank" rel="noreferrer"><span><small>iPhone</small>App Store</span></a></aside><!-- app-store-banner:end -->`;
}

const manifests = ["manifest.json", ...["FR", "NL", "BE", "CH"].map((code) => `national/${code}/manifest.json`)]
  .map((file) => readJson(`shared/tsr/sign-pictograms/${file}`));
const artworks = new Map(manifests.flatMap((manifest) => manifest.artworks.map((art) => [`tsr/sign-pictograms/${art.png_path}`, art])));
const plain = (value = "") => value.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

export function publicArtwork(sign) {
  const art = artworks.get(sign.image_path);
  return art && art.license && !String(art.license_status || sign.source_provenance?.license_status || "").includes("pending") ? art : null;
}

function renderSignEntries(lang, country, webRoot, route) {
  const text = referenceCopy[lang], translations = signText[lang];
  const signs = catalogue.signs(readJson(`shared/tsr/prolix-${country.toLowerCase()}-class-catalog-v1.json`));
  const cards = signs.map((sign) => {
    const title = sign.label?.[lang] || sign.label?.en || sign.sign_code;
    const art = publicArtwork(sign);
    let image = "", credit = "";
    if (art) {
      const target = `assets/reference/${sign.image_path}`;
      mkdirSync(path.dirname(path.join(webRoot, target)), { recursive: true });
      copyFileSync(path.join(repoRoot, "shared", sign.image_path), path.join(webRoot, target));
      image = `<img src="${localHref(route, target)}" alt="${html(title)}" width="104" height="104" loading="lazy" />`;
      credit = `<details class="sign-credit"><summary>${html(text.credits)}</summary><p>${html(plain(art.artist || art.license_provenance?.artist || art.source_credit))} · ${link(art.source_page_permanent_url || art.source_page_url, art.commons_title || sign.sign_code)} · ${link(art.license_basis_url || art.license_source_url, art.license)}</p><p>${html(art.changes || text.changes)}</p></details>`;
    }
    const search = [sign.sign_code, ...Object.values(sign.label || {}), ...Object.values(sign.speech || {})].join(" ").toLowerCase();
    const phrases = catalogue.languages.map((language) => {
      const spoken = catalogue.spoken(sign, language);
      return `<dt>${{ en: "English", fr: "Français", de: "Deutsch", nl: "Nederlands" }[language]}</dt><dd lang="${spoken ? language : lang}">${html(spoken || translations.silent)}</dd>`;
    }).join("");
    return `<article class="reference-sign" data-sign-code="${html(sign.sign_code)}" data-search="${html(search)}">${image}<h2>${html(title)}</h2><p class="sign-code">${html(sign.sign_code)}</p><dl aria-label="${html(translations.spoken)}">${phrases}</dl>${credit}</article>`;
  }).join("\n");
  return `<p>${html(translations.reference)}</p>${country === "CH" ? `<p>${link("https://www.astra.admin.ch/de/signale", text.officialSigns)}</p>` : ""}<label class="reference-search-label" for="sign-search">${html(translations.search)}</label><input id="sign-search" class="reference-search" type="search" /><p class="reference-count" aria-live="polite" data-count-label="${html(text.catalogue)}">${signs.length} ${html(text.catalogue)}</p><div class="reference-signs">${cards}</div>`;
}

const value = (input, text) => input == null ? text.unspecified : String(input);
function months(input, lang, text) {
  return `${input} ${new Intl.PluralRules(lang).select(Number(input)) === "one" ? text.month_one : text.month_other}`;
}
function table(headers, rows, id) {
  return `<div class="reference-table-scroll" tabindex="0" role="region" aria-labelledby="${id}"><table><thead><tr>${headers.map((head) => `<th scope="col">${html(head)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell, index) => `<${index ? "td" : 'th scope="row"'}>${html(cell)}</${index ? "td" : "th"}>`).join("")}</tr>`).join("\n")}</tbody></table></div>`;
}

export function renderPenaltyBody(lang, rules) {
  const text = penaltyText[lang], copy = referenceCopy[lang], currency = penalty.field(rules, "currency_code");
  const contexts = penalty.categories(rules);
  const contextName = (key) => key === "motorway_130" ? `${text.motorway} · 130 km/h` : text[key] || key;
  const sections = contexts.map((context) => {
    const rows = penalty.rows(rules, context).map((row) => {
      const range = row.max == null ? `≥${row.min}` : row.min === row.max ? `+${row.min}` : `+${row.min}–${row.max}`;
      let ban = row.ban == null ? text.unspecified : `${row.condition === "first_offence_minimum_withdrawal" ? "≥" : ""}${months(row.ban, lang, text)}`;
      if (row.conditional != null) ban += ` · ${text.conditional}: ${months(row.conditional, lang, text)}`;
      if (row.condition && text[row.condition]) ban += ` · ${text[row.condition]}`;
      return [range, value(row.fine, text), value(row.points, text), ban];
    });
    const tariff = rules.speeding_tariffs;
    const intro = tariff ? `<p>${html(context === "motorway_130" ? text.motorway130 : text.threshold)}: +${context === "motorway_130" ? tariff.motorway_130_minimum_delta_kmh : tariff.minimum_delta_kmh} km/h · ${html(text.fee)}: ${tariff.administrative_fee_eur} ${html(currency)}</p>` : "";
    return `<section class="reference-table-section"><h2 id="${context}">${html(contextName(context))}</h2>${intro}${table([text.excess, `${text.fine} (${currency})`, text.points, text.ban], rows, context)}</section>`;
  }).join("\n");
  const escalation = rules.posted_limit_escalation;
  let escalationTable = "";
  if (escalation) {
    let lower = 0;
    const minimum = escalation.driving_ban_condition === "raser_standard_minimum_with_statutory_exceptions" ? "≥" : "";
    const rows = escalation.thresholds.map((row) => {
      const limit = row.max_posted_limit_kmh == null ? `>${lower}` : lower === 0 ? `≤${row.max_posted_limit_kmh}` : `${lower + 1}–${row.max_posted_limit_kmh}`;
      lower = row.max_posted_limit_kmh ?? lower;
      return [limit, `≥${row.min_delta_kmh}`, `${minimum}${months(escalation.driving_ban_months, lang, text)}`, `${text.qualifying_statutory_exception}: ${minimum}${months(escalation.conditional_driving_ban_months, lang, text)}`];
    });
    escalationTable = `<section class="reference-table-section"><h2 id="thresholds">${html(text.thresholds)}</h2>${table([text.limit, text.minimum, text.ban, text.exception], rows, "thresholds")}</section>`;
  }
  const notes = (penalty.field(rules, "bands") || []).map((band) => {
    const translated = band.localized_templates?.[lang]?.detail_template;
    const note = translated || (lang === "de" ? band.detail_vorlage : null) || band.detail_template;
    if (!note) return "";
    const resolved = note.replace(/\{(?:currency|waehrung)\}/g, currency);
    return `<li${translated || (lang === "de" && band.detail_vorlage) ? "" : ' lang="en"'}>${html(resolved)}</li>`;
  }).filter(Boolean).join("");
  const sources = [...new Set([penalty.field(rules, "source_url"), ...(rules.source_urls || [])].filter((url) => typeof url === "string" && /^https?:\/\//.test(url)))];
  return `<p class="reference-notice">${html(text.disclaimer)} ${html(text.estimates)}</p><p>${html(copy.scope)}</p><nav class="reference-contexts" aria-label="${html(text.context)}">${contexts.map((key) => link(`#${key}`, contextName(key))).join("")}</nav>${sections}${escalationTable}${notes ? `<details class="reference-conditions"><summary>${html(copy.details)}</summary><ul>${notes}</ul></details>` : ""}<div class="reference-sources"><p>${html(text.source)}: ${sources.map((url, index) => link(url, `${text.source} ${index + 1}`)).join(" · ")}</p><p>${html(copy.sourceDate)}: ${html(penalty.field(rules, "source_checked_at") || text.unspecified)}</p></div>`;
}

function renderPage({ lang, type, country, body }) {
  const copy = referenceCopy[lang], route = referenceRoute(lang, type, country), assetPrefix = rootPrefix(route);
  const title = country ? `${copy[type === "signs" ? "signTitle" : "fineTitle"]} ${countryName(lang, country)}` : copy[type];
  const description = `${title}. ${copy[type === "signs" ? "signsIntro" : "finesIntro"]}`;
  const breadcrumbs = [{ name: "YouSpeed", item: `${base}${homeRoute(lang)}` }, { name: copy[type], item: `${base}${referenceRoute(lang, type)}` }];
  if (country) breadcrumbs.push({ name: countryName(lang, country), item: `${base}${route}` });
  const schema = { "@context": "https://schema.org", "@type": "BreadcrumbList", itemListElement: breadcrumbs.map((item, index) => ({ "@type": "ListItem", position: index + 1, ...item })) };
  return `<!doctype html><html lang="${lang}"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><title>${html(title)} | YouSpeed</title><meta name="description" content="${html(description)}" /><meta name="robots" content="index,follow,max-image-preview:large" /><link rel="canonical" href="${base}${route}" />${languages.map((other) => `<link rel="alternate" hreflang="${other}" href="${base}${referenceRoute(other, type, country)}" />`).join("")}<link rel="alternate" hreflang="x-default" href="${base}${referenceRoute("de", type, country)}" /><meta property="og:title" content="${html(title)} | YouSpeed" /><meta property="og:description" content="${html(description)}" /><meta property="og:type" content="website" /><meta property="og:url" content="${base}${route}" /><meta property="og:image" content="${base}assets/social/youspeed-og-${lang}.png" /><link rel="icon" href="${assetPrefix}assets/icons/favicon.svg" /><link rel="stylesheet" href="${assetPrefix}styles.css" /><script type="application/ld+json">${JSON.stringify(schema).replace(/</g, "\\u003c")}</script></head><body><nav class="nav support-nav" aria-label="YouSpeed"><a class="nav-brand" href="${localHref(route, homeRoute(lang))}"><img class="brand-icon" src="${assetPrefix}assets/icons/app-icon-mark-192.png" alt="" width="36" height="36" /><span>YouSpeed</span></a><a class="support-home-link" href="${localHref(route, homeRoute(lang))}">${html(copy.home)}</a></nav><main class="reference-page">${storeBanner(lang, route)}<div class="container reference-content"><nav class="reference-breadcrumbs" aria-label="Breadcrumb">${breadcrumbs.map((item) => link(localHref(route, item.item.slice(base.length)), item.name)).join(" / ")}</nav><div class="reference-languages" aria-label="Language">${languages.map((other) => `<a href="${localHref(route, referenceRoute(other, type, country))}"${lang === other ? ' aria-current="page"' : ""}>${other.toUpperCase()}</a>`).join("")}</div><header class="reference-heading"><p class="eyebrow">YouSpeed · ${html(copy[type])}</p><h1>${html(title)}</h1><p>${html(copy[type === "signs" ? "signsIntro" : "finesIntro"])}</p></header>${body}<nav class="reference-related">${link(localHref(route, referenceRoute(lang, "signs")), copy.signs)}${link(localHref(route, referenceRoute(lang, "fines")), copy.fines)}</nav></div></main><footer class="site-footer"><div class="container">${link(localHref(route, "datenschutz.html"), "Privacy / Datenschutz")} · ${link(localHref(route, "support/"), "Support")} · ${link("https://github.com/volzinnovation/youspeed.de", "GitHub")}</div></footer>${type === "signs" && country ? `<script src="${assetPrefix}reference.js" defer></script>` : ""}</body></html>\n`;
}

export function addStoreBanners(root) {
  function walk(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const file = path.join(directory, entry.name);
      if (entry.isDirectory()) walk(file);
      else if (entry.name.endsWith(".html")) {
        const route = path.relative(root, file).split(path.sep).join("/");
        const source = readFileSync(file, "utf8");
        const lang = source.match(/<html\b[^>]*lang="([^"]+)"/)?.[1]?.split("-")[0] || "de";
        const banner = storeBanner(lang, route);
        const result = source.includes("<!-- app-store-banner:start -->") ? source.replace(/<!-- app-store-banner:start -->[\s\S]*?<!-- app-store-banner:end -->/, () => banner) : source.replace(/<main\b[^>]*>/, (tag) => `${tag}\n${banner}`);
        if (result !== source) writeFileSync(file, result);
      }
    }
  }
  walk(root);
}

export function buildReferencePages(webRoot) {
  const rules = readdirSync(path.join(repoRoot, "shared/Rules")).filter((file) => file.endsWith("-rules.json")).map((file) => readJson(`shared/Rules/${file}`));
  const pages = [];
  for (const lang of languages) {
    for (const type of ["signs", "fines"]) {
      const countries = (type === "signs" ? signCountries : rules.map((rule) => countryCodes[penalty.field(rule, "country_code")])).slice().sort((a, b) => countryName(lang, a).localeCompare(countryName(lang, b), lang));
      for (const country of [undefined, ...countries]) {
        const route = referenceRoute(lang, type, country);
        const body = country ? type === "signs" ? renderSignEntries(lang, country, webRoot, route) : renderPenaltyBody(lang, rules.find((rule) => countryCodes[penalty.field(rule, "country_code")] === country)) : `<h2>${html(referenceCopy[lang].countries)}</h2><ul class="reference-country-list">${countries.map((code) => `<li>${link(localHref(route, referenceRoute(lang, type, code)), countryName(lang, code))}</li>`).join("")}</ul>`;
        mkdirSync(path.dirname(path.join(webRoot, route)), { recursive: true });
        writeFileSync(path.join(webRoot, route), renderPage({ lang, type, country, body }));
        pages.push({ lang, type, country, route });
      }
    }
  }
  addStoreBanners(webRoot);
  return pages;
}
