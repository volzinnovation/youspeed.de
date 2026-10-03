#!/usr/bin/env node
// Author store compositions around complete, retained native captures.
// Blank Dashcam panes use an explicitly requested genuine-footage composition.
// Re-render from retained captures, never from the already composed output.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { compositeDashcamPreview } from './composite_dashcam_preview.mjs';

const require = createRequire(import.meta.url);
const sharp = require(process.env.YOUSPEED_SHARP_MODULE || 'sharp');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const copy = JSON.parse(fs.readFileSync(path.join(root, 'store/artwork/marketing-copy.json'), 'utf8'));
const options = process.argv.slice(2);
const platform = options.find(value => ['apple', 'android'].includes(value));
const refresh = options.includes('--capture-source');
const onlyDashcam = options.includes('--only-dashcam');
const nativeCompositeDirectory = options.find(value => value.startsWith('--native-composites='))?.slice('--native-composites='.length);
const signTexts = JSON.parse(fs.readFileSync(path.join(root, 'shared/traffic-sign-documentation/translations.json'), 'utf8'));
const fineTexts = JSON.parse(fs.readFileSync(path.join(root, 'shared/penalty-documentation/translations.json'), 'utf8'));
const selectedLocales = options.find(value => value.startsWith('--locales='))?.slice(10).split(',');
const esc = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const imageURI = raw => `data:image/png;base64,${raw.toString('base64')}`;
const hash = raw => crypto.createHash('sha256').update(raw).digest('hex');
const provenancePath = path.join(root, 'store/artwork/screenshot-layouts.json');
const provenance = fs.existsSync(provenancePath) ? JSON.parse(fs.readFileSync(provenancePath, 'utf8')) : { format: 'youspeed.marketing-screenshots.v1', images: {} };

async function fitted(text, width, size, bold = false) {
  const { width: measured } = await sharp({ text: { text: esc(text), font: `Arial ${bold ? 'Bold ' : ''}${size}`, rgba: true } }).metadata();
  return Math.min(size, Math.floor(size * width / measured));
}

for (const target of platform ? [platform] : ['apple', 'android']) {
  for (const locale of Object.keys(copy)) {
    if (selectedLocales && !selectedLocales.includes(locale)) continue;
    const relative = target === 'apple' ? `store/apple/screenshots/${locale}/iphone-6.9` : `store/android/listing/${locale}/phone-screenshots`;
    const directory = path.join(root, relative);
    if (!fs.existsSync(directory)) continue;
    for (const name of fs.readdirSync(directory).filter(name => name.endsWith('.png')).sort()) {
      if (onlyDashcam && name !== (target === 'apple' ? '04-dashcam.png' : '02-dashcam.png')) continue;
      const output = path.join(directory, name);
      const signCountry = name.match(/reference-signs-(\w+)\.png$/)?.[1];
      const fineCountry = name.match(/reference-penalties-(\w+)\.png$/)?.[1];
      const referenceCountry = signCountry || fineCountry;
      const capture = referenceCountry
        ? path.join(root, `store/reference-screenshots/${target}/${locale}/${signCountry ? 'signs' : 'penalties'}/${referenceCountry}.png`)
        : path.join(root, `store/artwork/raw-screenshots/${target}/${locale}/${name}`);
      fs.mkdirSync(path.dirname(capture), { recursive: true });
      const key = `${relative}/${name}`;
      const alreadyComposed = provenance.images[key]?.output_sha256 === hash(fs.readFileSync(output));
      if (referenceCountry && !fs.existsSync(capture)) throw new Error(`Native reference capture missing: ${capture}`);
      if (!fs.existsSync(capture) && alreadyComposed) throw new Error(`Retained native source missing: ${capture}`);
      if (!referenceCountry && (!fs.existsSync(capture) || (refresh && !alreadyComposed))) fs.copyFileSync(output, capture);
      const raw = fs.readFileSync(capture);
      const meta = await sharp(raw).metadata();
      const composite = await compositeDashcamPreview({ sharp, root, target, locale, name, raw });
      const displayedCapture = composite?.png || raw;
      if (composite && nativeCompositeDirectory) {
        const previewOutput = path.join(nativeCompositeDirectory, target, `${locale}.png`);
        fs.mkdirSync(path.dirname(previewOutput), { recursive: true });
        fs.writeFileSync(previewOutput, composite.png);
      }
      const landscape = target === 'android' && meta.width > meta.height;
      const width = target === 'apple' ? 1320 : landscape ? 1920 : 1080;
      const height = target === 'apple' ? 2868 : landscape ? 1080 : 1920;
      const scale = width / 1320;
      const pad = 85 * scale;
      const index = Number(name.slice(0, 2)) - 1;
      // Android places dashcam second; the other benefit captions follow native order.
      const story = target === 'android' ? [0, 3, 1, 2, 4, 5, 6, 7][index] : index;
      const language = locale.split('-')[0];
      const referenceText = signCountry ? signTexts[language] : fineTexts[language];
      const countryAlpha2 = { NLD: 'NL' }[referenceCountry] || referenceCountry;
      const countryName = referenceCountry ? new Intl.DisplayNames([locale], { type: 'region' }).of(countryAlpha2) : '';
      const [line1, line2, detail] = referenceCountry
        ? [referenceText.title, countryName, signCountry ? 'English · Français · Deutsch · Nederlands' : referenceText.disclaimer]
        : copy[locale].gallery[name === '01-camera-recognition.png' ? 1 : story];
      const headlineBase = landscape ? 66 : 110 * scale;
      const font = Math.min(await fitted(line1, width - 2 * pad, headlineBase, true), await fitted(line2, width - 2 * pad, headlineBase, true));
      const brandY = landscape ? 72 : 140 * scale;
      const titleY = landscape ? 166 : 325 * scale;
      const lineGap = landscape ? 80 : 138 * scale;
      const detailY = landscape ? 350 : 573 * scale;
      const detailSize = await fitted(detail, width - 2 * pad, landscape ? 35 : 44 * scale);
      const areaTop = landscape ? 410 : 690 * scale;
      const areaHeight = height - areaTop - (landscape ? 65 : 145 * scale);
      const areaWidth = width - 2 * pad;
      const factor = Math.min(areaWidth / meta.width, areaHeight / meta.height);
      const screenWidth = Math.round(meta.width * factor);
      const screenHeight = Math.round(meta.height * factor);
      const x = Math.round((width - screenWidth) / 2);
      const y = Math.round(areaTop + (areaHeight - screenHeight) / 2);
      if (composite) {
        const [left, top, paneWidth, paneHeight] = composite.provenance.native_viewport;
        composite.provenance.native_placement = { x, y, width: screenWidth, height: screenHeight };
        composite.provenance.rendered_viewport_bounds = [
          Math.floor(x + left * screenWidth / meta.width), Math.floor(y + top * screenHeight / meta.height),
          Math.ceil(x + (left + paneWidth) * screenWidth / meta.width), Math.ceil(y + (top + paneHeight) * screenHeight / meta.height),
        ];
      }
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
<rect width="100%" height="100%" fill="#082d37"/>
<rect x="${pad}" y="${brandY - 34 * scale}" width="${5 * scale}" height="${40 * scale}" fill="#fae14f"/>
<g font-family="Arial, sans-serif">
<text x="${pad + 22 * scale}" y="${brandY}" fill="#ffffff" font-size="${42 * scale}" font-weight="700">YouSpeed</text>
<text x="${width - pad}" y="${brandY}" text-anchor="end" fill="#9bb6bc" font-size="${28 * scale}">${String(index + 1).padStart(2, '0')}</text>
<text x="${pad}" y="${titleY}" fill="#ffffff" font-size="${font}" font-weight="700" letter-spacing="-2">${esc(line1)}</text>
<text x="${pad}" y="${titleY + lineGap}" fill="#fae14f" font-size="${font}" font-weight="700" letter-spacing="-2">${esc(line2)}</text>
<text x="${pad}" y="${detailY}" fill="#d9e7e9" font-size="${detailSize}">${esc(detail)}</text>
</g>
<rect x="${x - 6}" y="${y - 6}" width="${screenWidth + 12}" height="${screenHeight + 12}" rx="${22 * scale}" fill="#56767d"/>
<image href="${imageURI(displayedCapture)}" x="${x}" y="${y}" width="${screenWidth}" height="${screenHeight}"/>
</svg>`;
      await sharp(Buffer.from(svg)).flatten({ background: '#082d37' }).png().toFile(output);
      if (target === 'android') fs.copyFileSync(output, path.join(root, `fastlane/metadata/android/${locale}/images/phoneScreenshots/${name}`));
      provenance.images[key] = { source: path.relative(root, capture), source_sha256: hash(raw), output_sha256: hash(fs.readFileSync(output)), width, height,
        content: composite ? 'User-requested marketing composition: complete native demonstration UI with a genuine recorded Dashcam frame placed in its empty camera viewport. Not a live capture of the depicted session. No synthetic road imagery or recognition result.' : 'Complete native demonstration capture, proportionally scaled. No synthetic road preview or recognition result.',
        ...(composite ? { composite: composite.provenance } : {}),
      };
    }
    console.log(`${target} ${locale}: composed gallery from retained native captures`);
  }
}
fs.writeFileSync(provenancePath, JSON.stringify(provenance, null, 2) + '\n');
