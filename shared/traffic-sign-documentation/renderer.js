/* Read-only catalogue presentation: artwork, labels and speech come from shared JSON. */
(function(scope){
  'use strict';
  const languages=['en','fr','de','nl'];
  function signs(catalog, query='') {
    const words=query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    const entries=catalog.signs.filter(sign=>sign.display_eligible===true && typeof sign.image_path==='string' && sign.sign_code)
      .filter(sign=>words.every(word=>[sign.sign_code,...Object.values(sign.label||{}),...Object.values(sign.speech||{})].join(' ').toLocaleLowerCase().includes(word)))
      .sort((a,b)=>a.sign_code.localeCompare(b.sign_code,'en',{numeric:true}) || a.class_id.localeCompare(b.class_id,'en'));
    // Several model classes can describe the same national sign. Show it once,
    // retaining the existing reviewed speech rather than a silent reference alias.
    const unique=new Map();
    for(const sign of entries){const previous=unique.get(sign.sign_code);const score=item=>languages.filter(language=>spoken(item,language)).length;if(!previous || score(sign)>score(previous))unique.set(sign.sign_code,sign);}
    return [...unique.values()];
  }
  function spoken(sign,language){return sign.speech?.[language]?.trim() || null;}
  const api={signs,spoken,languages};
  if(typeof module!=='undefined')module.exports=api;
  scope.TrafficSignDocumentation=api;
  if(typeof document==='undefined')return;
  const input=scope.trafficSignDocumentationInput,locale=(input.locale||'en').replace('_','-'),lang=locale.split('-')[0];
  const t=input.translations[lang]||input.translations.en,p=input.commonTranslations[lang]||input.commonTranslations.en;
  document.documentElement.lang=locale;document.title=t.title;
  const el=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;return node;};
  const main=document.getElementById('content');main.append(el('h1',t.title));
  const note=el('p',p.disclaimer);note.className='notice';main.append(note,el('p',t.reference));
  const countryLabel=el('label',p.country),country=el('select');country.id='country';countryLabel.append(country);main.append(countryLabel);
  const names=new Intl.DisplayNames([locale],{type:'region'});
  const catalogs=input.catalogs.slice().sort((a,b)=>names.of(a.country).localeCompare(names.of(b.country),locale));
  for(const catalog of catalogs){const option=el('option',names.of(catalog.country));option.value=catalog.country;country.append(option);}
  country.value=catalogs.some(c=>c.country===input.activeCountry)?input.activeCountry:'DE';
  const searchLabel=el('label',t.search),search=el('input');search.type='search';search.id='search';search.className='search';searchLabel.append(search);main.append(searchLabel);
  const count=el('p');count.className='count';count.setAttribute('aria-live','polite');main.append(count);
  const cards=el('section');cards.className='cards';cards.id='signs';main.append(cards);
  const languageNames={de:'Deutsch',en:'English',fr:'Français',nl:'Nederlands'};
  function render(){cards.replaceChildren();const catalog=catalogs.find(c=>c.country===country.value),entries=signs(catalog,search.value);count.textContent=names.of(country.value)+' · '+entries.length;
    for(const sign of entries){const card=el('article');card.className='sign';const image=el('img');image.src=input.images[sign.image_path];image.alt=sign.label?.[lang]||sign.label?.en||sign.sign_code;image.loading='lazy';image.width=104;image.height=104;
      card.append(image,el('h2',sign.label?.[lang]||sign.label?.en||sign.sign_code),el('code',sign.sign_code));
      const list=el('dl');list.setAttribute('aria-label',t.spoken);
      for(const language of languages){const phrase=spoken(sign,language),value=el('dd',phrase||t.silent);value.lang=phrase?language:locale;list.append(el('dt',languageNames[language]),value);}
      card.append(list);cards.append(card);
    }
  }
  country.addEventListener('change',()=>{search.value='';render();});search.addEventListener('input',render);search.addEventListener('keydown',event=>{if(event.key==='Enter')search.blur();});render();
})(typeof globalThis!=='undefined'?globalThis:this);
