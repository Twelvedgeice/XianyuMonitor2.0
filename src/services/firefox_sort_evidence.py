"""Allowlisted evidence: no headers, URLs, cookies, titles, sellers or raw payloads."""
import hashlib
import json
import re
from urllib.parse import parse_qs

TIME_LABEL = re.compile(r'(?:\d+(?:分钟|小时|天|周|个月|年)(?:前|内)?(?:发布|上新)|刚刚发布|今天发布|昨天发布|\d{4}[-/]\d{1,2}[-/]\d{1,2})')

def ref(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:12] if value else None

def request_summary(request):
    try:
        raw = request.post_data or ''
        fields = parse_qs(raw)
        data = json.loads(fields['data'][0]) if 'data' in fields else json.loads(raw)
        if isinstance(data.get('data'), str):
            data = json.loads(data['data'])
        result = {'keyword_matches': data.get('keyword') == 'aph仏英'}
        for key in ('sortField','sortValue'):
            value=data.get(key)
            result[key] = value if value in ('','create','modify','price','reduce','pos','credit','desc','asc','credit_desc',None) else 'other'
        for key in ('pageNumber','rowsPerPage'):
            value=data.get(key)
            result[key]=int(value) if str(value).isdigit() else None
        result['fromFilter']=data.get('fromFilter') if isinstance(data.get('fromFilter'),bool) else None
        return result
    except (ValueError,TypeError,KeyError,AttributeError):
        return {'parse_failed':True}

def time_labels(value):
    found=[]
    if isinstance(value,dict):
        for key,item in value.items():
            if key in ('textContent','gradientImageTextContent','content') and isinstance(item,str):
                found.extend(TIME_LABEL.findall(item))
            elif isinstance(item,(dict,list)):
                found.extend(time_labels(item))
    elif isinstance(value,list):
        for item in value:
            found.extend(time_labels(item))
    return list(dict.fromkeys(found))

def numeric_times(value, prefix=''):
    result={}
    if isinstance(value,dict):
        for key,item in value.items():
            path=prefix+'.'+key if prefix else key
            if re.search(r'time|gmt',key,re.I) and str(item).isdigit() and len(str(item)) in (10,13):
                result[path]=int(item)
            elif isinstance(item,(dict,list)):
                result.update(numeric_times(item,path))
    elif isinstance(value,list):
        for index,item in enumerate(value[:50]):
            result.update(numeric_times(item,prefix+'.'+str(index)))
    return result

def payload_summary(payload):
    rows=[]
    for index,item in enumerate(payload.get('data',{}).get('resultList',[])):
        main=item.get('data',{}).get('item',{}).get('main',{})
        content=main.get('exContent',{})
        value=main.get('clickParam',{}).get('args',{}).get('publishTime')
        rows.append({'position':index+1,'item_ref':ref(content.get('itemId')),
                     'parser_publishTime':int(value) if str(value).isdigit() else None,
                     'display_time_labels':time_labels(content.get('fishTags',{})),
                     'time_fields':numeric_times(item)})
    inversions=[]
    for previous,current in zip(rows,rows[1:]):
        a,b=previous['parser_publishTime'],current['parser_publishTime']
        if a is not None and b is not None and a<b:
            inversions.append({'positions':[previous['position'],current['position']],
                               'later_by_seconds':(b-a)/(1000 if len(str(b))==13 else 1)})
    return {'rows':rows,'inversions':inversions}

async def page_summary(page):
    # Only item IDs (hashed below) and publication labels leave this DOM read.
    cards=await page.locator('a[href]').evaluate_all('''elements => elements.flatMap(a => {
        const u = new URL(a.href, location.href);
        const id = u.pathname === '/item' ? u.searchParams.get('id') : null;
        if (!id || a.getClientRects().length === 0) return [];
        const labels = (a.innerText || '').match(/(?:\\d+(?:分钟|小时|天|周|个月|年)(?:前|内)?(?:发布|上新)|刚刚发布|今天发布|昨天发布)/g) || [];
        return [{id,labels}];
    })''')
    return [{'item_ref':ref(card['id']),'display_time_labels':card['labels']} for card in cards]
