"""Standard desktop browser settings for recovery and monitoring."""
from urllib.parse import urlsplit

def desktop_options():
    return {'viewport': {'width': 1365, 'height': 900}, 'locale': 'zh-CN', 'timezone_id': 'Asia/Shanghai'}

def storage_from_snapshot(snapshot):
    state = {'cookies': snapshot.get('cookies', []), 'origins': snapshot.get('origins', [])}
    local = (snapshot.get('storage') or {}).get('local')
    url = urlsplit(snapshot.get('pageUrl', ''))
    if isinstance(local, dict) and url.scheme == 'https' and (url.hostname == 'goofish.com' or (url.hostname or '').endswith('.goofish.com')):
        origin = f'{url.scheme}://{url.netloc}'
        if not any(o.get('origin') == origin for o in state['origins']):
            state['origins'] = list(state['origins']) + [{'origin': origin, 'localStorage': [
                {'name': k, 'value': v} for k, v in local.items() if isinstance(k, str) and isinstance(v, str)]}]
    return state
