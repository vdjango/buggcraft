"""Explicit development-only machine translation import into Qt TS; never runs in launcher/build.
Only public UI strings are submitted. Existing translations remain editable with Qt Linguist.
Unsupported languages are not advertised as translated launcher languages.
"""
import concurrent.futures, copy, json, re, sys, time, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
BASE=ROOT/'assets/i18n'
names=json.loads((BASE/'languages.json').read_text('utf-8'))
template=ET.parse(BASE/'ts/bugg_en_us.ts')
for context in template.findall('context'):
    for message in list(context.findall('message')):
        translation=message.find('translation')
        if translation is not None and translation.get('type') in ('obsolete','vanished'):
            context.remove(message)
sources=list(dict.fromkeys(m.findtext('source','') for m in template.findall('.//message')))
english=json.loads((BASE/'en_us.json').read_text('utf-8'))
overrides={'zh_tw':'zh-TW','zh_hk':'zh-TW','tl_ph':'tl','fil_ph':'fil','no_no':'no','sr_sp':'sr','sr_cs':'sr-Latn','be_latn':'be','eo_uy':'eo','se_no':'se','sah_sah':'sah','zlm_arab':'ms-Arab'}
# Genuine regional variants share their language catalog; invented/dialect locales are not silently mapped.
groups={}
for code in names:
    if code=='zh_cn': continue
    target=overrides.get(code,code.split('_')[0])
    if code in ('en_pt','en_ud','enp','enws','lol_us','got_de','qya_aa','tlh_aa','vp_vl','io_en','jbo_en','lzh','qid','rpr','hal_ua','ry_ua','hn_no','de_at','de_ch','fr_ch','nl_be'): continue
    groups.setdefault(target,[]).append(code)
CACHE=ROOT/'research/translations'
CACHE.mkdir(parents=True,exist_ok=True)

def preserve_file_filter(source, translation):
    """Keep QFileDialog glob patterns literal even when the label is translated."""
    mask=re.search(r'\(\*\.[^)]*\)',source)
    if not mask: return translation
    translated_mask=re.search(r'\([^)]*\)',translation)
    if translated_mask:
        return translation[:translated_mask.start()]+mask.group()+translation[translated_mask.end():]
    return translation.rstrip()+' '+mask.group()

def validated_translation(source, translation):
    if not translation or not translation.strip(): raise ValueError('empty translation: '+source)
    placeholders=lambda value: sorted(re.findall(r'%[1-9n][0-9]?',value))
    if placeholders(source)!=placeholders(translation):
        raise ValueError('placeholder mismatch: '+source)
    return preserve_file_filter(source,translation)

def translate_many(texts,target):
    query=urllib.parse.urlencode({'client':'gtx','sl':'zh-CN','tl':target,'dt':'t','q':'\n'.join(texts)})
    for attempt in range(4):
        try:
            req=urllib.request.Request('https://translate.googleapis.com/translate_a/single?'+query,headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req,timeout=25) as r: value=json.load(r)
            translated=''.join(item[0] or '' for item in value[0])
            lines=translated.split('\n')
            if len(lines)!=len(texts):
                if len(texts)==1: return [translated]
                return [translate_many([s],target)[0] for s in texts]
            return lines
        except urllib.error.HTTPError as e:
            if e.code==400: raise
            if attempt==3: raise
        except Exception:
            if attempt==3: raise
        time.sleep(0.5*(attempt+1))

def catalog(target,codes):
    cache_path=CACHE/(target+'.json')
    cache=json.loads(cache_path.read_text('utf-8')) if cache_path.exists() else {}
    if target=='en': cache.update(english)
    missing=[s for s in sources if s not in cache]
    batch=[];size=0
    batches=[]
    for source in missing:
        if size+len(source.encode('utf-8'))>1100 and batch: batches.append(batch);batch=[];size=0
        batch.append(source);size+=len(source.encode('utf-8'))
    if batch: batches.append(batch)
    try:
        for batch in batches:
            protected=[];maps=[]
            for source in batch:
                placeholders=re.findall(r'%[1-9n][0-9]?',source)
                value=source.replace('\n',' ')
                mapping={}
                for i,token in enumerate(placeholders):
                    marker=f'ZXQPH{i}QXZ';value=value.replace(token,marker,1);mapping[marker]=token
                protected.append(value);maps.append(mapping)
            output=translate_many(protected,target)
            for source,translated,mapping in zip(batch,output,maps):
                for marker,token in mapping.items(): translated=re.sub(re.escape(marker),lambda _:token,translated,flags=re.I)
                if sorted(re.findall(r'%[1-9n][0-9]?',translated))!=sorted(re.findall(r'%[1-9n][0-9]?',source)):
                    translated=translate_many([source],target)[0]
                if sorted(re.findall(r'%[1-9n][0-9]?',translated))!=sorted(re.findall(r'%[1-9n][0-9]?',source)): raise ValueError('placeholder mismatch')
                cache[source]=validated_translation(source,translated)
            cache_path.write_text(json.dumps(cache,ensure_ascii=False,indent=2),'utf-8')
        for code in codes:
            tree=copy.deepcopy(template);tree.getroot().set('language',code)
            tree.getroot().set('sourcelanguage','zh_CN')
            for message in tree.findall('.//message'):
                for location in list(message.findall('location')): message.remove(location)
                translation=message.find('translation')
                source=message.findtext('source','')
                translation.attrib.clear();translation.text=validated_translation(source,cache[source])
            tree.write(BASE/f'ts/bugg_{code}.ts',encoding='utf-8',xml_declaration=True)
        print('OK',target,len(codes),len(cache),flush=True)
        return codes
    except Exception as e:
        print('UNAVAILABLE',target,type(e).__name__,str(e)[:100],flush=True)
        return []

def sync_local():
    """Refresh TS contexts after lupdate using existing locale translations; never contact network."""
    codes=json.loads((BASE/'catalogs.json').read_text('utf-8'))
    for code in codes:
        if code=='zh_cn': continue
        path=BASE/f'ts/bugg_{code}.ts'
        previous=ET.parse(path)
        by_context={};by_source={}
        for context in previous.findall('context'):
            name=context.findtext('name','')
            for message in context.findall('message'):
                source=message.findtext('source','')
                translation=message.find('translation')
                if translation is None or not translation.text: continue
                by_context[name,source]=translation.text
                by_source.setdefault(source,translation.text)
        refreshed=copy.deepcopy(template)
        refreshed.getroot().set('language',code)
        refreshed.getroot().set('sourcelanguage','zh_CN')
        for context in refreshed.findall('context'):
            name=context.findtext('name','')
            for message in context.findall('message'):
                source=message.findtext('source','')
                value=by_context.get((name,source),by_source.get(source))
                if value is None: raise ValueError(f'{code}: missing {name}: {source}')
                for location in list(message.findall('location')): message.remove(location)
                translation=message.find('translation')
                translation.attrib.clear();translation.text=validated_translation(source,value)
        refreshed.write(path,encoding='utf-8',xml_declaration=True)
    print('SYNCED',len(codes)-1,'catalogs',flush=True)

if __name__=='__main__' and '--sync-local' in sys.argv:
    sync_local()
    sys.exit(0)

if __name__=='__main__':
    completed=['zh_cn']
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for result in pool.map(lambda item:catalog(*item),groups.items()): completed.extend(result)
    (BASE/'catalogs.json').write_text(json.dumps(sorted(completed),ensure_ascii=False,separators=(',',':')),'utf-8')
    print('CATALOGS',len(completed),flush=True)
