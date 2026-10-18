"""Portable PDF companion using the exact slide renders; PPTX stays editable."""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

root = Path(__file__).resolve().parents[1]
output = root / 'output/youspeed-lecture-2026-10-19.pdf'
c = canvas.Canvas(str(output), pagesize=(960, 540))
c.setTitle('YouSpeed.de — 19 October 2026')
c.setAuthor('YouSpeed project lecture')
render_root = root / '.build/final-renders'
if not render_root.exists():
    render_root = root / '.build/renders'
images = sorted(render_root.glob('slide-*.png'))
assert len(images) == 36, len(images)
for image in images:
    c.drawImage(ImageReader(str(image)), 0, 0, width=960, height=540)
    c.showPage()
c.save()
print(output)
