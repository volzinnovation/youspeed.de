"""Prepare identical 1024 RGB tensors for phone detector comparison."""
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import cv2
from PIL import Image

def frame(output, name, pixels):
    h,w = pixels.shape[:2]
    scale = 1024 / max(w,h)
    width,height = round(w*scale),round(h*scale)
    x,y = (1024-width)//2,(1024-height)//2
    resized = cv2.resize(pixels,(width,height),interpolation=cv2.INTER_LINEAR)
    padded = cv2.copyMakeBorder(resized,y,1024-height-y,x,1024-width-x,cv2.BORDER_CONSTANT,value=(114,)*3)
    filename = name + ".png"
    if not cv2.imwrite(str(output/filename),padded,[cv2.IMWRITE_PNG_COMPRESSION,1]):
        raise RuntimeError(f"Cannot write {filename}")
    return {"file":filename,"width":w,"height":h,"transform":[width/w,height/h,x,y]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("videos",nargs="*",type=Path)
    parser.add_argument("--scene-manifest", type=Path)
    parser.add_argument("--scene-images", type=Path)
    args = parser.parse_args()
    if args.videos and (args.scene_manifest or args.scene_images):
        parser.error("Choose video sources or a scene manifest with its image directory")
    if not args.videos and (not args.scene_manifest or not args.scene_images):
        parser.error("Pass videos or both --scene-manifest and --scene-images")
    output = args.output
    output.mkdir(parents=True,exist_ok=False)
    rows = []
    for i,video in enumerate(args.videos):
        capture = cv2.VideoCapture(str(video),cv2.CAP_FFMPEG)
        if not capture.isOpened():
            raise ValueError(f"Cannot open {video.name}")
        fps = capture.get(cv2.CAP_PROP_FPS)
        duration = capture.get(cv2.CAP_PROP_FRAME_COUNT) / fps if fps else 0.
        if duration <= 0:
            raise ValueError("Recorded drive duration is unavailable")
        length = min(6., duration)
        starts = sorted({round(max(0., duration*fraction-length/2),3)
                         for fraction in (.10,.50,.90) if duration > length}) or [0.]
        for window,start in enumerate(starts):
            if not capture.set(cv2.CAP_PROP_POS_MSEC, start*1000):
                raise ValueError(f"Cannot seek {video.name} to {start}s")
            next_pts = start
            end = min(duration,start+length)
            last_pts = -1.
            while True:
                success,pixels = capture.read()
                if not success:
                    break
                pts = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                if pts <= last_pts:
                    raise ValueError("Video timestamps are not increasing")
                last_pts = pts
                if pts >= end:
                    break
                if pts + .015 < next_pts:
                    continue
                name = f"drive-{i:02}-{window:02}-{len(rows):07}"
                rows.append({"id":name,"drive":i,"window":window,"pts":pts,**frame(output,name,pixels)})
                next_pts += .25
        capture.release()
    if not args.videos:
        review = json.loads(args.scene_manifest.read_bytes())
        for row in review:
            name = row["picture_id"]
            data = (args.scene_images/Path(row["image"]).name).read_bytes()
            if sha256(data).hexdigest() != row["source_sha256"]:
                raise ValueError(f"Frozen source changed: {name}")
            with Image.open(BytesIO(data)) as source:
                w,h = source.size
                scale = 1024/max(w,h)
                width,height = round(w*scale),round(h*scale)
                x,y = (1024-width)//2,(1024-height)//2
                canvas = Image.new("RGB",(1024,1024),(114,)*3)
                canvas.paste(source.convert("RGB").resize((width,height),Image.Resampling.BILINEAR),(x,y))
            filename = name + ".png"
            canvas.save(output/filename,compress_level=1)
            rows.append({"id":name,"file":filename,"width":w,"height":h,"transform":[width/w,height/h,x,y]})
    if not rows:
        raise ValueError("No video frames decoded")
    (output/"frames.json").write_text(json.dumps(rows,separators=(",",":")))
    print(len(rows),"paired detector inputs")


if __name__ == "__main__":
    main()
