"""Opt-in local publish-time cutoff for new-listing notifications."""
import json
import re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo


class SearchResponseError(RuntimeError):
    """Search failed; never continue applying filters to this response."""


class SearchVerificationError(SearchResponseError):
    """The server requires user verification; do not retry this attempt."""


async def validate_search_response(response, stage):
    try:
        if not response.ok:
            raise SearchResponseError(f"搜索 HTTP 错误：{response.status}")
        payload = await response.json()
    except SearchResponseError as exc:
        raise SearchResponseError(f"{stage}: {exc}") from exc
    except Exception as exc:
        raise SearchResponseError(f"{stage}: 搜索响应无法解析") from exc
    try:
        validate_search_payload(payload)
    except SearchResponseError as exc:
        raise type(exc)(f"{stage}: {exc}") from exc
    return payload


def validate_search_payload(payload):
    raw_codes = payload.get('ret', []) if isinstance(payload, dict) else []
    codes = [str(value).split('::', 1)[0] for value in raw_codes] if isinstance(raw_codes, list) else []
    safe_codes = [code for code in codes if re.fullmatch(r'[A-Z0-9_]+', code)]
    if any(code != 'SUCCESS' for code in codes):
        error = SearchVerificationError if any('VALIDATE' in code or code.startswith('RGV') for code in safe_codes) else SearchResponseError
        raise error('搜索接口未成功：' + ','.join(safe_codes or ['UNKNOWN']))
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get('resultList'), list):
        raise SearchResponseError('搜索接口没有返回有效商品列表，不能判定为没有新商品。')


def load_cutoff(task_name):
    path = Path('data/new-listing-policy.json')
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding='utf-8')).get(task_name)


def is_new_listing(item, cutoff):
    if cutoff is None:
        return True
    try:
        raw = item.get('发布时间戳')
        if raw is not None:
            published = float(raw) / 1000
        else:
            published = datetime.strptime(item['发布时间'], '%Y-%m-%d %H:%M').replace(
                tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
        return published >= float(cutoff)
    except (KeyError, ValueError, TypeError, OverflowError):
        return False
