#!/usr/bin/env python3
"""Paired full-vocabulary crop stress tests; not independent road validation."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter
from train_fr_end_sign_classifier import ClassificationMetrics, ordered_model_names, sha256_file, write_json

VARIANTS = ('clean', 'lowres32', 'lowres64', 'blur', 'dark')

class StressTransform:
    def __init__(self, variant):
        if variant not in VARIANTS:
            raise ValueError(variant)
        self.variant = variant

    def __call__(self, image):
        from torchvision.transforms.functional import to_tensor
        image = image.convert('RGB').resize((224, 224), Image.Resampling.BILINEAR)
        if self.variant.startswith('lowres'):
            side = int(self.variant[6:])
            image = image.resize((side, side), Image.Resampling.BILINEAR).resize((224, 224), Image.Resampling.BILINEAR)
        elif self.variant == 'blur':
            image = image.filter(ImageFilter.GaussianBlur(2.0))
        elif self.variant == 'dark':
            image = ImageEnhance.Brightness(image).enhance(0.5)
        return to_tensor(image)


def main():
    import torch
    from torchvision.datasets import ImageFolder
    from ultralytics import YOLO
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Preserve existing evaluation; choose new output')
    args.output.mkdir(parents=True)
    model = YOLO(str(args.model), task='classify').model.float().cuda().eval()
    model.model[-1].export = False
    names = ordered_model_names(model.names)
    declared = json.loads((args.data / 'dataset-summary.json').read_text())['class_names']
    if names != declared:
        raise ValueError('Model vocabulary mismatch')
    results = {'model': str(args.model), 'model_sha256': sha256_file(args.model),
               'limitation': 'Synthetic crop stress tests on development split, not independent road or detector validation.',
               'variants': {}}
    for variant in VARIANTS:
        dataset = ImageFolder(str(args.data / 'val'), transform=StressTransform(variant), allow_empty=True)
        if dataset.classes != names:
            raise ValueError('Dataset vocabulary mismatch')
        loader = torch.utils.data.DataLoader(dataset, batch_size=64, num_workers=4)
        metrics = ClassificationMetrics(names)
        errors = []
        offset = 0
        with torch.inference_mode():
            for images, labels in loader:
                raw = model(images.cuda())
                logits = raw[1] if isinstance(raw, tuple) else raw
                if not torch.isfinite(logits).all():
                    raise ValueError('Non-finite predictions')
                scores, predicted = logits.softmax(1).max(1)
                metrics.add(labels.tolist(), predicted.tolist(), scores.tolist(), logits.topk(5, dim=1).indices.tolist())
                for i, (actual, pred, score) in enumerate(zip(labels.tolist(), predicted.tolist(), scores.tolist())):
                    if actual != pred:
                        errors.append({'image': str(Path(dataset.samples[offset+i][0]).relative_to(args.data)),
                                       'truth': names[actual], 'prediction': names[pred], 'score': score})
                offset += len(labels)
        result = metrics.result()
        write_json(args.output / (variant + '-metrics.json'), result)
        write_json(args.output / (variant + '-errors.json'), errors)
        results['variants'][variant] = {'top1_accuracy': result['top1_accuracy'], 'target': result['target']}
        write_json(args.output / 'summary.json', results)
        print(json.dumps({'variant': variant, **results['variants'][variant]}), flush=True)

if __name__ == '__main__':
    main()
