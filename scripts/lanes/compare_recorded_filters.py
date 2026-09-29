#!/usr/bin/env python3
"""Repeatable recorded-pixel filter experiment. No phone or app mutation.

All generated pixels and scores are diagnostic. Native detector baselines remain unchanged.
"""
from pathlib import Path
import argparse, hashlib, json, subprocess, time
import cv2
import numpy as np

def sha(data): return hashlib.sha256(data).hexdigest()

def input_path(value, manifest):
    path=Path(value)
    return path if path.is_absolute() else manifest.parent/path

def read_verified(path, expected=None):
    data=path.read_bytes()
    if expected is not None and sha(data)!=expected:
        raise ValueError(f'Input SHA256 differs from manifest: {path}')
    return data

def paint_response(gray):
    """Production-like ridge contrast evaluated densely for RESPONSE scoring, not native parity."""
    h,w=gray.shape; response=np.zeros((h,w),np.float32)
    for r in sorted({max(1,round(i*w/384)) for i in (1,2,3)}):
        mean=cv2.boxFilter(gray,cv2.CV_32F,(2*r+1,3),normalize=True,borderType=cv2.BORDER_REPLICATE)
        d=3*r+1
        center=mean[:,d:-d]
        ridge=np.minimum(center-mean[:,:-2*d],center-mean[:,2*d:])
        response[:,d:-d]=np.maximum(response[:,d:-d],np.where(center>=95,ridge,0))
    return np.maximum(response,0)

def paired_edges(gray, operator):
    if operator=='scharr': gx=cv2.Scharr(gray,cv2.CV_32F,1,0,scale=1/32)
    else: gx=cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3,scale=1/8)
    h,w=gray.shape; response=np.zeros((h,w),np.float32)
    for gap in range(2,11):
        left=gap//2;right=gap-left
        response[:,left:w-right]=np.maximum(response[:,left:w-right],np.minimum(gx[:,:w-gap],-gx[:,gap:]))
    return np.maximum(response,0)

def variants(gray, full_gray=None):
    """Each tuple describes source transform, compatible representation, and response threshold."""
    yield 'raw','grayscale',lambda:(gray.copy(),None,26)
    if full_gray is not None:
        yield 'area_resample','grayscale',lambda:(cv2.resize(full_gray,(gray.shape[1],gray.shape[0]),interpolation=cv2.INTER_AREA),None,26)
    yield 'gaussian3','grayscale',lambda:(cv2.GaussianBlur(gray,(3,3),.8),None,26)
    yield 'median3','grayscale',lambda:(cv2.medianBlur(gray,3),None,26)
    yield 'bilateral5','grayscale',lambda:(cv2.bilateralFilter(gray,5,25,2),None,26)
    yield 'clahe2','grayscale',lambda:(cv2.createCLAHE(clipLimit=2,tileGridSize=(8,8)).apply(gray),None,26)
    for width in (5,9,13):
        def tophat(width=width):
            response=cv2.morphologyEx(gray,cv2.MORPH_TOPHAT,np.ones((1,width),np.uint8))
            enhanced=np.clip(gray.astype(np.float32)+1.5*response,0,255).astype(np.uint8)
            return enhanced,response.astype(np.float32),18
        yield f'tophat{width}_enhanced','grayscale-enhancement',tophat
    for operator in ('sobel','scharr'):
        for threshold in (8,12):
            def edges(operator=operator,threshold=threshold):
                response=paired_edges(gray,operator)
                mask=(response>=threshold).astype(np.uint8)*255
                # Deliberate three-pixel bright ridge adapter; not original image intensity.
                adapted=cv2.dilate(mask,np.ones((1,3),np.uint8))
                return adapted,response,threshold
            yield f'{operator}_paired{threshold}','binary-ridge-adapter',edges
    for low,high in ((30,90),(50,150)):
        def canny(low=low,high=high):
            edges=cv2.Canny(cv2.GaussianBlur(gray,(3,3),.8),low,high,L2gradient=True)
            return cv2.dilate(edges,np.ones((1,3),np.uint8)),edges.astype(np.float32),127
        yield f'canny{low}_{high}','binary-ridge-adapter',canny

def roi_mask(h,w,annotation):
    roi=np.zeros((h,w),np.uint8)
    if annotation and annotation.get('roadPolygon'):
        points=np.array([[round(x*(w-1)),round(y*(h-1))] for x,y in annotation['roadPolygon']],np.int32)
        cv2.fillPoly(roi,[points],255)
    else: roi[round(.5*(h-1)):round(.94*(h-1))+1]=255
    for polygon in (annotation or {}).get('ignorePolygons',[]):
        points=np.array([[round(x*(w-1)),round(y*(h-1))] for x,y in polygon],np.int32)
        cv2.fillPoly(roi,[points],0)
    return roi>0

def score_response(mask, annotation, tolerance):
    h,w=mask.shape;roi=roi_mask(h,w,annotation);active=mask & roi
    result={'responsePixelsInRoi':int(active.sum()),'roiPixels':int(roi.sum()),
        'responseDensity':float(active.sum()/max(1,roi.sum())),'annotationAvailable':bool(annotation)}
    if not annotation: return result
    if annotation.get('noPaintROI'):
        negative=roi_mask(h,w,{'roadPolygon':annotation['noPaintROI']})
        result.update(noPaintRoiPixels=int(negative.sum()),falseResponsePixelsInNoPaintRoi=int((mask & negative).sum()),
            falseResponseDensityInNoPaintRoi=float((mask & negative).sum()/max(1,negative.sum())))
    truth=np.zeros((h,w),np.uint8)
    for boundary in annotation.get('boundaries',[]):
        if boundary.get('kind','paint')!='paint':continue
        points=np.array([[round(x*(w-1)),round(y*(h-1))] for x,y in boundary['points']],np.int32)
        if len(points)>1:cv2.polylines(truth,[points],False,255,1)
    target=(truth>0)&roi
    if not target.any():return result
    near_response=cv2.dilate(active.astype(np.uint8),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*tolerance+1,2*tolerance+1)))>0
    near_truth=cv2.dilate(target.astype(np.uint8),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*tolerance+1,2*tolerance+1)))>0
    off=active & ~near_truth
    result.update(annotatedPaintPixels=int(target.sum()),coveredPaintPixels=int((target & near_response).sum()),annotatedPaintCoverage=float((target & near_response).sum()/target.sum()),
        offAnnotationResponsePixels=int(off.sum()),offAnnotationResponseFraction=float(off.sum()/max(1,active.sum())),
        tolerancePixels=tolerance,exhaustiveAnnotation=annotation.get('exhaustive',False),
        offAnnotationInterpretation='false_positive_response' if annotation.get('exhaustive',False) else 'unlabeled_or_false_response')
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--annotations',type=Path);p.add_argument('--native',type=Path);p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--native-source',type=Path,action='append',default=[],help='Source file to fingerprint alongside native executable; repeatable')
    p.add_argument('--tolerance',type=int,default=3);a=p.parse_args()
    if a.output.exists():raise SystemExit('Use a new output directory; refusing to overwrite experiment')
    a.output.mkdir(parents=True)
    cv2.setNumThreads(1)
    dataset=json.loads(a.dataset.read_text());frames=dataset['frames'] if isinstance(dataset,dict) else dataset
    annotations={}
    if a.annotations:
        rows=json.loads(a.annotations.read_text());rows=rows.get('frames',rows) if isinstance(rows,dict) else rows
        annotations={f['id']:f for f in rows}
    manifest=[];metrics=[];inputs=[];seen=set()
    for index,frame in enumerate(frames):
        if not frame['id'] or frame['id'] in seen:raise ValueError('Empty or duplicate source frame id')
        seen.add(frame['id'])
        graypath=input_path(frame['grayPath'],a.dataset)
        raw=read_verified(graypath,frame.get('graySha256'));w,h=frame['width'],frame['height']
        if not (isinstance(w,int) and isinstance(h,int) and 64<=w<=384 and 64<=h<=216):
            raise ValueError('This experiment requires exact admitted RoadBoundaryDetector dimensions: 64..384 by 64..216')
        if len(raw)!=w*h:raise ValueError(f"Wrong raw byte count for {frame['id']}")
        gray=np.frombuffer(raw,dtype=np.uint8).reshape(h,w);inputs.append({'id':frame['id'],'graySha256':sha(raw),'width':w,'height':h})
        full_gray=None
        if frame.get('fullGrayPath'):
            full_raw=read_verified(input_path(frame['fullGrayPath'],a.dataset),frame.get('fullGraySha256'))
            if len(full_raw)!=frame['rawWidth']*frame['rawHeight']:raise ValueError('Wrong full raw byte count')
            full_gray=np.frombuffer(full_raw,dtype=np.uint8).reshape(frame['rawHeight'],frame['rawWidth'])
            inputs[-1]['fullGraySha256']=sha(full_raw)
        rgb=None
        if frame.get('rgbPath'):
            rgb_bytes=read_verified(input_path(frame['rgbPath'],a.dataset),frame.get('rgbSha256'))
            inputs[-1]['rgbSha256']=sha(rgb_bytes)
            rgb=cv2.imdecode(np.frombuffer(rgb_bytes,np.uint8),cv2.IMREAD_COLOR)
            if rgb is None:raise ValueError(f"RGB image cannot be decoded: {frame['id']}")
        if rgb is not None and rgb.shape[:2]!=(h,w):rgb=cv2.resize(rgb,(w,h),interpolation=cv2.INTER_AREA)
        base=rgb if rgb is not None else cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR)
        panels=[]
        for name,representation,transform in variants(gray,full_gray):
            times=[]
            for _ in range(max(1,a.repeats)):
                start=time.perf_counter_ns();processed,response,threshold=transform();times.append((time.perf_counter_ns()-start)/1e6)
            # Ridge response on enhanced gray records its compatibility with the unchanged extractor.
            native_compatible_response=paint_response(processed)
            response=native_compatible_response if response is None else response
            mask=response>=threshold
            folder=a.output/name;folder.mkdir(exist_ok=True)
            stem=f'{index:04d}';raw_out=(folder/(stem+'.gray')).resolve();raw_out.write_bytes(processed.tobytes())
            cv2.imwrite(str(folder/(stem+'-input.png')),processed)
            heat=np.clip(response*(255/max(1,float(np.percentile(response[response>0],95)) if np.any(response>0) else 1)),0,255).astype(np.uint8)
            cv2.imwrite(str(folder/(stem+'-response.png')),heat)
            cv2.imwrite(str(folder/(stem+'-mask.png')),mask.astype(np.uint8)*255)
            manifest.append(dict(id=frame['id']+'::'+name,sourceFrameId=frame['id'],variant=name,source=frame.get('source',''),
                time=frame.get('time',0),width=w,height=h,grayPath=str(raw_out),graySha256=sha(processed.tobytes()),representation=representation))
            score=score_response(mask,annotations.get(frame['id']),a.tolerance)
            compatibility=score_response(native_compatible_response>=26,annotations.get(frame['id']),a.tolerance)
            metrics.append(dict(id=frame['id'],source=frame.get('source'),time=frame.get('time'),variant=name,representation=representation,
                responseThreshold=threshold,hostFilterMs=times,coldFilterMs=times[0],response=score,
                unchangedGrayRidgeResponse=compatibility,outputSha256=sha(processed.tobytes())))
            panel=base.copy();panel[mask & roi_mask(h,w,annotations.get(frame['id']))]=(0,0,255)
            panel=cv2.copyMakeBorder(panel,24,0,0,0,cv2.BORDER_CONSTANT,value=(28,28,28))
            cv2.putText(panel,name,(5,17),cv2.FONT_HERSHEY_SIMPLEX,.43,(255,255,255),1,cv2.LINE_AA);panels.append(panel)
        blank=np.zeros_like(panels[0])
        while len(panels)%4:panels.append(blank)
        sheet=np.vstack([np.hstack(panels[i:i+4]) for i in range(0,len(panels),4)])
        cv2.imwrite(str(a.output/(f'{index:04d}-response-contact.jpg')),sheet)
    manifest_path=a.output/'variants.json';manifest_path.write_text(json.dumps({'schemaVersion':1,'frames':manifest},indent=2)+'\n')
    (a.output/'response-metrics.json').write_text(json.dumps({'schemaVersion':1,'opencvVersion':cv2.__version__,'dataset':str(a.dataset.resolve()),
        'datasetSha256':sha(a.dataset.read_bytes()),'scriptSha256':sha(Path(__file__).read_bytes()),
        'nativeExecutableSha256':sha(a.native.read_bytes()) if a.native else None,
        'nativeSourceSha256':{str(path):sha(path.read_bytes()) for path in a.native_source},'inputs':inputs,'metrics':metrics,
        'limitations':['Host filter timings exclude response scoring/image export/native detector; not Moto latency.',
        'Response metrics are dense pixel support, separate from native24-row candidate extraction.',
        'Binary-ridge adapters deliberately synthesize intensity; counts are not ordinary-gray parity.',
        'Without exhaustive annotation, off-annotation responses are not confirmed false positives.']},indent=2)+'\n')
    if a.native:subprocess.run([str(a.native.resolve()),str(manifest_path.resolve()),str((a.output/'native-baseline.ndjson').resolve())],check=True)
    print(json.dumps({'frames':len(frames),'variantsPerFrame':len(manifest)//max(1,len(frames)),'manifest':str(manifest_path.resolve()),'nativeRun':bool(a.native)},indent=2))
if __name__=='__main__':main()
