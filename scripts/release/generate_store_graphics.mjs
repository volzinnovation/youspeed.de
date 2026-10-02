#!/usr/bin/env node
// Render editable SVG marketing artwork. Original screenshots/sign bytes are
// never painted over or replaced with generated sign artwork.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const sharp = require(process.env.YOUSPEED_SHARP_MODULE || 'sharp');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const source = path.join(root, 'store/artwork/source');
const embed = relative => `data:image/png;base64,${fs.readFileSync(path.join(root, relative)).toString('base64')}`;
const escape = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const backdrop = embed('store/artwork/source/european-road-backdrop.png');
const appIcon = embed('store/android/listing/en-US/icon-512.png');
const signs = ['de-205', 'de-206', 'de-301'].map(id => embed(`shared/tsr/sign-pictograms/png/${id}.png`));
const locales = {
  'de-DE': ['Deine Fahrt.', 'Aufgenommen.', 'Dashcam · Offline-Karten · Schilderkennung', 'Karten & Hinweise: DE · FR · CH · BE · NL', 'Videos lokal speichern. Bewusst teilen.'],
  'en-US': ['Your drive.', 'Recorded.', 'Dashcam · Offline maps · Sign recognition', 'Maps & advisories: DE · FR · CH · BE · NL', 'Record locally. Share when you choose.'],
  'fr-FR': ['Vos trajets.', 'Enregistrés.', 'Dashcam · Cartes hors ligne · Reconnaissance', 'Cartes et alertes : DE · FR · CH · BE · NL', 'Vidéos locales. Partage à votre choix.'],
  'nl-NL': ['Je rit.', 'Vastgelegd.', 'Dashcam · Offline kaarten · Bordherkenning', 'Kaarten en advies: DE · FR · CH · BE · NL', 'Lokaal opnemen. Delen wanneer jij kiest.'],
  'es-ES': ['Tu viaje.', 'Grabado.', 'Dashcam · Mapas sin conexión · Señales', 'Mapas y avisos: DE · FR · CH · BE · NL', 'Graba localmente. Comparte cuando quieras.'],
  'it-IT': ['Il tuo viaggio.', 'Registrato.', 'Dashcam · Mappe offline · Riconoscimento', 'Mappe e avvisi: DE · FR · CH · BE · NL', 'Video locali. Condividi quando vuoi.'],
  'pl-PL': ['Twoja podróż.', 'Nagrana.', 'Kamera samochodowa · Mapy offline · Znaki', 'Mapy i ostrzeżenia: DE · FR · CH · BE · NL', 'Nagrywaj lokalnie. Udostępniaj, gdy zechcesz.'],
  'pt-BR': ['Sua viagem.', 'Gravada.', 'Dashcam · Mapas offline · Placas', 'Mapas e avisos: DE · FR · CH · BE · NL', 'Grave localmente. Compartilhe quando quiser.'],
  'sv-SE': ['Din resa.', 'Inspelad.', 'Dashcam · Offlinekartor · Vägmärken', 'Kartor och information: DE · FR · CH · BE · NL', 'Spela in lokalt. Dela när du vill.'],
};

for (const [locale, [line1, line2, features, countries, qualifier]] of Object.entries(locales)) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="500" viewBox="0 0 1024 500">
<defs>
  <linearGradient id="shade"><stop stop-color="#090d12" stop-opacity="0.98"/><stop offset="0.57" stop-color="#090d12" stop-opacity="0.76"/><stop offset="1" stop-color="#090d12" stop-opacity="0.08"/></linearGradient>
  <filter id="shadow" x="-50%" y="-50%" width="200%" height="200%"><feDropShadow dx="0" dy="5" stdDeviation="8" flood-opacity="0.35"/></filter>
</defs>
<image href="${backdrop}" x="0" y="0" width="1024" height="500" preserveAspectRatio="xMidYMid slice"/>
<rect width="1024" height="500" fill="url(#shade)"/>
<image href="${appIcon}" x="48" y="35" width="55" height="55"/>
<g font-family="Arial, sans-serif" fill="#ffffff">
  <text x="121" y="75" font-size="39" font-weight="700">YouSpeed</text>
  <text x="48" y="190" font-size="66" font-weight="700" letter-spacing="-2">${escape(line1)}</text>
  <text x="48" y="266" font-size="66" font-weight="700" letter-spacing="-2" fill="#fae14f">${escape(line2)}</text>
  <text x="48" y="323" font-size="21">${escape(features)}</text>
  <text x="48" y="410" font-size="18" fill="#eef0f2">${escape(countries)}</text>
  <text x="48" y="456" font-size="14" fill="#d2d7dc">${escape(qualifier)}</text>
</g>
<g filter="url(#shadow)">
  <image href="${signs[0]}" x="725" y="72" width="143" height="143" preserveAspectRatio="xMidYMid meet"/>
  <image href="${signs[1]}" x="858" y="211" width="115" height="115" preserveAspectRatio="xMidYMid meet"/>
  <image href="${signs[2]}" x="721" y="324" width="111" height="111" preserveAspectRatio="xMidYMid meet"/>
</g>
</svg>`;
  const svgPath = path.join(source, `feature-graphic-${locale}.svg`);
  fs.writeFileSync(svgPath, svg);
  const output = path.join(root, `store/android/listing/${locale}/feature-graphic-1024x500.png`);
  await sharp(Buffer.from(svg)).flatten({ background: '#090d12' }).png().toFile(output);
  fs.copyFileSync(output, path.join(root, `fastlane/metadata/android/${locale}/images/featureGraphic.png`));
  console.log(`${locale}: 1024 × 500, opaque PNG, mirrored to Fastlane`);
}
