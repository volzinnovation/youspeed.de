#!/usr/bin/env python3
"""Build a standalone ART benchmark from current and saved pre-change native sources.

No deployment occurs here. Requires Kotlin, Android SDK d8, cached serialization
jars. Benchmark runs the actual prepare pipeline; camera/model contention absent.
"""
import argparse,hashlib,json,os,shutil,subprocess
from pathlib import Path
from replay_path import classpath
ROOT=Path(__file__).resolve().parents[2]
NAMES=['LaneDetection.kt','RoadBoundaryDetector.kt','RoadPathLaneFilter.kt','RoadBoundaryTemporalTracker.kt','RoadBoundaryPresentationGate.kt','RoadBoundaryMotionHint.kt','RoadPathEvidence.kt','TrafficSignApplicability.kt','VisualRoadCalibration.kt','RoadPathSession.kt']

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--sdk',type=Path,required=True);a=p.parse_args()
 a.output.mkdir(parents=True,exist_ok=False);sources=a.output/'sources';sources.mkdir()
 current=ROOT/'android/app/src/main/java/de/youspeed/android/alpha'
 for name in NAMES:shutil.copy2(current/name,sources/name)
 def snippet(path,start,end):
  s=path.read_text();return s[s.index(start):s.index(end,s.index(start))]
 runtime=current/'LaneDetectionRuntime.kt';old=a.baseline/'LaneDetectionRuntime.kt'
 contracts=(current/'TrafficSignContracts.kt').read_text()
 begin=contracts.index('data class NormalizedTrafficSignBoundingBox(')
 # The calibration helper is not exercised by this benchmark (no sign boxes).
 # Keep its exact production type, including validation, for future callers.
 end=contracts.index('\n}\n',begin)+2
 (sources/'BoundingBox.kt').write_text('package de.youspeed.android.alpha\n'+contracts[begin:end]+'\n')
 geometry=snippet(runtime,'internal data class LaneImageGeometry(','\ninternal data class LanePreviewGeometry')
 sampler=snippet(runtime,'internal object LaneLumaSampler {','\n/** REALTIME')
 legacy=snippet(old,'internal object LaneLumaSampler {','\n/** REALTIME').replace('LaneLumaSampler','LegacyLaneLumaSampler')
 (sources/'CameraSampler.kt').write_text('package de.youspeed.android.alpha\nimport java.nio.ByteBuffer\n'+geometry+sampler+legacy)
 filter=(a.baseline/'RoadPathLaneFilter.kt').read_text().replace('RoadPathLaneFilter','LegacyRoadPathLaneFilter')
 (sources/'LegacyRoadPathLaneFilter.kt').write_text(filter)
 detector=(a.baseline/'RoadBoundaryDetector.kt').read_text();detector=detector[detector.index('class RoadBoundaryDetector {'):].replace('class RoadBoundaryDetector','class LegacyRoadBoundaryDetector')
 (sources/'LegacyRoadBoundaryDetector.kt').write_text('package de.youspeed.android.alpha\nimport kotlin.math.*\n'+detector)
 session=(a.baseline/'RoadPathSession.kt').read_text()
 for name in ['RoadPathSession','RoadPathPreparedFrame','RoadPathCameraFrame','RoadPathLiveOverlay','RoadPathLaneFilter','RoadBoundaryDetector']:
  session=session.replace(name,'Legacy'+name)
 (sources/'LegacyRoadPathSession.kt').write_text(session)
 shutil.copy2(Path(__file__).with_name('PreparationBenchmark.kt'),sources/'PreparationBenchmark.kt')
 cp=classpath();android=a.sdk/'platforms/android-36/android.jar'
 jar=a.output/'benchmark.jar'
 subprocess.run(['kotlinc',*map(str,sources.glob('*.kt')),'-cp',cp+os.pathsep+str(android),'-include-runtime','-d',str(jar)],check=True)
 dex=a.output/'dex';dex.mkdir()
 subprocess.run([str(a.sdk/'build-tools/36.0.0/d8'),'--min-api','26','--lib',str(android),'--output',str(dex),str(jar),*cp.split(os.pathsep)],check=True)
 subprocess.run(['jar','cf',str((a.output/'benchmark-dex.jar').resolve()),'-C',str(dex),'.'],check=True)
 (a.output/'metadata.json').write_text(json.dumps(dict(scope='Paired standalone ART preparation benchmark; no application deployment or camera/model/recording contention.',sources={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in sources.glob('*.kt')},originalRuntimeSha256=hashlib.sha256(runtime.read_bytes()).hexdigest(),baselineRuntimeSha256=hashlib.sha256(old.read_bytes()).hexdigest()),indent=2)+'\n')

if __name__=='__main__':main()
