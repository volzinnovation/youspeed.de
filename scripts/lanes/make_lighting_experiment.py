#!/usr/bin/env python3
"""Create offline-only native source snapshots for frozen lighting ablations.

Does not modify app code. Run with replay_recorded_pipeline.py --source-dir.
A = measured border qualification, B = bilateral local variance normalization.
Original bright evidence is unchanged before suppression. Extra candidates can
still alter suppression/association, which is deliberately measured by replay.
"""
import argparse
import hashlib
import json
from pathlib import Path
from replay_recorded_pipeline import SOURCES, ROOT


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Production source changed: expected exactly one patch anchor {old!r}")
    return text.replace(old, new)


def generate(source, output, mode, input_kind):
    output.mkdir(parents=True, exist_ok=False)
    texts = {name: (source/name).read_text() for name in SOURCES}
    hashes = {name: hashlib.sha256((source/name).read_bytes()).hexdigest() for name in SOURCES}
    if input_kind == 'raw':
        session = texts['RoadPathSession.swift']
        anchors = [
            'RoadBoundaryPreprocessor.topHat5(grayscale: frame.grayscale, width: frame.width, height: frame.height,\n            shouldContinue: { elapsedMs() < 50 })',
            'RoadBoundaryPreprocessor.topHat5ForDetector(grayscale: frame.grayscale, width: frame.width, height: frame.height, horizonY: visual?.horizonY,\n            shouldContinue: { elapsedMs() < 50 })',
        ]
        matching = [anchor for anchor in anchors if anchor in session]
        if len(matching) != 1:
            raise ValueError('Unknown/ambiguous production filter call; refusing the raw ablation')
        texts['RoadPathSession.swift'] = replace_once(session, matching[0], '(elapsedMs() < 50 ? frame.grayscale : nil)')
    if mode != 'baseline':
        text = texts['RoadBoundaryDetector.swift']
        text = replace_once(text, 'let row: Int\n', 'let row: Int\n        var recovered = false\n')
        text = replace_once(text, 'func detect(grayscale: [UInt8],', 'func detect(grayscale: [UInt8], originalGrayscale: [UInt8]? = nil,')
        text = replace_once(text, 'var active: [Track] = []', 'let original = originalGrayscale ?? grayscale\n        guard original.count == grayscale.count else { return empty() }\n        var active: [Track] = []')
        text = replace_once(text, 'var paints = [Bool]', 'var recovered = [Bool](repeating: false, count: width)\n        var paints = [Bool]')
        text = replace_once(text, 'paints[x] = false', 'paints[x] = false\n                recovered[x] = false')
        anchor = '            for x in margin..<(width - margin) {\n                if x % 32 == 0 && !check(32 * radii.count)'
        text = replace_once(text, anchor, '            guard check(width*3) else { return empty(true) }\n            let lightingRow = LightingRecovery.Row(original,width,y)\n'+anchor)
        text = replace_once(text, '                let edge = abs(mean(x - 3, 1) - mean(x + 3, 1))', '''                if ridge < 26 {
                    let (score,exceeded) = LightingRecovery.response(original,width,height,lightingRow,x,y,radii,check)
                    if exceeded { return empty(true) }
                    if score >= 26 { ridge = score; recovered[x] = true; LightingRecovery.count("recoveredBeforeNMS") }
                } else { LightingRecovery.count("brightBeforeNMS") }
                let edge = abs(mean(x - 3, 1) - mean(x + 3, 1))''')
        text = replace_once(text, 'cue: paints[x] ? .paint : .edge, row: row)', 'cue: paints[x] ? .paint : .edge, row: row, recovered: recovered[x])')
        text = replace_once(text, '            completed.append(contentsOf: active.filter', '''            LightingRecovery.counters["recoveredAfterRowCap", default: 0] += rowCandidates.filter { $0.recovered }.count
            completed.append(contentsOf: active.filter''')
        text = replace_once(text, '            evidence.append(RoadBoundaryEvidence', '''            LightingRecovery.counters["recoveredInEligibleTracks", default: 0] += samples.filter { $0.recovered }.count
            evidence.append(RoadBoundaryEvidence''')
        helper = Path(__file__).with_name('LightingRecovery.swift').read_text().replace('static var mode = "AB"', f'static var mode = "{mode}"')
        texts['RoadBoundaryDetector.swift'] = text+'\n'+helper
        texts['RoadPathSession.swift'] = replace_once(texts['RoadPathSession.swift'], 'detector.detect(grayscale:enhanced,width:', 'detector.detect(grayscale:enhanced,originalGrayscale:frame.grayscale,width:')
        texts['RoadPathSession.swift'] = replace_once(texts['RoadPathSession.swift'],
            'let previousPreparedScope=publishedScope',
            'LightingRecovery.counters = [:]\n        let previousPreparedScope=publishedScope')
        texts['RoadPathSession.swift'] = replace_once(texts['RoadPathSession.swift'],
            'json["lumaSamplingMs"] =',
            'json["lightingExperiment"] = LightingRecovery.counters\n        json["lumaSamplingMs"] =')
    for name, text in texts.items():
        (output/name).write_text(text)
    (output/'experiment.json').write_text(json.dumps(dict(schemaVersion=1, mode=mode, input=input_kind,
        baselineSourceHashes=hashes, generatorSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        helperSha256=hashlib.sha256(Path(__file__).with_name('LightingRecovery.swift').read_bytes()).hexdigest(),
        parameters='Frozen in LightingRecovery.swift; no tuning after label/prediction comparison',
        scope='Offline only; native deadlines and presentation unchanged'), indent=2)+'\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-dir', type=Path, default=ROOT/'iphone/SpeedConsumerApp')
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--mode', choices=['baseline','A','B','AB'], required=True)
    p.add_argument('--input-kind', choices=['raw','top-hat'], required=True)
    a=p.parse_args(); generate(a.source_dir,a.output_dir,a.mode,a.input_kind)
