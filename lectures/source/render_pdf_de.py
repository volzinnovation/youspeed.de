from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import shutil
import json
import subprocess
root=Path(__file__).resolve().parents[1]
output=root/'output/ki-intelligente-mobilitaet-2026-10-19-de.pdf'
pages=sorted((root/'.build/de/final-renders').glob('slide-*.png'))
assert len(pages)==42,len(pages)
node='/Users/raphaelvolz/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
source_url=(root/'source/slides-de.mjs').as_uri()
slide_data=json.loads(subprocess.check_output([node,'--input-type=module','-e',f'import {{slides}} from {json.dumps(source_url)}; console.log(JSON.stringify(slides));'],text=True))
assert len(slide_data)==len(pages)
def add_links(c,d):
    links=[]
    if d['type']=='website':
        links=[(label,url,64+j*540,600,528,44) for j,(label,url) in enumerate(d.get('links',[]))]
    elif d['type']=='tags':
        label,url=d['links'][0]
        links=[(label,url+'?signs=DE:274-50',564,597,652,44)]
    elif d['type']=='wide' and d.get('links'):
        links=[(label,url,64,622,800,44) for label,url in d['links']]
    elif d['type']=='install':
        links=[(label,url,64+j*365,580,340,44) for j,(label,url) in enumerate(d.get('links',[]))]
    for _,url,x,y,w,h in links:
        c.linkURL(url,(x*.75,(720-y-h)*.75,(x+w)*.75,(720-y)*.75),relative=0,thickness=0)

c=canvas.Canvas(str(output),pagesize=(960,540))
c.setTitle('KI für intelligente Mobilität')
c.setAuthor('Prof. Dr. Raphael Volz')
c.setSubject('Profilprojekt IMo WS27-28 HSPF')
for p,d in zip(pages,slide_data):
    c.drawImage(ImageReader(str(p)),0,0,width=960,height=540)
    add_links(c,d)
    c.showPage()
c.save()
shutil.copy2(output,root/'output/youspeed-lecture-2026-10-19.pdf')
print(output)
