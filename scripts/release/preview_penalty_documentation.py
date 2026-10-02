#!/usr/bin/env python3
"""Preview the shared offline lookup using the real rule JSON; no copied tariff data."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--locale', default='en')
    parser.add_argument('--country', default='NLD')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    directory = ROOT / 'shared/penalty-documentation'
    payload = {'locale': args.locale, 'activeCountry': args.country,
               'documents': [json.loads(p.read_text()) for p in sorted((ROOT / 'shared/Rules').glob('*-rules.json'))],
               'translations': json.loads((directory / 'translations.json').read_text())}
    encoded = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c')
    html = (directory / 'index.html').read_text().replace('__YOUSPEED_RENDERER__', (directory / 'renderer.js').read_text())
    html = html.replace('__YOUSPEED_INPUT__', encoded)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html)
    print(args.output.resolve())

if __name__ == '__main__':
    main()
