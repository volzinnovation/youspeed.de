/* Shared read-only presentation. No tariffs are defined in this file. */
(function (scope) {
  'use strict';
  const aliases = {
    country_code: 'land_code', country_name: 'land_name', currency_code: 'waehrung_code',
    bands: 'stufen', min_delta_kmh: 'min_ueber_kmh', max_delta_kmh: 'max_ueber_kmh',
    money_fine_eur: 'geldbusse_eur', penalty_points: 'punkte', driving_ban_months: 'fahrverbot_monate',
    conditional_driving_ban_months: 'bedingtes_fahrverbot_monate', driving_ban_condition: 'fahrverbot_bedingung',
    locality_variants: 'ortsvarianten', source_url: 'quelle_url', source_checked_at: 'quelle_geprueft_am'
  };
  function field(object, key) {
    if (Object.prototype.hasOwnProperty.call(object, key)) return object[key];
    return aliases[key] ? object[aliases[key]] : undefined;
  }
  function categories(rules) {
    if (rules.speeding_tariffs) {
      const keys = ['urban','urban_30','urban_15','rural','motorway'].filter(key => rules.speeding_tariffs.road_categories[key]);
      if (rules.speeding_tariffs.motorway_130_minimum_delta_kmh != null) keys.push('motorway_130');
      return keys;
    }
    const bands = field(rules, 'bands') || [];
    if (bands.some(b => b.posted_limit_variants)) return [...new Set(bands.flatMap(b => Object.keys(b.posted_limit_variants || {})))].sort((a,b)=>['at_most_50','above_50'].indexOf(a)-['at_most_50','above_50'].indexOf(b));
    const variants = bands.flatMap(b => Object.keys(field(b, 'locality_variants') || {}).map(k => ({innerorts:'urban', ausserorts:'rural', 'außerorts':'rural'})[k] || k));
    return variants.length ? ['urban','rural','motorway'].filter(key => variants.includes(key)).concat([...new Set(variants)].filter(key => !['urban','rural','motorway'].includes(key)).sort()) : ['general'];
  }
  function rows(rules, context) {
    if (rules.speeding_tariffs) {
      const tariff = rules.speeding_tariffs;
      const category = tariff.road_categories[context === 'motorway_130' ? 'motorway' : context];
      if (!category) return [];
      const minimum = context === 'motorway_130' ? tariff.motorway_130_minimum_delta_kmh : tariff.minimum_delta_kmh;
      const output = Object.entries(category.fines_eur).map(([delta, fine]) => ({min:Number(delta), max:Number(delta), fine, points:null, ban:null, conditional:null, condition:null}))
        .filter(row => row.min >= minimum).sort((a,b) => a.min-b.min);
      output.push({min:category.criminal_from_delta_kmh, max:null, fine:null, points:null, ban:null, conditional:null, condition:'criminal'});
      return output;
    }
    return (field(rules, 'bands') || []).map(band => {
      const variants = field(band, 'locality_variants') || {};
      const variant = band.posted_limit_variants?.[context] || variants[context] || variants[({urban:'innerorts', rural:'ausserorts'})[context]] || variants[context === 'rural' ? 'außerorts' : ''] || {};
      const value = key => field(variant, key) ?? field(band, key) ?? null;
      return {min:field(band,'min_delta_kmh'), max:field(band,'max_delta_kmh') ?? null,
        fine:value('money_fine_eur'), points:value('penalty_points'), ban:value('driving_ban_months'),
        conditional:value('conditional_driving_ban_months'), condition:value('driving_ban_condition') || band.enforcement_class || null};
    });
  }
  const api = {field, categories, rows};
  if (typeof module !== 'undefined') module.exports = api;
  scope.PenaltyDocumentation = api;
  if (typeof document === 'undefined') return;
  const config = scope.penaltyDocumentationInput;
  const locale = (config.locale || 'en').replace('_','-');
  const lang = locale.split('-')[0];
  const t = config.translations[lang] || config.translations.en;
  document.documentElement.lang = locale;
  document.title = t.title;
  const el = (tag, text, className) => { const node = document.createElement(tag); if (text != null) node.textContent = text; if (className) node.className=className; return node; };
  const main = document.getElementById('content');
  main.append(el('h1', t.title), el('p',t.disclaimer,'notice'),el('p',t.estimates,'intro'));
  const countryLabel = el('label',t.country); const countrySelect=el('select'); countrySelect.id='country';countryLabel.append(countrySelect);main.append(countryLabel);
  const contextLabel = el('label',t.context); const contextSelect=el('select');contextSelect.id='context';contextLabel.append(contextSelect);main.append(contextLabel);
  const output=el('section');output.id='lookup';main.append(output);
  const alpha2={DEU:'DE',FRA:'FR',CHE:'CH',BEL:'BE',NLD:'NL',GBR:'GB',LUX:'LU',LIE:'LI',MCO:'MC',ROU:'RO',SWE:'SE',ISL:'IS'};
  const names = typeof Intl.DisplayNames === 'function' ? new Intl.DisplayNames([locale],{type:'region'}) : null;
  const entries=config.documents.map(rules=>({rules,code:field(rules,'country_code')})).map(item=>({...item,name:names && alpha2[item.code] ? names.of(alpha2[item.code]) : field(item.rules,'country_name') || item.code})).sort((a,b)=>a.name.localeCompare(b.name,locale));
  for(const item of entries){const option=el('option',item.name);option.value=item.code;countrySelect.append(option);}
  countrySelect.value=entries.some(item=>item.code===config.activeCountry)?config.activeCountry:entries[0]?.code || '';
  function categoryTitle(key){return key==='motorway_130' ? t.motorway+' · 130 km/h' : t[key] || key;}
  function updateContexts(){contextSelect.replaceChildren();const rules=entries.find(item=>item.code===countrySelect.value)?.rules;if(!rules)return;for(const key of categories(rules)){const option=el('option',categoryTitle(key));option.value=key;contextSelect.append(option);}render();}
  function cell(value){return value==null?t.unspecified:String(value);}
  function months(value){const category=new Intl.PluralRules(locale).select(Number(value));return cell(value)+' '+(category==='one'?t.month_one:category==='few'?t.months:t.month_other);}
  function makeTable(headers, values){const table=el('table');const head=el('thead');const tr=el('tr');for(const title of headers) {const th=el('th',title);th.scope='col';tr.append(th);}head.append(tr);table.append(head);const body=el('tbody');for(const cells of values){const row=el('tr');cells.forEach((value,index)=>{const node=el(index===0?'th':'td',value);if(index===0)node.scope='row';row.append(node);});body.append(row);}table.append(body);const scroll=el('div',null,'table-scroll');scroll.tabIndex=0;scroll.append(table);return scroll;}
  function render(){output.replaceChildren();const item=entries.find(item=>item.code===countrySelect.value);if(!item)return;const rules=item.rules,context=contextSelect.value,currency=field(rules,'currency_code') || '';
    output.append(el('h2',item.name+' · '+categoryTitle(context)));
    const tariff=rules.speeding_tariffs;
    if(tariff){const minimum=context==='motorway_130'?tariff.motorway_130_minimum_delta_kmh:tariff.minimum_delta_kmh;output.append(el('p',(context==='motorway_130'?t.motorway130:t.threshold)+': +'+minimum+' km/h'),el('p',t.fee+': '+tariff.administrative_fee_eur+' '+currency));}
    const display=rows(rules,context).map(row=>{
      const range=row.max==null?'≥'+row.min:row.min===row.max?'+'+row.min:'+'+row.min+'–'+row.max;
      const minimum=row.condition==='first_offence_minimum_withdrawal';
      let ban=row.ban==null?t.unspecified:(minimum?'≥':'')+months(row.ban);
      if(row.conditional!=null)ban+=' · '+t.conditional+': '+months(row.conditional);
      if(row.condition && t[row.condition])ban+=' · '+t[row.condition];
      return [range,cell(row.fine),cell(row.points),ban];
    });
    output.append(makeTable([t.excess,t.fine+' ('+currency+')',t.points,t.ban],display));
    const escalation=rules.posted_limit_escalation;
    if(escalation){output.append(el('h2',t.thresholds));let lower=0;const thresholdRows=escalation.thresholds.map(row=>{const limit=row.max_posted_limit_kmh==null?'>'+lower:lower===0?'≤'+row.max_posted_limit_kmh:(lower+1)+'–'+row.max_posted_limit_kmh;lower=row.max_posted_limit_kmh ?? lower;return [limit,'≥'+row.min_delta_kmh,(escalation.driving_ban_condition==='raser_standard_minimum_with_statutory_exceptions'?'≥':'')+months(escalation.driving_ban_months),t.qualifying_statutory_exception+': '+(escalation.driving_ban_condition==='raser_standard_minimum_with_statutory_exceptions'?'≥':'')+months(escalation.conditional_driving_ban_months)];});output.append(makeTable([t.limit,t.minimum,t.ban,t.exception],thresholdRows));}
    const source=field(rules,'source_url');if(source && /^https?:\/\//.test(source)){const a=el('a',t.source);a.href=source;a.rel='noopener noreferrer';const paragraph=el('p');paragraph.append(a);output.append(paragraph);}
    const checked=field(rules,'source_checked_at');if(checked)output.append(el('p',t.checked+': '+checked,'reviewed'));
  }
  countrySelect.addEventListener('change',updateContexts);contextSelect.addEventListener('change',render);updateContexts();
})(typeof globalThis!=='undefined'?globalThis:this);
