#!/usr/bin/env python3
"""Offline whole-track raw-paint verification; frozen 40% consensus hypothesis.

Checks existing PAINT tracks, not just newly recovered candidates. Reuses the
previous border/contrast hypothesis without relaxing deadlines or presentation.
Sources must be the pre-optimization production snapshot to isolate accuracy.
"""
import argparse,hashlib,json,shutil
from pathlib import Path
from replay_recorded_pipeline import SOURCES
from make_lighting_experiment import replace_once

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-dir',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();a.output_dir.mkdir(parents=True,exist_ok=False)
 for name in SOURCES:shutil.copy2(a.source_dir/name,a.output_dir/name)
 p=a.output_dir/'RoadBoundaryDetector.swift';s=p.read_text()
 s=replace_once(s,'func detect(grayscale: [UInt8],','func detect(grayscale: [UInt8], originalGrayscale: [UInt8]? = nil,')
 s=replace_once(s,'        var active: [Track] = []','''        let original = originalGrayscale ?? grayscale
        guard original.count == grayscale.count else { return empty() }
        var verificationRows: [Int: LightingRecovery.Row] = [:]
        var active: [Track] = []''')
 s=replace_once(s,'            evidence.append(RoadBoundaryEvidence','''            if cue == .paint {
                LightingRecovery.count("paintTracksExamined")
                var verified = 0
                for sample in samples {
                    let x = Int((sample.point.x*Double(width-1)).rounded())
                    let y = Int((sample.point.y*Double(height-1)).rounded())
                    if verificationRows[y] == nil {
                        guard check(width*3) else { return empty(true) }
                        verificationRows[y] = LightingRecovery.Row(original,width,y)
                    }
                    let (score,exceeded) = LightingRecovery.response(original,width,height,verificationRows[y]!,x,y,radii,check)
                    if exceeded { return empty(true) }
                    if score >= 26 { verified += 1 }
                }
                LightingRecovery.counters["verifiedSupportedRows", default:0] += verified
                guard verified >= max(4,Int(ceil(Double(samples.count)*0.40))) else {
                    LightingRecovery.count("paintTracksRejected"); continue
                }
                LightingRecovery.count("paintTracksRetained")
            }
            evidence.append(RoadBoundaryEvidence''')
 helper=Path(__file__).with_name('LightingRecovery.swift').read_text();p.write_text(s+'\n'+helper)
 p=a.output_dir/'RoadPathSession.swift';s=p.read_text()
 s=replace_once(s,'detector.detect(grayscale:enhanced,width:', 'detector.detect(grayscale:enhanced,originalGrayscale:frame.grayscale,width:')
 s=replace_once(s,'let previousPreparedScope=publishedScope','LightingRecovery.counters = [:]\n        let previousPreparedScope=publishedScope')
 s=replace_once(s,'json["lumaSamplingMs"] =','json["lightingExperiment"] = LightingRecovery.counters\n        json["lumaSamplingMs"] =');p.write_text(s)
 (a.output_dir/'experiment.json').write_text(json.dumps(dict(hypothesis='Require at least 4 and 40% raw border/contrast verified support rows for every completed paint track; retain existing confidence for passing tracks; reject failing tracks before final six selection.',helperSha256=hashlib.sha256(helper.encode()).hexdigest(),generatorSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),scope='offline-only; reused labels are development data; no parameter tuning after scores'),indent=2))

if __name__=='__main__':main()
