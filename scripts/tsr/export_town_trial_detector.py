"""Export the fixed town detector through the mobile model-pack contract."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import torch
from torch import nn
from ultralytics import YOLO

from ultralytics.nn.tasks import DetectionModel

CHECKPOINT_SHA = "f02bf99483c5ad2b79f254b1623b18593ed780c8f3c2df7051331633bb1a2a36"
ARCHITECTURE_SHA = "9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef"
THRESHOLD = 0.840783


def compatible_model(checkpoint, architecture_source):
    for path, expected in ((checkpoint, CHECKPOINT_SHA), (architecture_source, ARCHITECTURE_SHA)):
        if sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Unexpected source SHA-256: {path.name}")
    architecture = deepcopy(YOLO(architecture_source).model.yaml)
    architecture["end2end"] = False
    model = DetectionModel(architecture, nc=1, verbose=False)
    model.end2end = False
    state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model.load_state_dict(state["model"])
    model.eval()
    padded = deepcopy(model)
    head = padded.model[-1]
    # The native raw decoder expects xywh/sign/plate/face. Keep the learned
    # sign convolution and supply permanently inactive compatibility channels.
    for branch in head.cv3:
        sign = branch[-1]
        adapter = nn.Conv2d(sign.in_channels,3,1)
        with torch.no_grad():
            adapter.weight.zero_()
            adapter.bias.fill_(-100.)
            adapter.weight[:1].copy_(sign.weight)
            adapter.bias[:1].copy_(sign.bias)
        branch[-1] = adapter
    head.nc = 3
    head.no = 4*head.reg_max+head.nc
    padded.names = {0:"sign",1:"plate",2:"face"}
    padded.eval()
    pixels = torch.rand((1,3,1024,1024),generator=torch.Generator().manual_seed(72))
    with torch.inference_mode():
        expected = model(pixels)[0]
        actual = padded(pixels)[0]
    if actual.shape != (1,7,21504) or actual[:,5:].count_nonzero().item():
        raise ValueError("The compatibility channels must always be inactive")
    torch.testing.assert_close(actual[:,:5],expected,rtol=1e-5,atol=1e-5)
    return padded


def export(fmt, checkpoint, architecture, output_dir):
    torch.set_num_threads(4)
    folder = output_dir/fmt
    folder.mkdir(parents=True,exist_ok=True)
    path = folder/"town_yolo26n_trial.pt"
    torch.save({"model":compatible_model(checkpoint, architecture),"train_args":{"task":"detect","imgsz":1024}},path)
    model = YOLO(path)
    output = model.export(format=fmt,imgsz=1024,batch=1,half=True,nms=fmt=="coreml",
                          iou=.45,conf=.25,end2end=False,device="cpu")
    report = {"source_checkpoint_sha256":CHECKPOINT_SHA,"threshold":THRESHOLD,"format":fmt,
              "padding_classes":"inactive","path":str(output)}
    (folder/"receipt.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report),flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("format",choices=("coreml","tflite"))
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--architecture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export(args.format, args.checkpoint, args.architecture, args.output)
