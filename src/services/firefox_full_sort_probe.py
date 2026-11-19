"""Run the real collector through sorting, then stop before item processing.

One-shot worker lock owns this temporary instrumentation. Scheduling, account
selection, retries, notifications and failure records are outside this probe.
"""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

from src.services.firefox_click_probe import safe_error
from src.services.firefox_sort_evidence import request_summary, payload_summary, page_summary
from src.services.new_listing_policy import validate_search_response

ROOT=Path(__file__).resolve().parents[2]

class _BoundaryReached(BaseException):
    pass

class _SafeLog(io.TextIOBase):
    def __init__(self, entries): self.entries=entries
    def write(self, text):
        for line in text.splitlines():
            if '[Firefox排序]' in line or '[筛选响应]' in line:
                self.entries.append(line)
        return len(text)
    def flush(self): pass

def _load_task():
    from src.infrastructure.persistence.sqlite_task_repository import _row_to_task
    with sqlite3.connect((ROOT/'data/app.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM tasks WHERE id=0').fetchone()
    if row is None: raise RuntimeError('Reference task missing')
    return _row_to_task(row).model_dump()

async def probe_full_sort(runtime,snapshot):
    import src.scraper as scraper
    import src.services.firefox_sort as sorter
    assert runtime.account=='private_3'
    task=_load_task()
    result={'ok':False,'mode':'real_collector_through_sort','cases':[]}
    context=await runtime.get_context(snapshot)
    original_pages=set(context.pages)
    if any('www.goofish.com' in page.url for page in original_pages):
        return {**result,'error':'existing_search_page_not_owned_by_probe'}
    original_sort=sorter.apply_firefox_publish_sort
    try:
        for name in ('fresh_collector_page','reused_collector_page'):
            case={'name':name,'ok':False,'logs':[],
                  'existing_search_page':any('www.goofish.com' in p.url for p in context.pages)}
            result['cases'].append(case)
            async def capture(page,option,**kwargs):
                try:
                    response=await original_sort(page,option,**kwargs)
                    payload=await validate_search_response(response,'完整采集排序验证')
                    request=request_summary(response.request)
                    selected=payload_summary(payload)
                    rendered=await page_summary(page)
                    same=[r['item_ref'] for r in selected['rows']]==[r['item_ref'] for r in rendered]
                    case.update(http=response.status,request=request,items=len(selected['rows']),
                        dom_equals_response_order=same,sort_function_completed=True,
                        ok=request.get('sortField')=='create' and request.get('sortValue')=='desc' and same)
                except Exception as exc:
                    case['error']=safe_error(exc)
                raise _BoundaryReached()
            async def once(operation,**kwargs):
                try: await operation()
                except _BoundaryReached: raise
                except Exception as exc: case['error']=safe_error(exc)
                raise _BoundaryReached()
            async def forbidden(*args,**kwargs):
                case['error']='unexpected_side_effect_blocked'
                raise _BoundaryReached()
            with ExitStack() as stack:
                stack.enter_context(patch.object(sorter,'apply_firefox_publish_sort',capture))
                stack.enter_context(patch.object(scraper,'retry_collection',once))
                stack.enter_context(patch.object(scraper,'AccountFailover',lambda **kwargs:SimpleNamespace()))
                stack.enter_context(patch.object(scraper,'FAILURE_GUARD',SimpleNamespace(
                    should_skip_start=lambda *args,**kwargs:SimpleNamespace(skip=False))))
                stack.enter_context(patch.object(scraper,'send_ntfy_notification',forbidden))
                stack.enter_context(patch.object(scraper,'handle_account_success',forbidden))
                stack.enter_context(patch.object(scraper,'handle_verification_failure',forbidden))
                log=_SafeLog(case['logs'])
                stack.enter_context(redirect_stdout(log));stack.enter_context(redirect_stderr(log))
                try:
                    await scraper.scrape_xianyu(task,0,_firefox_runtime=runtime,
                        _selected_account=str(ROOT/'state/private_3.json'))
                except _BoundaryReached: pass
            if not case['ok']: break
        result['ok']=len(result['cases'])==2 and all(case['ok'] for case in result['cases'])
    except Exception as exc:
        result['error']=safe_error(exc)
    finally:
        for page in list(context.pages):
            if page not in original_pages: await page.close()
        result['owned_pages_closed']=True
    return result
