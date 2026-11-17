#!/usr/bin/env python3
"""Measure the actual native tile-label balance without new model inference."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import hashlib


def main():
    import ultralytics
    from ultralytics.data.dataset import YOLODataset
    assert ultralytics.__version__=='8.4.213'
    root=Path('/job/latest-ultralytics-v1')
    data=YOLODataset(img_path=str(root/'pilot-tile/data/train.txt'),imgsz=1024,batch_size=16,
                     cache=False,augment=False,rect=False,tile=True,data={'names':{0:'sign'},'nc':1})
    source_counts={raw['source_index']:len(raw['cls']) for raw in data.labels}
    counts=Counter();boxes=0
    for raw in data.labels:
        label=deepcopy(raw)
        x1,y1,x2,y2=label['tile'];label['ori_shape']=(y2-y1,x2-x1)
        adjusted=data.update_labels_info(label)
        n=len(adjusted['cls']);boxes+=n;counts['positive_tiles' if n else 'empty_tiles']+=1
    assert len(data)==830
    report={'schema':'streetshots-native-tile-label-balance-v1','ultralytics':ultralytics.__version__,
            'positive_source_images':sum(n>0 for n in source_counts.values()),'original_source_label_instances':sum(source_counts.values()),'training_source_images':len(data.tile_counts),'tile_samples':len(data),'label_instances_after_native_clipping':boxes,
            **counts,'positive_tile_fraction':counts['positive_tiles']/len(data),
            'method':'Exact installed YOLODataset tile_windows and update_labels_info/Instances.crop; before stochastic augmentation; no new inference or holdout inspection.',
            'interpretation':'Tiling changes both object scale and foreground/background balance. This is a plausible contributor to confidence changes, not an isolated causal test.',
            'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (root/'tile-balance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
