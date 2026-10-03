// Deterministic marketing composition: immutable native UI + genuine recording.
// Only blank preview pixels change. Border, captions and controls remain native.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function inRoundedRect(x, y, [left, top, width, height], radius) {
  if (x < left || y < top || x >= left + width || y >= top + height) return false;
  const cx = Math.max(left + radius, Math.min(x + 0.5, left + width - radius));
  const cy = Math.max(top + radius, Math.min(y + 0.5, top + height - radius));
  return (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= radius ** 2;
}

export async function compositeDashcamPreview({ sharp, root, target, locale, name, raw }) {
  const config = JSON.parse(fs.readFileSync(path.join(root, 'store/artwork/dashcam-preview.json'), 'utf8'));
  const geometry = config.platforms[target];
  if (name !== geometry.filename) return null;
  const frame = fs.readFileSync(path.join(root, config.frame.path));
  if (hash(frame) !== config.frame.sha256) throw new Error('Genuine Dashcam frame hash mismatch');
  const { data: native, info } = await sharp(raw).removeAlpha().raw().toBuffer({ resolveWithObject: true });
  const [nativeWidth, nativeHeight] = geometry.native_size;
  if (info.width !== nativeWidth || info.height !== nativeHeight || info.channels !== 3) {
    throw new Error(`Unexpected native Dashcam dimensions/channels: ${target} ${locale}`);
  }
  const [left, top, width, height] = geometry.viewport;
  const mask = new Uint8Array(width * height);
  const black = (x, y) => {
    const offset = ((top + y) * nativeWidth + left + x) * 3;
    return native[offset] === 0 && native[offset + 1] === 0 && native[offset + 2] === 0;
  };
  if (geometry.mask === 'enclosed-black-component') {
    // The native continuous rounded stroke forms an exact boundary. A flood
    // fill keeps its antialiasing and avoids approximating SwiftUI's corners.
    const queue = new Uint32Array(width * height);
    let read = 0, write = 0;
    const seed = Math.floor(height / 2) * width + Math.floor(width / 2);
    if (!black(seed % width, Math.floor(seed / width))) throw new Error('Preview seed is not black');
    queue[write++] = seed;
    mask[seed] = 1;
    const visit = index => {
      if (!mask[index] && black(index % width, Math.floor(index / width))) {
        mask[index] = 1;
        queue[write++] = index;
      }
    };
    while (read < write) {
      const index = queue[read++], x = index % width, y = Math.floor(index / width);
      if (x > 0) visit(index - 1);
      if (x + 1 < width) visit(index + 1);
      if (y > 0) visit(index - width);
      if (y + 1 < height) visit(index + width);
    }
    for (let x = 0; x < width; x++) if (mask[x] || mask[(height - 1) * width + x]) throw new Error('Preview border is not closed');
    for (let y = 0; y < height; y++) if (mask[y * width] || mask[y * width + width - 1]) throw new Error('Preview border is not closed');
  } else if (geometry.mask === 'rounded-black-pixels') {
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      if (black(x, y) && inRoundedRect(left + x, top + y, geometry.viewport, geometry.corner_radius)) mask[y * width + x] = 1;
    }
  } else throw new Error(`Unsupported preview mask: ${geometry.mask}`);
  const capsules = geometry.protected_capsules?.[locale] || [];
  if (geometry.protected_capsules && !capsules.length) throw new Error(`Missing native caption protection: ${locale}`);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    if (capsules.some(rect => inRoundedRect(left + x, top + y, rect, rect[3] / 2))) mask[y * width + x] = 0;
  }
  // Both apps use a centered aspect-fill camera preview. The historical frame
  // is already upright; resize/crop it without inventing or repainting pixels.
  const [cropLeft, cropTop, cropWidth, cropHeight] = config.frame.source_crop;
  const fitted = await sharp(frame)
    .extract({ left: cropLeft, top: cropTop, width: cropWidth, height: cropHeight })
    .resize(width, height, { fit: 'cover', position: 'centre' }).removeAlpha().raw().toBuffer();
  const composed = Buffer.from(native);
  let changedPixels = 0, replacedPixels = 0;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const index = y * width + x;
    if (!mask[index]) continue;
    const destination = ((top + y) * nativeWidth + left + x) * 3, source = index * 3;
    if (native[destination] !== fitted[source] || native[destination + 1] !== fitted[source + 1]
        || native[destination + 2] !== fitted[source + 2]) changedPixels++;
    composed[destination] = fitted[source];
    composed[destination + 1] = fitted[source + 1];
    composed[destination + 2] = fitted[source + 2];
    replacedPixels++;
  }
  const png = await sharp(composed, { raw: { width: nativeWidth, height: nativeHeight, channels: 3 } }).png().toBuffer();
  return {
    png,
    provenance: {
      format: config.format,
      authoring: config.authoring,
      frame: config.frame,
      native_viewport: geometry.viewport,
      fit: 'centered aspect-fill',
      mask: geometry.mask,
      protected_capsules: capsules,
      preserved: 'All native pixels outside the camera pane, its border, caption capsules and non-black UI pixels (including Done). Raw source capture remains unchanged.',
      changed_native_pixels: changedPixels,
      replaced_native_pixels: replacedPixels,
      composed_native_sha256: hash(png),
    },
  };
}
