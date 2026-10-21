#!/usr/bin/env node
/** Load portable lane ZIPs or extracted datasets; emit reviewed, pixel-coordinate labels. */
import {readFile, stat, realpath, writeFile, mkdir} from 'node:fs/promises';
import {resolve, join, dirname, relative, isAbsolute} from 'node:path';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require = createRequire(import.meta.url);
const core = require('../../inspector/lane-annotations-core.js');
const zip = require('../../inspector/lane-dataset-zip.js');

export async function loadDataset(input, {split = 'train', points = 65, includeDrafts = false} = {}) {
  if (!core.SPLITS.includes(split)) throw new Error('Split must be train, validation or test.');
  if (!Number.isInteger(points) || points < 2 || points > 10001) throw new Error('points must be 2–10001.');
  const root = await realpath(input), isDirectory = (await stat(root)).isDirectory();
  const archive = isDirectory ? null : await zip.unpack(new Blob([await readFile(root)]));
  async function read(name) {
    if (archive) {
      const blob = archive.get(name); if (!blob) throw new Error(`Missing ${name}`);
      return Buffer.from(await blob.arrayBuffer());
    }
    const path = await realpath(join(root, name)), rel = relative(root, path);
    if (rel.startsWith('..') || isAbsolute(rel)) throw new Error('Dataset asset escapes its directory.');
    return readFile(path);
  }
  const manifest = core.validate(JSON.parse(await read('manifest.json')));
  const expected = core.splitManifests(manifest);
  for (const name of core.SPLITS) {
    const ids = JSON.parse(await read(`splits/${name}.json`));
    if (JSON.stringify(ids) !== JSON.stringify(expected[name])) throw new Error(`Inconsistent ${name} split manifest.`);
  }
  const output = [];
  for (const sample of [...manifest.samples].sort((a,b) => a.sourceId.localeCompare(b.sourceId) || a.frameIndex-b.frameIndex)) {
    const source = manifest.sources.find(s => s.id === sample.sourceId);
    if (source.split !== split || (sample.status !== 'reviewed' && !includeDrafts)) continue;
    const imageBytes = await read(sample.image.path);
    if (imageBytes.length !== sample.image.byteLength || createHash('sha256').update(imageBytes).digest('hex') !== sample.image.sha256 ||
        imageBytes.length < 24 || !imageBytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])) ||
        imageBytes.readUInt32BE(16) !== sample.width || imageBytes.readUInt32BE(20) !== sample.height) throw new Error(`Invalid frame image: ${sample.id}`);
    output.push({sampleId: sample.id, sourceId: source.id, groupId: source.groupId, sequenceId: sample.sequenceId,
      frameIndex: sample.frameIndex, pts: sample.pts, timeBase: source.timeBase, timeSeconds: sample.timeSeconds,
      image: sample.image.path, imageBytes, width: sample.width, height: sample.height, status: sample.status,
      curves: sample.curves.map(curve => ({annotationId: curve.id, trackId: curve.trackId, marking: curve.marking,
        classId: curve.marking === 'solid' ? 0 : 1, points: core.polyline(curve, sample.width, sample.height, points)}))});
  }
  return output;
}

async function main(argv) {
  const input = argv.shift();
  if (!input || argv.includes('--help')) throw new Error('Usage: node scripts/inspector/lane_dataset_loader.mjs DATASET.zip|DIRECTORY [--split train|validation|test] [--points 65] [--include-drafts] [--output DIRECTORY]');
  const options = {}, outputArg = {path: null};
  while (argv.length) {
    const flag = argv.shift();
    if (flag === '--include-drafts') options.includeDrafts = true;
    else if (flag === '--split' && argv.length) options.split = argv.shift();
    else if (flag === '--points' && argv.length) options.points = Number(argv.shift());
    else if (flag === '--output' && argv.length) outputArg.path = resolve(argv.shift());
    else throw new Error(`Unknown or incomplete option: ${flag}`);
  }
  const records = await loadDataset(input, options);
  if (outputArg.path) {
    if (outputArg.path === resolve(input)) throw new Error('Output must differ from input.');
    await mkdir(join(outputArg.path, 'images'), {recursive: true});
    for (const record of records) await writeFile(join(outputArg.path, record.image), record.imageBytes);
  }
  const labels = records.map(({imageBytes, ...label}) => JSON.stringify(label)).join('\n') + (records.length ? '\n' : '');
  if (outputArg.path) await writeFile(join(outputArg.path, 'labels.jsonl'), labels);
  else process.stdout.write(labels);
}
if (import.meta.url === pathToFileURL(process.argv[1] || '').href) main(process.argv.slice(2)).catch(error => { console.error(error.message); process.exitCode = 1; });
