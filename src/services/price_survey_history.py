"""Read original local JSON/JSONL without modifying or deleting source files."""
import json
import re
from datetime import datetime
from urllib.parse import urlsplit,parse_qs
from src.infrastructure.persistence.storage_names import normalize_keyword_from_filename


def local_history_records(folder):
    for path in sorted(folder.glob('*')):
        if not path.is_file() or path.suffix.lower() not in ('.json','.jsonl'):continue
        keyword=normalize_keyword_from_filename(path.with_suffix('.jsonl').name)
        if keyword.endswith('.jsonl'):keyword=keyword[:-6]
        stamp=datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec='seconds')
        with path.open(encoding='utf-8-sig') as stream:
            if path.suffix.lower()=='.json':
                try:
                    data=json.load(stream)
                    records=data if isinstance(data,list) else (data.get('items',[]) if isinstance(data,dict) and 'items' in data else [data])
                except (ValueError,TypeError):continue
            else:
                records=[]
                for line in stream:
                    try:records.append(json.loads(line))
                    except ValueError:continue
        for record in records:
            if not isinstance(record,dict):continue
            item=record.get('商品信息',record)
            if not isinstance(item,dict):continue
            item=dict(item);item_id=str(item.get('商品ID') or item.get('item_id') or '')
            if not item_id:
                item_id=parse_qs(urlsplit(str(item.get('商品链接',''))).query).get('id',[''])[0]
            if not re.fullmatch(r'[0-9]{1,30}',item_id):continue
            item['商品ID']=item_id
            item.setdefault('商品标题',str(item.get('title') or ''))
            item.setdefault('当前售价',item.get('price_display') or item.get('price'))
            item['商品链接']='https://www.goofish.com/item?id='+item_id
            yield str(record.get('keyword') or keyword),item,str(path),str(record.get('crawl_time') or stamp)
