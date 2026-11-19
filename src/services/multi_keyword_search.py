"""Search coverage and task-wide item identity; no browser or scheduling effects."""
import json
from urllib.parse import parse_qs, urlparse


def search_keywords(task):
    values = [task['keyword']]
    if not task.get('_price_survey'):
        values.extend(task.get('keyword_rules') or [])
    return list(dict.fromkeys(v.strip() for v in values if isinstance(v, str) and v.strip()))


def item_identity(item):
    value = item.get('商品ID')
    if value is not None and str(value).strip():
        return str(value).strip()
    return link_identity(item.get('商品链接', ''))


def link_identity(link):
    return parse_qs(urlparse(str(link)).query).get('id', [None])[0]


def matches_keyword(response, keyword):
    from src.services.search_pagination import is_search_results_response
    if not is_search_results_response(response):
        return False
    try:
        raw = response.request.post_data or ''
        fields = parse_qs(raw)
        data = json.loads(fields['data'][0]) if 'data' in fields else json.loads(raw)
        if isinstance(data.get('data'), str):
            data = json.loads(data['data'])
        return data.get('keyword') == keyword
    except (ValueError, TypeError, KeyError, AttributeError):
        return False
