#!/usr/bin/env python3
"""Run identical independent stills through unmodified Swift/Kotlin lane sessions.

One fresh session and one exposure per still. Processing clocks are fixed at zero
for deterministic semantics; operation caps remain active. No camera equivalence,
temporal maturity, sign relevance, accuracy or device timing is inferred here.
"""
import argparse
from collections import Counter
import hashlib,json,math,os,re,shutil,subprocess
from pathlib import Path
from replay_path import classpath

ROOT=Path(__file__).resolve().parents[2]
SWIFT=['LaneDetection','RoadBoundaryDetector','VisualRoadCalibration','RoadBoundaryTemporalTracker',
       'RoadBoundaryPresentationGate','RoadBoundaryMotionHint','RoadPathEvidence','TrafficSignApplicability','RoadPathSession']
KOTLIN=['LaneDetection','RoadBoundaryDetector','RoadBoundaryMotionHint','RoadBoundaryTemporalTracker',
        'RoadBoundaryPresentationGate','RoadPathEvidence','TrafficSignApplicability','VisualRoadCalibration','RoadPathSession','RoadPathLaneFilter']


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def write_json(path,value):Path(path).write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')

def normalized_manifest(path,mode,trace=True):
    path=Path(path).resolve();original=json.loads(path.read_text())
    if original.get('schemaVersion')!=1 or not isinstance(original.get('frames'),list) or not 1<=len(original['frames'])<=2048:
        raise ValueError('Require schemaVersion1 and1..2048 independent stills')
    if mode not in ('preview','tsr'):raise ValueError('Unsupported production session mode')
    if any(original.get(key) for key in ('useSearchBands','groupFragments','fragmentTracking','retainTentativeIdentity','jointSelection')):
        raise ValueError('This comparison uses actual app callsite defaults only')
    frames=[];seen=set()
    for source in original['frames']:
        fid=source.get('id')
        if not isinstance(fid,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]+',fid) or fid in seen:raise ValueError('Require unique ASCII frame identity')
        seen.add(fid)
        if source.get('sequenceId')!=fid or type(source.get('time')) not in (int,float) or source['time']!=0:
            raise ValueError('Each still must have sequenceId=id and time=0; no repeated-frame confirmation')
        width,height=source.get('width'),source.get('height');dw,dh=source.get('decodedWidth'),source.get('decodedHeight')
        if type(width) is not int or type(height) is not int or not(64<=width<=384 and 64<=height<=216):raise ValueError('Analysis dimensions out of bounds')
        if type(dw) is not int or type(dh) is not int or min(dw,dh)<1 or abs(dw/dh-width/height)>.015:raise ValueError('Decoded geometry/aspect differs')
        if source.get('variant','raw') not in ('raw','luma',None):raise ValueError('Require unfiltered luma; production filter runs natively')
        if any(source.get(key) for key in ('calibration','visualCalibration','locationFixes','orientationKey')):
            raise ValueError('Image-only still comparison cannot invent calibration/motion metadata')
        gray=Path(source['grayPath']);gray=(path.parent/gray).resolve() if not gray.is_absolute() else gray.resolve()
        if gray.stat().st_size!=width*height or source.get('graySha256')!=sha(gray):raise ValueError('Input gray bytes/hash differs')
        frame=dict(id=fid,sequenceId=fid,time=0.0,grayPath=str(gray),graySha256=sha(gray),width=width,height=height,decodedWidth=dw,decodedHeight=dh)
        for key in ('source','sourceFrameId','split','dataset','groupId','sceneTags'):
            if key in source:frame[key]=source[key]
        if 'semanticScoreAdjustments' in source and source['semanticScoreAdjustments'] is not None:
            values=source['semanticScoreAdjustments']
            if mode!='preview' or not isinstance(values,list) or len(values)>6 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=.1 for v in values):
                raise ValueError('Require bounded preview-only semantic score adjustments')
            if source.get('semanticSourceInputSha256')!=frame['graySha256']:raise ValueError('Semantic source exposure hash differs')
            frame.update(semanticScoreAdjustments=values,semanticSourceInputSha256=frame['graySha256'])
        frames.append(frame)
    return dict(schemaVersion=1,sessionMode=mode,detectorTrace=bool(trace),frames=frames)

def differences(left,right,path='frames'):
    output=[]
    if type(left) in (int,float) and type(right) in (int,float):
        if left!=right:output.append(dict(path=path,swift=left,kotlin=right))
    elif isinstance(left,dict) and isinstance(right,dict) and left.keys()==right.keys():
        for key in left:output.extend(differences(left[key],right[key],path+'.'+key))
    elif isinstance(left,list) and isinstance(right,list) and len(left)==len(right):
        for i,(a,b) in enumerate(zip(left,right)):output.extend(differences(a,b,f'{path}[{i}]'))
    elif left!=right:output.append(dict(path=path,swift=left,kotlin=right))
    return output

def records(path):return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]

def compile_sources(output,reuse=None):
    sources=output/'sources';sources.mkdir()
    for platform,names,extension,origin in [('swift',SWIFT,'swift',ROOT/'iphone/SpeedConsumerApp'),('kotlin',KOTLIN,'kt',ROOT/'android/app/src/main/java/de/youspeed/android/alpha')]:
        target=sources/platform;target.mkdir()
        for name in names:shutil.copyfile(origin/f'{name}.{extension}',target/f'{name}.{extension}')
        shutil.copyfile(Path(__file__).with_name(f'StillLaneReplay.{extension}'),target/f'StillLaneReplay.{extension}')
    shutil.copyfile(__file__,sources/Path(__file__).name)
    cp=classpath();source_hashes={str(p.relative_to(sources)):sha(p) for p in sorted(sources.rglob('*')) if p.is_file()}
    settings={'swiftOptimization':'-O','swiftVersion':subprocess.check_output(['swiftc','--version'],text=True).strip(),
              'kotlinVersion':subprocess.run(['kotlinc','-version'],capture_output=True,text=True,check=True).stderr.strip(),
              'javaVersion':subprocess.run(['java','-version'],capture_output=True,text=True,check=True).stderr.strip(),
              'serializationJars':{p:sha(Path(p)) for p in cp.split(os.pathsep)}}
    binary,jar=output/'still-swift',output/'still-kotlin.jar'
    commands=[['swiftc','-O','-module-cache-path',str(output/'swift-cache'),*map(str,sorted((sources/'swift').glob('*.swift'))),'-o',str(binary)],
              ['kotlinc',*map(str,sorted((sources/'kotlin').glob('*.kt'))),'-cp',cp,'-include-runtime','-d',str(jar)]]
    if reuse:
        previous=json.loads((reuse/'metadata.json').read_text())
        if previous['sourceHashes']!=source_hashes or previous['buildSettings']!=settings:raise ValueError('Refuse build reuse with different source/compiler/dependencies')
        for name in (binary.name,jar.name):
            if sha(reuse/name)!=previous['binaryHashes'][name]:raise ValueError('Frozen native executable changed')
            shutil.copy2(reuse/name,output/name)
        (output/'compile.log').write_text('Reused hash-verified native build: '+str(reuse)+'\n')
    else:
        with (output/'compile.log').open('w') as log:
            for command in commands:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    return dict(sourceHashes=source_hashes,buildSettings=settings,compileCommands=commands,binaryHashes={p.name:sha(p) for p in (binary,jar)},reuseBuild=str(reuse) if reuse else None),cp

def execute(manifest_path,output,mode='preview',reuse=None,repeat=True,trace=True):
    normalized=normalized_manifest(manifest_path,mode,trace)
    output=Path(output).resolve()
    if output.exists():raise ValueError('Choose a new immutable output directory')
    output.mkdir(parents=True)
    input_path=output/'input.normalized.json';write_json(input_path,normalized)
    build,cp=compile_sources(output,Path(reuse).resolve() if reuse else None)
    metadata=dict(schemaVersion=1,manifest=str(Path(manifest_path).resolve()),manifestSha256=sha(manifest_path),normalizedManifestSha256=sha(input_path),
        sessionMode=mode,frames=len(normalized['frames']),appCallsiteFlags=dict(previewMode=mode=='preview',useSearchBands=False,groupFragments=False,fragmentTracking=False,retainTentativeIdentity=False,jointSelection=False),
        appCallsiteHashes={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'iphone/SpeedConsumerApp/DriveSessionViewModel.swift',ROOT/'android/app/src/main/java/de/youspeed/android/alpha/ConsumerSessionController.kt')},
        maximumGeometryOperations=250000,processingClock='Injected fixed zero; excludes processing deadline and device timing validation',exposureClock='One synthetic relative time0 per independent still; not a measured camera/UTC mapping',
        scope='Production image preprocessing/detector/temporal-first-observation/presentation/selection; no camera adapter, calibration, GPS, real sequence, sign observations or sign-relevance ground truth',**build)
    write_json(output/'metadata.json',metadata)
    commands={'swift':[str(output/'still-swift'),str(input_path)],'kotlin':['java','-cp',str(output/'still-kotlin.jar')+os.pathsep+cp,'de.youspeed.android.alpha.StillLaneReplayKt',str(input_path)]}
    values={};repeat_results={}
    for platform,command in commands.items():
        destination=output/f'{platform}.ndjson'
        with (output/f'{platform}.log').open('w') as log:subprocess.run(command+[str(destination)],stdout=log,stderr=subprocess.STDOUT,check=True)
        values[platform]=records(destination)
        if repeat:
            rerun=output/f'{platform}.repeat.ndjson'
            with (output/f'{platform}.repeat.log').open('w') as log:subprocess.run(command+[str(rerun)],stdout=log,stderr=subprocess.STDOUT,check=True)
            repeat_results[platform]=sha(destination)==sha(rerun)
            if not repeat_results[platform]:raise ValueError('Native deterministic repeat differs: '+platform)
    for platform,rows in values.items():
        if [r['id'] for r in rows]!=[f['id'] for f in normalized['frames']]:raise ValueError('Native output population/order differs')
        for row,frame in zip(rows,normalized['frames']):
            if row['inputSha256']!=frame['graySha256'] or row['sequenceId']!=row['id'] or row['time']!=0 or row['freshInputObservations']!=1:raise ValueError('Native still identity differs')
            if any(item['observationCount']>1 for item in row['lanePresentation']['items']):raise ValueError('Artificial confirmation in still output')
    mismatches=differences(values['swift'],values['kotlin'])
    summaries={platform:dict(frames=len(rows),framesWithRaw=sum(bool(r['rawBoundaries']) for r in rows),rawBoundaries=sum(len(r['rawBoundaries']) for r in rows),framesWithVisible=sum(bool(r['confirmedBoundaries']) for r in rows),geometryBudgetExceeded=sum(r['geometryBudgetExceeded'] for r in rows),selectionReasons=dict(Counter(d['reason'] for r in rows for d in r['lanePresentation']['selectionDecisions']))) for platform,rows in values.items()}
    result=dict(schemaVersion=1,matching=not mismatches,numericTolerance=0,mismatchCount=len(mismatches),mismatches=mismatches,deterministicRepeat=repeat_results,sessionMode=mode,frames=len(normalized['frames']),platforms=summaries,recordsSha256={platform:sha(output/f'{platform}.ndjson') for platform in values},qualification=metadata['scope'])
    write_json(output/'summary.json',result)
    if mismatches:raise ValueError('Native semantics differ; see summary.json')
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--output-dir',type=Path,required=True);parser.add_argument('--session-mode',choices=('preview','tsr'),default='preview');parser.add_argument('--reuse-build',type=Path);parser.add_argument('--no-repeat',action='store_true');parser.add_argument('--no-trace',action='store_true');args=parser.parse_args()
    result=execute(args.manifest,args.output_dir,args.session_mode,args.reuse_build,not args.no_repeat,not args.no_trace)
    print(json.dumps({k:v for k,v in result.items() if k!='mismatches'},indent=2))
if __name__=='__main__':main()
