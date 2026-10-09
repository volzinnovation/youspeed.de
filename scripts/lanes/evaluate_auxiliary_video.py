#!/usr/bin/env python3
"""Apply an A2D2-trained auxiliary head to hash-bound video targets, inference only.

Private video never enters training. Sparse approximate paint reviews and a
reviewed negative ROI support transfer diagnostics, not dense paint IoU or
on-device performance claims. No native or speed-policy behavior changes.
"""
import argparse
from collections import defaultdict
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
THRESHOLD = .5


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def load_bound_manifest(path):
    """Verify exported RGB and gray separately; RGB resize cannot reconstruct raw gray."""
    manifest = json.loads(Path(path).read_text())
    if 'provenanceSha256' in manifest:
        provenance = Path(path).parent / 'provenance.json'
        if sha(provenance) != manifest['provenanceSha256']:
            raise ValueError('Export provenance binding mismatch')
    rows = manifest['frames']
    seen, previous, previous_pts, shapes = set(), {}, {}, {}
    for row in rows:
        fid = row['id']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', fid) or fid in seen:
            raise ValueError('Duplicate/unsafe frame ID')
        seen.add(fid)
        key = row['sequenceId']
        identity = row['sourceVideoSha256'], row['split'], row['width'], row['height']
        if key in shapes and shapes[key] != identity:
            raise ValueError('Sequence crosses source/split/shape identity')
        shapes[key] = identity
        if not math.isfinite(row['time']) or (key in previous and row['time'] <= previous[key]):
            raise ValueError('Sequence times must strictly increase')
        previous[key] = row['time']
        if not math.isfinite(row['actualPTS']) or (key in previous_pts and row['actualPTS'] <= previous_pts[key]):
            raise ValueError('Encoded sequence PTS must strictly increase')
        previous_pts[key] = row['actualPTS']
        if not re.fullmatch(r'[a-f0-9]{64}', row['sourceVideoSha256']):
            raise ValueError('Missing source content identity')
        if row.get('status', 'available') != 'available':
            raise ValueError('Unavailable RGB target')
        width, height = row['width'], row['height']
        if type(width) is not int or type(height) is not int or not 2 <= width <= 384 or not 2 <= height <= 216:
            raise ValueError('Invalid analysis dimensions')
        if sha(row['grayPath']) != row['graySha256'] or Path(row['grayPath']).stat().st_size != width * height:
            raise ValueError('Gray binding mismatch: ' + fid)
        if row.get('sourceFrameGraySha256', row['graySha256']) != row['graySha256']:
            raise ValueError('Source exposure/gray binding mismatch: ' + fid)
        if sha(row['rgbPath']) != row['rgbSha256']:
            raise ValueError('RGB binding mismatch: ' + fid)
        image = cv2.imread(row['rgbPath'], cv2.IMREAD_COLOR)
        if image is None or image.shape != (row['rgbHeight'], row['rgbWidth'], 3):
            raise ValueError('RGB shape mismatch: ' + fid)
        if abs(float(row['ptsValue'] * Fraction(row['timeBase'])) - row['actualPTS']) > 1e-9:
            raise ValueError('Original encoded PTS binding mismatch: ' + fid)
        if row.get('sourceFrameId') != f"{row['sourceVideoSha256']}:{row['ptsValue']}:{row['timeBase']}":
            raise ValueError('Original source exposure identity mismatch: ' + fid)
        transform = row['transform']
        if transform.get('crop') is not None or (transform['analysisWidth'], transform['analysisHeight']) != (width, height):
            raise ValueError('Only uncropped full-image analysis transforms are supported')
        if (transform['uprightWidth'], transform['uprightHeight']) != (row['decodedWidth'], row['decodedHeight']):
            raise ValueError('Upright source dimensions mismatch')
        # Both images must be aspect-preserving integer fits of the same upright frame.
        uw, uh = transform['uprightWidth'], transform['uprightHeight']
        if abs(row['rgbWidth'] / uw - row['rgbHeight'] / uh) > max(1 / uw, 1 / uh):
            raise ValueError('RGB aspect transform mismatch')
        if abs(width / uw - height / uh) > max(1 / uw, 1 / uh):
            raise ValueError('Analysis aspect transform mismatch')
    if not rows:
        raise ValueError('Empty target manifest')
    return rows


def inverse_letterbox(probability, transform, width, height):
    """Inverse pixel-center letterbox: exact integer crop, then bilinear resampling."""
    size = transform['inputSize']
    left, top = transform['padLeft'], transform['padTop']
    rw, rh = transform['resizedWidth'], transform['resizedHeight']
    if (probability.shape != (size, size) or any(type(v) is not int for v in (size,left,top,rw,rh))
            or min(rw,rh) <= 0 or min(left,top) < 0 or left+rw > size or top+rh > size):
        raise ValueError('Invalid letterbox dimensions')
    if not np.isfinite(probability).all() or probability.min() < 0 or probability.max() > 1:
        raise ValueError('Invalid model probabilities')
    unpadded = probability[top:top+rh, left:left+rw]
    restored = cv2.resize(unpadded, (width,height), interpolation=cv2.INTER_LINEAR)
    return np.ascontiguousarray(restored, dtype=np.float32)


class AuxiliaryPredictor:
    """A target-only adapter; no neighboring image or label is passed to the network."""
    def __init__(self, checkpoint, detector, device):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from scripts.lanes import train_a2d2_auxiliary as training
        import torch
        self.torch, self.training, self.device = torch, training, device
        self.extractor, self.head, self.config = training.load_auxiliary(checkpoint, detector, device=device)
        self.extractor.eval()
        self.head.eval()
        if self.config.get('detectorSha256') != sha(detector):
            raise ValueError('Checkpoint detector binding mismatch')
        self.config_sha256 = canonical_sha(self.config)

    def synchronize(self):
        if str(self.device).startswith('cuda'):
            self.torch.cuda.synchronize(self.device)
        elif str(self.device).startswith('mps'):
            self.torch.mps.synchronize()

    def __call__(self, bgr, width, height):
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        size = self.config['inputSize']
        tensor, transform = self.training.letterbox_rgb(rgb, size)
        with self.torch.inference_mode():
            logits = self.head(self.extractor(tensor.unsqueeze(0).to(self.device)))
            logits = self.torch.nn.functional.interpolate(logits, size=(size,size), mode='bilinear', align_corners=False)
            probability = self.torch.sigmoid(logits)[0,0].detach().cpu().numpy()
        result = inverse_letterbox(probability, transform, width, height)
        return result, transform


def distribution(values):
    values = np.asarray(values, dtype=np.float32).reshape(-1)
    if not values.size:
        return dict(count=0)
    return dict(count=int(values.size), mean=float(values.mean()), minimum=float(values.min()),
                p10=float(np.quantile(values,.1)), median=float(np.median(values)),
                p90=float(np.quantile(values,.9)), maximum=float(values.max()),
                fractionAtLeastHalf=float((values >= THRESHOLD).mean()))


def review_helpers():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.lanes import audit_teacher_labels as audit
    return audit


def sparse_positive_scores(probability, label, settings):
    """Only explicitly painted spans; band maximum reflects approximate geometry."""
    audit = review_helpers()
    height, width = probability.shape
    exact, nearby = [], []
    points, seen = [], set()
    tolerance = settings['paintToleranceX'] * (width-1)
    for border in label['borders']:
        for y in range(height):
            ny = y / (height-1)
            if not label['evaluationYRange'][0] <= ny <= label['evaluationYRange'][1]:
                continue
            if not any(lo <= ny <= hi for lo,hi in border['paintedYIntervals']):
                continue
            nx = audit.x_at(border['geometry'], ny)
            if nx is None:
                continue
            if any((q := audit.x_at(region['points'],ny)) is not None and abs(q-nx) <= region['tolerance']
                   for region in label.get('ignoreGeometry',[])):
                continue
            x = nx * (width-1)
            identity = round(x,6), y
            if identity in seen:
                continue
            seen.add(identity)
            lo, hi = max(0,math.floor(x-tolerance)), min(width-1,math.ceil(x+tolerance))
            center = float(np.interp(x, np.arange(width), probability[y]))
            band = float(probability[y,lo:hi+1].max())
            exact.append(center);nearby.append(band)
            points.append(dict(x=nx,y=ny,centerlineProbability=center,bandMaximumProbability=band))
    return dict(centerline=distribution(exact), approximateBandMaximum=distribution(nearby),
                paintToleranceX=settings['paintToleranceX'],points=points,
                scope='Sparse approximate reviewed ego-border paint spans only; other paint is unknown; not dense IoU or precision')


def bind_reviews(rows, labels_path=None, negative_path=None):
    audit = review_helpers()
    byid = {row['id']:dict(row,inputSha256=row['graySha256']) for row in rows}
    labels, negatives, settings = {}, {}, None
    if labels_path:
        settings = json.loads(Path(labels_path).read_text())
        if not audit.finite(settings.get('paintToleranceX')) or not 0 <= settings['paintToleranceX'] <= 1:
            raise ValueError('Invalid approximate paint tolerance')
        for label in settings['frames']:
            if label['id'] in labels or label['id'] not in byid:
                raise ValueError('Duplicate/missing reviewed target')
            audit.bind_label(label,byid[label['id']])
            labels[label['id']] = label
    if negative_path:
        negative = json.loads(Path(negative_path).read_text())
        for interval_index,interval in enumerate(negative['intervals']):
            lo,hi = audit.y_range(interval['evaluationYRange'])
            start,end = interval['startSeconds'],interval['endSeconds']
            if not audit.finite(start) or not audit.finite(end) or start >= end:
                raise ValueError('Invalid negative interval')
            ids = interval['frameIDs']
            if not ids:
                raise ValueError('Empty negative interval')
            previous = -math.inf
            for index,fid in enumerate(ids):
                if fid not in byid or fid in negatives:
                    raise ValueError('Missing/duplicate negative target')
                row=byid[fid]
                if (row['sequenceId']!=interval['sequenceId'] or row['inputSha256']!=interval['inputSha256'].get(fid)
                        or not start <= row['time'] < end or row['time'] <= previous):
                    raise ValueError('Negative target identity/hash/time mismatch')
                previous=row['time']
                next_time=byid[ids[index+1]]['time'] if index+1<len(ids) else end
                dt=min(.2,max(0.,min(next_time,end)-row['time']))
                negatives[fid]=dict(intervalIndex=interval_index,evaluationYRange=[lo,hi],attributedDurationSeconds=dt,
                                    startSeconds=start,endSeconds=end,qualification=negative['qualification'])
    return labels,negatives,settings


def negative_score(probability, binding):
    height,width=probability.shape
    lo,hi=binding['evaluationYRange']
    ys=np.arange(height)/(height-1)
    roi=probability[(ys>=lo)&(ys<=hi),:]
    count=int((roi>=THRESHOLD).sum())
    return dict(binding,roiPixelCount=int(roi.size),falsePositivePixels=count,
                falsePositivePixelFraction=count/int(roi.size),probability=distribution(roi),
                sampledPositiveDurationSeconds=binding['attributedDurationSeconds'] if count else 0.)


def render_overlay(bgr,probability):
    h,w=probability.shape
    base=cv2.resize(bgr,(w,h),interpolation=cv2.INTER_AREA)
    marked=base.copy()
    mask=probability>=THRESHOLD
    marked[mask]=(marked[mask].astype(np.float32)*.4+np.array([0,180,255])*.6).astype(np.uint8)
    return base,marked


def contact_sheet(path,entries,rows,probabilities):
    width,height=384,216
    sheet=np.full((42+len(entries)*(height+28),width*2,3),24,np.uint8)
    cv2.putText(sheet,'Auxiliary marking probabilities >=0.5 (orange); target-only video transfer', (8,18),cv2.FONT_HERSHEY_SIMPLEX,.42,(255,255,255),1)
    cv2.putText(sheet,'Left: original target. Right: prediction. Approximate review is not dense truth.', (8,35),cv2.FONT_HERSHEY_SIMPLEX,.40,(220,220,220),1)
    for index,fid in enumerate(entries):
        row=rows[fid];image=cv2.imread(row['rgbPath']);base,marked=render_overlay(image,probabilities[fid])
        y=42+index*(height+28)
        cv2.putText(sheet,f'{fid}  t={row["time"]:.3f}',(8,y+19),cv2.FONT_HERSHEY_SIMPLEX,.43,(255,255,255),1)
        sheet[y+28:y+28+height,:width]=cv2.resize(base,(width,height))
        sheet[y+28:y+28+height,width:]=cv2.resize(marked,(width,height))
    if not cv2.imwrite(str(path),sheet):raise ValueError('Contact sheet export failed')
    return dict(path=str(path),sha256=sha(path),frameIDs=entries)


def overlay_video(path,rows,probabilities,ffmpeg):
    """A fixed-10-Hz QA montage; original PTS are shown, never reinterpreted."""
    chosen=[row for row in rows if row['sequenceId'] in ('fresh-day-access','fresh-day-marked')]
    if not chosen:
        return dict(status='not_applicable',reason='Reviewed marked-day and negative sequences absent')
    command=[ffmpeg,'-v','error','-f','rawvideo','-pix_fmt','bgr24','-video_size','768x246',
             '-framerate','10','-i','pipe:0','-an','-c:v','libx264','-crf','20','-pix_fmt','yuv420p',
             '-movflags','+faststart',str(path)]
    process=None
    try:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        for row in chosen:
            plain,marked=render_overlay(cv2.imread(row['rgbPath']),probabilities[row['id']])
            frame=np.full((246,768,3),24,np.uint8)
            frame[30:,:384]=cv2.resize(plain,(384,216))
            frame[30:,384:]=cv2.resize(marked,(384,216))
            cv2.putText(frame,f'{row["id"]}  PTS {row["actualPTS"]:.3f}  orange >=0.5',
                        (8,20),cv2.FONT_HERSHEY_SIMPLEX,.43,(255,255,255),1)
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        error=process.stderr.read().decode(errors='replace')
        code=process.wait()
        if code:
            return dict(status='unavailable',reason=error[-2000:])
        return dict(status='created',path=str(path),sha256=sha(path),frames=len(chosen),displayFPS=10,
                    qualification='Fixed-cadence QA montage, not original capture timing; source PTS shown per frame')
    except (OSError,BrokenPipeError) as error:
        if process is not None:
            process.kill();process.wait()
        return dict(status='unavailable',reason=str(error))


def sync_predictor(predictor):
    synchronize=getattr(predictor,'synchronize',None)
    if synchronize:
        synchronize()


def run(args,predictor_factory=AuxiliaryPredictor):
    input_hashes={str(args.manifest):sha(args.manifest),str(Path(__file__)):sha(__file__)}
    for path in (args.labels,args.negative_labels):
        if path:input_hashes[str(path)]=sha(path)
    rows=load_bound_manifest(args.manifest)
    labels,negatives,settings=bind_reviews(rows,args.labels,args.negative_labels)
    out=args.output_dir.resolve()
    if out==ROOT or ROOT in out.parents:raise ValueError('Outputs must remain outside repository')
    if out.exists():raise ValueError('Output exists; refusing overwrite')
    weights_sha,detector_sha=sha(args.checkpoint),sha(args.detector)
    predictor=predictor_factory(args.checkpoint,args.detector,args.device)
    out.mkdir(parents=True)
    for directory in ('masks','probabilities'): (out/directory).mkdir()
    probabilities,records,latencies={},[],[]
    try:
        first=rows[0]
        warm_image=cv2.imread(first['rgbPath'],cv2.IMREAD_COLOR)
        for _ in range(5):predictor(warm_image,first['width'],first['height'])
        sync_predictor(predictor)
        for index,row in enumerate(rows):
            image=cv2.imread(row['rgbPath'],cv2.IMREAD_COLOR)
            sync_predictor(predictor)
            began=time.perf_counter()
            probability,letterbox=predictor(image,row['width'],row['height'])
            mask=probability>=THRESHOLD
            sync_predictor(predictor)
            elapsed_ms=(time.perf_counter()-began)*1000
            latencies.append(elapsed_ms)
            if probability.shape!=(row['height'],row['width']) or not np.isfinite(probability).all() or probability.min()<0 or probability.max()>1:
                raise ValueError('Invalid predicted target probability')
            probability=probability.astype(np.float32)
            pp=out/'probabilities'/(row['id']+'.npy');np.save(pp,probability,allow_pickle=False)
            mp=out/'masks'/(row['id']+'.png')
            if not cv2.imwrite(str(mp),mask.astype(np.uint8)*255):raise ValueError('Mask export failed')
            record={key:row[key] for key in ('id','sequenceId','split','time','actualPTS','ptsValue','timeBase','sourceVideoSha256','grayPath','graySha256','rgbPath','rgbSha256','width','height')}
            record.update(checkpointSha256=weights_sha,detectorSha256=detector_sha,configSha256=predictor.config_sha256,
                          targetOnly=True,usesFutureFrames=False,probabilityPath=str(pp),probabilitySha256=sha(pp),
                          warmedHostInferenceMilliseconds=elapsed_ms,
                          maskPath=str(mp),maskSha256=sha(mp),maskValues=dict(background=0,marking=255),
                          threshold=THRESHOLD,probability=distribution(probability),letterbox=letterbox,
                          inverseLetterbox='Bilinear logits to square (align_corners=False), sigmoid, exact integer pad crop, cv2.INTER_LINEAR to analysis pixel centers')
            if row['id'] in labels: record['sparseReviewedPaint']=sparse_positive_scores(probability,labels[row['id']],settings)
            if row['id'] in negatives: record['knownNegativeROI']=negative_score(probability,negatives[row['id']])
            records.append(record)
            probabilities[row['id']]=probability
            if (index+1)%100==0:print(f'{index+1}/{len(rows)} target-only inferences',flush=True)
        # Independently rerun each sequence's prefix from a fresh checkpoint after
        # all future targets were processed. No future image is passed to a call.
        sequences=defaultdict(list)
        for row in rows:sequences[row['sequenceId']].append(row)
        checks=[]
        for sequence,items in sequences.items():
            fresh=predictor_factory(args.checkpoint,args.detector,args.device)
            for row in items[:3]:
                repeated,_=fresh(cv2.imread(row['rgbPath']),row['width'],row['height'])
                delta=float(np.max(np.abs(repeated-probabilities[row['id']])))
                if delta>1e-6:raise ValueError('Chronological prefix invariance spotcheck failed: '+row['id'])
                checks.append(dict(id=row['id'],maximumAbsoluteDifference=delta))
        byid={r['id']:r for r in rows}
        selected=[]
        # Fixed chronological samples per sequence; no favourable score selection.
        for items in sequences.values():
            for index in (len(items)//4,3*len(items)//4):selected.append(items[index]['id'])
        contact=contact_sheet(out/'contact-sheet.png',selected,byid,probabilities)
        video=overlay_video(out/'reviewed-overlay.mp4',rows,probabilities,args.ffmpeg) if getattr(args,'overlay_video',False) else None
        positive=[r['sparseReviewedPaint'] for r in records if 'sparseReviewedPaint' in r]
        center=[p['centerlineProbability'] for r in positive for p in r['points']]
        band=[p['bandMaximumProbability'] for r in positive for p in r['points']]
        neg=[r['knownNegativeROI'] for r in records if 'knownNegativeROI' in r]
        total_roi=sum(r['roiPixelCount'] for r in neg);fp=sum(r['falsePositivePixels'] for r in neg)
        summary=dict(schemaVersion=1,frames=len(rows),sequences=len(sequences),threshold=THRESHOLD,
                     scoreCalibration='Uncalibrated sigmoid scores; fixed 0.5 threshold; no private-video threshold tuning',
                     checkpointSha256=weights_sha,detectorSha256=detector_sha,config=predictor.config,configSha256=predictor.config_sha256,
                     inputManifest=str(args.manifest.resolve()),inputManifestSha256=sha(args.manifest),evaluatorSha256=sha(__file__),device=args.device,
                     trainingPerformedByEvaluator=False,usesFutureFrames=False,targetOnly=True,
                     hostLatency=dict(warmupCalls=5,samples=len(latencies),meanMilliseconds=float(np.mean(latencies)),
                         p50Milliseconds=float(np.median(latencies)),p95Milliseconds=float(np.quantile(latencies,.95)),
                         maximumMilliseconds=float(max(latencies)),platform=platform.platform(),machine=platform.machine(),
                         device=args.device,synchronized=True,
                         scope='Decoded RGB image to binary analysis mask: color conversion, letterbox, frozen detector features, auxiliary head, CPU transfer, inverse letterbox and threshold. Excludes PNG input decoding, model load and output export. Host measurement, not phone performance.'),
                     prefixInvariance=dict(passed=True,checkedFrames=len(checks),tolerance=1e-6,checks=checks,
                         definition='First three targets per sequence independently rerun with a fresh checkpoint after full chronological inference'),
                     sparseReviewedPaint=dict(reviewedFrames=len(positive),centerline=distribution(center),approximateBandMaximum=distribution(band),
                         qualification=settings['qualification'] if settings else 'No reviewed positives supplied'),
                     knownNegativeROI=dict(scoredFrames=len(neg),framesWithFalsePositivePixels=sum(r['falsePositivePixels']>0 for r in neg),
                         falsePositivePixels=fp,roiPixels=total_roi,falsePositivePixelFraction=fp/total_roi if total_roi else None,
                         sampledPositiveDurationSeconds=sum(r['sampledPositiveDurationSeconds'] for r in neg),
                         reviewedSampleDurationSeconds=sum(r['attributedDurationSeconds'] for r in neg),
                         durationDefinition='Per-target state held until next reviewed sample or interval end, capped at 0.2 seconds; intervening sensor exposures unobserved',
                         qualification=neg[0]['qualification'] if neg else 'No negative ROI supplied'),
                     annotationScope='Approximate development paint spans and reviewed negative ROI only; unreviewed pixels unknown; no dense IoU, precision, acceptance or on-device performance claim',
                     contactSheet=contact,overlayVideo=video)
        if args.labels:summary['reviewedLabelsSha256']=sha(args.labels)
        if args.negative_labels:summary['negativeLabelsSha256']=sha(args.negative_labels)
        # Recheck inputs and immutable checkpoint after inference before publication.
        load_bound_manifest(args.manifest)
        if any(sha(path)!=digest for path,digest in input_hashes.items()):
            raise ValueError('Manifest, reviews or evaluator changed during inference')
        if sha(args.checkpoint)!=weights_sha or sha(args.detector)!=detector_sha:raise ValueError('Model changed during evaluation')
        write_json(out/'frames.json',dict(schemaVersion=1,frames=records))
        write_json(out/'summary.json',summary)
        print(json.dumps(dict(outputDir=str(out),frames=len(rows),knownNegativeROI=summary['knownNegativeROI'])),flush=True)
        return summary
    except Exception as error:
        write_json(out/'failure.json',dict(status='incomplete',error=str(error)))
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--detector',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--labels',type=Path)
    parser.add_argument('--negative-labels',type=Path)
    parser.add_argument('--device',default='cpu')
    parser.add_argument('--overlay-video',action='store_true',help='Optional fixed-cadence QA MP4 for reviewed day sequences')
    parser.add_argument('--ffmpeg',default='/opt/homebrew/bin/ffmpeg')
    args=parser.parse_args()
    try:run(args)
    except (ValueError,KeyError,OSError) as error:parser.exit(1,f'Auxiliary video evaluation failed: {error}\n')

if __name__=='__main__':main()
