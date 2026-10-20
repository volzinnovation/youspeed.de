from pathlib import Path
import json
import os
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader

root = Path(__file__).resolve().parents[1]
revision = os.environ.get('LECTURE_REVISION', 'v9.1')
work = root / '.build' / revision
data = json.loads((work / 'slides.json').read_text())
pages = sorted((work / 'final-renders').glob('slide-*.png'))
assert len(pages) == len(data['slides']) == 27
output = root / f'output/tsr-sgblur-de-2026-10-26-{revision}.pdf'
c = canvas.Canvas(str(output), pagesize=(960, 540))
c.setTitle(data['meta']['title'] + ' — ' + data['meta']['subtitle'])
c.setAuthor('Prof. Dr. Raphael Volz')
c.setSubject('26. Oktober 2026 · 45 Minuten · Fine-Tuning, Precision, Recall und F1 mit TSR, SGBlur und Panoramax')
for page, slide in zip(pages, data['slides']):
    c.drawImage(ImageReader(str(page)), 0, 0, width=960, height=540)
    # Keep source references usable even though the visual slides are rasterized.
    c.bookmarkPage('slide-' + str(c.getPageNumber()))
    c.addOutlineEntry(slide['title'], 'slide-' + str(c.getPageNumber()), level=0)
    if slide['type'] == 'modelTable':
        for j, (label, url) in enumerate(slide.get('links', [])):
            c.linkURL(url, ((64+j*602)*.75, (720-526)*.75, (614+j*602)*.75, (720-486)*.75), relative=0, thickness=0)
    if slide['type'] in ('cnn', 'yolo') and slide.get('links'):
        y = 592 if slide['type'] == 'cnn' else 662
        c.linkURL(slide['links'][0][1], (48, (720-y-40)*.75, 900, (720-y)*.75), relative=0, thickness=0)
    if slide['type'] == 'sgblur':
        for j, origin in enumerate(slide.get('origins', [])):
            c.linkURL(origin['url'], ((64+j*602)*.75, (720-571)*.75, (614+j*602)*.75, (720-531)*.75), relative=0, thickness=0)
    if slide['type'] == 'failureComparison':
        c.linkURL(slide['sources'][0], (48, 146, 460.5, 352.5), relative=0, thickness=0)
    if slide['type'] == 'annotation':
        c.linkURL(slide['sources'][0], (48, 85, 618, 414), relative=0, thickness=0)
    if slide['type'] == 'datasets' and slide.get('datasetUrl'):
        c.linkURL(slide['datasetUrl'], (48, 18, 912, 61.5), relative=0, thickness=0)
    if slide['type'] == 'serverDownload':
        c.linkURL(slide['datasetUrl'], (48, 378, 912, 408), relative=0, thickness=0)
    if slide['type'] == 'fineTuning':
        c.linkURL(slide['modelUrl'], (48, (720-314)*.75, 912, (720-274)*.75), relative=0, thickness=0)
    if slide['type'] == 'failure' and slide.get('links'):
        for j, (label, url) in enumerate(slide['links']):
            y = 548 + j*42
            c.linkURL(url, (584*.75, (720-y-40)*.75, 1216*.75, (720-y)*.75), relative=0, thickness=0)
    if slide['type'] == 'dataAndModel':
        for j, column in enumerate(slide['columns']):
            x = 64 + j*602
            c.linkURL(column['url'], (x*.75, (720-290)*.75, (x+550)*.75, (720-250)*.75), relative=0, thickness=0)
    c.showPage()
c.save()
reader = PdfReader(str(output))
assert len(reader.pages) == 27
assert all(abs(float(p.mediabox.width)-960) < 0.01 and abs(float(p.mediabox.height)-540) < 0.01 for p in reader.pages)
print(output)
