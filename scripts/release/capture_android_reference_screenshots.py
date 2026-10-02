#!/usr/bin/env python3
"""Capture native country references on the store emulator; no production data changes."""
import argparse,json,pathlib,re,subprocess,time,xml.etree.ElementTree as ET
ROOT=pathlib.Path(__file__).resolve().parents[2]
LOCALES=['en-US','fr-FR','de-DE','nl-NL','es-ES','it-IT','pl-PL','pt-BR','sv-SE']
COUNTRIES={'signs':['DE','FR','NL','BE','CH'],'penalties':['DEU','FRA','CHE','BEL','NLD','GBR','LUX','LIE','MCO','ROU','SWE','ISL']}
PACKAGE='de.youspeed.android.debug'
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--serial',default='emulator-5554');parser.add_argument('--output',type=pathlib.Path,default=ROOT/'store/reference-screenshots/android');parser.add_argument('--locales',nargs='+',default=LOCALES);args=parser.parse_args()
 if not args.serial.startswith('emulator-'):raise SystemExit('Use an emulator; this capture command changes its logical display size.')
 adb=['adb','-s',args.serial]
 def run(*items):return subprocess.check_output(adb+list(items),text=True)
 def tree():
  for attempt in range(4):
   try:run('shell','uiautomator','dump','/sdcard/youspeed-reference.xml');return ET.fromstring(run('exec-out','cat','/sdcard/youspeed-reference.xml'))
   except subprocess.CalledProcessError:time.sleep(1)
  raise RuntimeError('Unable to read emulator UI')
 def tap(node):
  x1,y1,x2,y2=map(int,re.findall(r'\d+',node.get('bounds')));run('shell','input','tap',str((x1+x2)//2),str((y1+y2)//2))
 old_locale=re.search(r'\[(.*?)\]',run('shell','cmd','locale','get-app-locales',PACKAGE)).group(1)
 old_size=run('shell','wm','size');override=re.search(r'Override size: (\d+x\d+)',old_size)
 labels=json.loads((ROOT/'shared/traffic-sign-documentation/translations.json').read_text());fine=json.loads((ROOT/'shared/penalty-documentation/translations.json').read_text());records=[]
 run('shell','wm','size','1080x1920')
 try:
  for locale in args.locales:
   language=locale.split('-')[0];run('shell',f"cmd locale set-app-locales {PACKAGE} --locales '{locale}'")
   for kind,countries in COUNTRIES.items():
    for country in countries:
     output=args.output/locale/kind/(country+'.png');output.parent.mkdir(parents=True,exist_ok=True)
     if output.exists():continue
     run('shell','am','force-stop',PACKAGE)
     run('shell','am','start','-W','-n',PACKAGE+'/de.youspeed.android.alpha.MainActivity','--es','screenshot_state','camera-limit-active','--es','screenshot_reference_country',country)
     current=tree();buttons=[n for n in current.iter('node') if n.get('clickable')=='true' and int(re.findall(r'\d+',n.get('bounds'))[1])>1700];assert len(buttons)==6;tap(buttons[4])
     title=labels[language]['title'] if kind=='signs' else fine[language]['title']
     for attempt in range(12):
      current=tree();reference=next((n for n in current.iter('node') if n.get('text')==title),None)
      if reference is not None:tap(reference);break
      time.sleep(.5)
     else:raise RuntimeError(f'Info menu did not load: {locale}/{kind}/{country}')
     for attempt in range(12):
      current=tree()
      if any(n.get('resource-id')=='country' for n in current.iter('node')):break
     else:raise RuntimeError(f'Reference did not load: {locale}/{kind}/{country}')
     # Scroll within the web content to show the first sign's names or fine rows.
     run('shell','input','swipe','540','1600','540','950','450');current=tree()
     data=subprocess.check_output(adb+['exec-out','screencap','-p']);output.write_bytes(data)
     xml=ET.tostring(current,encoding='unicode');output.with_suffix('.xml').write_text(xml)
     records.append({'locale':locale,'kind':kind,'country':country,'path':str(output.relative_to(ROOT)),'bytes':len(data)})
     print(f'{locale} {kind} {country}',flush=True)
 finally:
  run('shell',f"cmd locale set-app-locales {PACKAGE} --locales '{old_locale}'")
  run('shell','wm','size',override.group(1) if override else 'reset')
  records=[{'locale':p.parents[1].name,'kind':p.parent.name,'country':p.stem,'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size} for p in sorted(args.output.glob('*/*/*.png'))]
  (args.output/'capture-report.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
