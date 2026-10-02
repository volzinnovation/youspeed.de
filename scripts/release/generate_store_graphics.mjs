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
// Equal spacing around a circle, clockwise from the speed limit at the top.
const signs = ['de-274-50', 'de-206', 'de-283', 'de-301', 'de-205'].map(id => embed(`shared/tsr/sign-pictograms/png/${id}.png`));
const signImages = signs.map((image, index) => {
  const angle = (-90 + index * 72) * Math.PI / 180;
  const x = (840 + 126 * Math.cos(angle) - 54).toFixed(2);
  const y = (250 + 126 * Math.sin(angle) - 54).toFixed(2);
  return `<image href="${image}" x="${x}" y="${y}" width="108" height="108" preserveAspectRatio="xMidYMid meet"/>`;
}).join('\n');
const locales = JSON.parse(fs.readFileSync(path.join(root, 'store/artwork/marketing-copy.json'), 'utf8'));

for (const [locale, copy] of Object.entries(locales)) {
  const [line1, line2] = copy.hero;
  const features = copy.feature_line;
  const headlineSize = Math.min(66, Math.floor(660 / (Math.max(line1.length, line2.length) * 0.55)));
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
  <text x="48" y="190" font-size="${headlineSize}" font-weight="700" letter-spacing="-2">${escape(line1)}</text>
  <text x="48" y="266" font-size="${headlineSize}" font-weight="700" letter-spacing="-2" fill="#fae14f">${escape(line2)}</text>
  <text x="48" y="323" font-size="21">${escape(features)}</text>
  <text x="48" y="410" font-size="20" fill="#eef0f2">${escape(copy.tagline)}</text>
</g>
<g filter="url(#shadow)">
  ${signImages}
</g>
</svg>`;
  const svgPath = path.join(source, `feature-graphic-${locale}.svg`);
  fs.writeFileSync(svgPath, svg);
  const output = path.join(root, `store/android/listing/${locale}/feature-graphic-1024x500.png`);
  await sharp(Buffer.from(svg)).flatten({ background: '#090d12' }).png().toFile(output);
  fs.copyFileSync(output, path.join(root, `fastlane/metadata/android/${locale}/images/featureGraphic.png`));
  console.log(`${locale}: 1024 × 500, opaque PNG, mirrored to Fastlane`);
}
