#!/usr/bin/env python3
"""Review index for yellow objects in the pinned OLD corpus; no model inference."""
from pathlib import Path
import collections
import csv
import hashlib
import io
import json
import re
import zipfile
from PIL import Image, ImageDraw, ImageOps


ROOT = Path('/home/raphael/youspeed-training-20261020/tsr')
OUT = ROOT / 'old-corpus-audit'
ARCHIVES = [('train.zip', '0a7cc5895afd76a4dc98e70efc9421ae82a6f580e6d60da3904911155e424853'),
            ('val.zip', '13ca882129a4e024fc865fc4a3187514a4554f8e323f612e338144fd1ff189ea')]


def main():
    OUT.mkdir(exist_ok=False)
    seen = set()
    pixels = collections.defaultdict(list)
    candidates = []
    rows = []
    for archive, expected in ARCHIVES:
        path = ROOT / 'sources' / archive
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
        with zipfile.ZipFile(path) as z:
            for item in z.infolist():
                if item.is_dir():
                    continue
                raw = z.read(item)
                sha = hashlib.sha256(raw).hexdigest()
                if sha in seen:
                    continue
                seen.add(sha)
                label = item.filename.split('/')[1]
                with Image.open(io.BytesIO(raw)) as original:
                    image = ImageOps.exif_transpose(original).convert('RGB')
                    pixel_sha = hashlib.sha256(str(image.size).encode() + b'\0' + image.tobytes()).hexdigest()
                    pixels[pixel_sha].append(sha)
                    thumb = image.copy()
                    thumb.thumbnail((64, 64))
                    yellow = sum(r > 140 and g > 120 and b < 140 and r > 1.4*b and
                                 g > 1.25*b and abs(r-g) < 100 for r, g, b in thumb.getdata())
                    ratio = yellow / (thumb.width * thumb.height)
                    row = {'archive': archive, 'member': item.filename, 'label': label,
                           'sha256': sha, 'rgb_sha256': pixel_sha, 'width': image.width,
                           'height': image.height, 'yellow_fraction': round(ratio, 5)}
                    rows.append(row)
                    # Deliberately broad review proposals, never automatic relabeling.
                    if ratio >= 0.12:
                        candidates.append((row, image.copy()))
    candidates.sort(key=lambda x: (-x[0]['yellow_fraction'], x[0]['sha256']))
    sheets = []
    crop_dir = OUT / 'yellow-crops'
    crop_dir.mkdir()
    for page, start in enumerate(range(0, len(candidates), 80), 1):
        sheet = Image.new('RGB', (1400, 1040), 'white')
        draw = ImageDraw.Draw(sheet)
        for offset, (row, image) in enumerate(candidates[start:start+80]):
            index = start + offset + 1
            row['review_index'] = index
            row['review_crop_path'] = f'yellow-crops/{index:04d}.png'
            image.save(OUT / row['review_crop_path'])
            image.thumbnail((130, 93))
            x, y = (offset % 10)*140, (offset // 10)*130
            sheet.paste(image, (x+(140-image.width)//2, y))
            draw.text((x+3, y+95), f'{index:04d} {row["label"][:20]}', fill='black')
            draw.text((x+3, y+111), f'{row["width"]}x{row["height"]} y={row["yellow_fraction"]:.2f}', fill='black')
        path = OUT / f'yellow-contact-{page:02d}.jpg'
        sheet.save(path, quality=90)
        sheets.append(str(path))
    (OUT / 'inventory.json').write_text(json.dumps(rows, indent=2)+'\n')
    (OUT / 'yellow-review.json').write_text(json.dumps([r for r, _ in candidates], indent=2)+'\n')
    summary = {'unique_byte_images': len(rows), 'unique_rgb_images': len(pixels),
               'decoded_duplicate_groups': sum(len(v)>1 for v in pixels.values()),
               'class_counts': dict(collections.Counter(r['label'] for r in rows)),
               'yellow_proposals': len(candidates), 'threshold': 0.12,
               'sheets': sheets, 'model_inference': False,
               'labels_changed': False, 'assistant_review_required': True}
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
