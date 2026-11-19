"""Loopback-only, token-authenticated Firefox owner with cancellable scrape jobs."""
import argparse
import asyncio
from collections import deque
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
import io
import json
from functools import wraps
import os
import secrets
import shutil
import socket
import time
import re
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from src.services.firefox_runtime import ROOT, FirefoxRuntime

LEASE_TIMEOUT_SECONDS = 30
LEASE_POLL_SECONDS = 2


class JobLog(io.TextIOBase):
    def __init__(self, job):
        self.job = job

    def write(self, text):
        if text:
            self.job['sequence'] += 1
            self.job['logs'].append((self.job['sequence'], text))
        return len(text)

    def flush(self):
        pass


def create_app(account, token, runtime=None):
    runtime = runtime or FirefoxRuntime(account)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    job = None
    operation = asyncio.Lock()
    verification = {'page': None, 'ok': False, 'count': None, 'observer': None}
    history_pages = None

    def clear_verification():
        page, observer = verification['page'], verification['observer']
        try:
            if page is not None and observer is not None:
                page.remove_listener('response', observer)
        finally:
            verification.update(page=None, ok=False, count=None, observer=None)

    def snapshot():
        return json.loads((ROOT / 'state' / (account + '.json')).read_text(encoding='utf-8'))

    def idle():
        if operation.locked() or (job and not job['done']):
            raise HTTPException(409, 'Firefox is already running a task')

    def exclusive(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            idle()
            async with operation:
                return await function(*args, **kwargs)
        return wrapped

    @app.middleware('http')
    async def authenticate(request: Request, call_next):
        if not secrets.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + token):
            return JSONResponse({'detail': 'Unauthorized'}, status_code=401)
        return await call_next(request)

    @app.get('/health')
    async def health():
        return {'account': account, 'pid': os.getpid(), 'browser_open': runtime.context is not None,
                'history_detail_version': 1}

    @app.post('/history/detail')
    @exclusive
    async def history_detail(request: Request):
        nonlocal history_pages
        payload=await request.json()
        if not isinstance(payload,dict):raise HTTPException(422,'Invalid verification payload')
        run_id=str(payload.get('run_id',''));item_id=str(payload.get('item_id',''))
        if not re.fullmatch(r'[a-f0-9]{32}',run_id) or not re.fullmatch(r'[0-9]{1,30}',item_id):
            raise HTTPException(422,'Invalid history verification target')
        if verification['page'] is not None or runtime.context is None:
            raise HTTPException(409,'Finish verification and open the existing browser first')
        state=snapshot()
        expected={c['value'] for c in state.get('cookies',[]) if c['name']=='unb'}
        actual={c['value'] for c in await runtime.context.cookies('https://www.goofish.com') if c['name']=='unb'}
        if not expected or expected!=actual:raise HTTPException(409,'Account identity is not verified')
        if history_pages is None:
            from src.services.history_detail import FirefoxHistoryPages
            history_pages=FirefoxHistoryPages(runtime)
        return await history_pages.check(run_id,item_id)

    @app.post('/history/cancel')
    async def history_cancel(request: Request):
        payload=await request.json()
        if not isinstance(payload,dict):raise HTTPException(422,'Invalid verification payload')
        run_id=str(payload.get('run_id',''))
        if not re.fullmatch(r'[a-f0-9]{32}',run_id):raise HTTPException(422,'Invalid verification id')
        if history_pages is not None:await history_pages.close(run_id)
        return {'ok':True}

    @app.post('/prepare')
    @exclusive
    async def prepare():
        if verification['page'] is not None:
            raise HTTPException(409, 'Finish manual verification first')
        state = snapshot()
        context = await runtime.get_context(state)
        cookies = await context.cookies('https://www.goofish.com')
        expected = {c['value'] for c in state['cookies'] if c['name'] == 'unb'}
        actual = {c['value'] for c in cookies if c['name'] == 'unb'}
        await runtime.save_live_state()
        return {'account': account, 'browser': 'firefox', 'identity_matches_saved': bool(expected) and expected == actual,
                'session_cookie_present': any(c['name'] == 'cookie2' and c['value'] for c in cookies)}

    async def execute(current, payload):
        try:
            from src.scraper import scrape_xianyu
            with redirect_stdout(JobLog(current)), redirect_stderr(JobLog(current)):
                current['result'] = await scrape_xianyu(payload['task'], payload.get('debug_limit', 0),
                    _firefox_runtime=runtime, _selected_account=str(ROOT / 'state' / (account + '.json')))
        except asyncio.CancelledError:
            current['error'] = 'Firefox task cancelled'
        except Exception as exc:
            current['error'] = type(exc).__name__ + ': ' + str(exc)
        finally:
            try:
                await runtime.save_live_state()
            except Exception:
                pass
            current['done'] = True

    async def lease(current):
        while not current['done']:
            await asyncio.sleep(LEASE_POLL_SECONDS)
            if time.monotonic() - current['heartbeat'] > LEASE_TIMEOUT_SECONDS:
                current['runner'].cancel()
                return

    @app.post('/run')
    async def run(request: Request):
        nonlocal job
        idle()
        if verification['page'] is not None:
            raise HTTPException(409, 'Finish manual Firefox verification first')
        payload = await request.json()
        idle()
        if not isinstance(payload.get('task'), dict):
            raise HTTPException(400, 'Missing task')
        job = {'id': secrets.token_hex(12), 'done': False, 'result': None, 'error': None,
               'sequence': 0, 'logs': deque(maxlen=4000), 'heartbeat': time.monotonic()}
        job['runner'] = asyncio.create_task(execute(job, payload))
        asyncio.create_task(lease(job))
        return {'job': job['id']}

    def get_job(job_id):
        if not job or job['id'] != job_id:
            raise HTTPException(404, 'Unknown job')
        return job

    @app.get('/jobs/{job_id}')
    async def poll(job_id: str, after: int = 0):
        current = get_job(job_id)
        current['heartbeat'] = time.monotonic()
        return {k: current[k] for k in ('done', 'result', 'error')} | {
            'logs': [(n, line) for n, line in current['logs'] if n > after]}

    @app.post('/jobs/{job_id}/cancel')
    async def cancel(job_id: str):
        current = get_job(job_id)
        if not current['done']:
            current['runner'].cancel()
        return {'ok': True}

    async def search_page():
        from src.services.search_pagination import is_search_results_response
        from src.services.new_listing_policy import validate_search_response
        context = await runtime.get_context(snapshot())
        page = next((p for p in context.pages if p.url.startswith('https://www.goofish.com/')), None)
        page = page or await context.new_page()
        async with page.expect_response(is_search_results_response, timeout=30000) as response:
            await page.goto('https://www.goofish.com/search?' + urlencode({'q': 'aph仏英'}), wait_until='domcontentloaded', timeout=60000)
        payload = await validate_search_response(await response.value, 'Firefox 验证搜索')
        return page, len(payload['data']['resultList'])

    @app.post('/probe')
    @exclusive
    async def probe():
        if verification['page'] is not None:
            raise HTTPException(409, 'Finish manual Firefox verification first')
        try:
            _, count = await search_page()
            await runtime.save_live_state()
            return {'ok': True, 'items': count, 'account': account}
        except Exception as exc:
            return {'ok': False, 'error': type(exc).__name__, 'detail': str(exc)[:400]}

    @app.post('/verify/start')
    @exclusive
    async def verify_start():
        from src.services.search_pagination import is_search_results_response
        from src.services.new_listing_policy import validate_search_response
        context = await runtime.get_context(snapshot())
        old = verification['page']
        clear_verification()
        if old is not None and not old.is_closed():
            await old.close()
        page = await context.new_page()
        verification.update(page=page, ok=False, count=None)
        async def observe(response):
            if verification['page'] is not page or not is_search_results_response(response):
                return
            verification['ok'] = False
            try:
                payload = await validate_search_response(response, 'Firefox 手动验证')
                if verification['page'] is page:
                    verification.update(ok=True, count=len(payload['data']['resultList']))
            except Exception:
                pass
        verification['observer'] = observe
        page.on('response', observe)
        await page.bring_to_front()
        try:
            await page.goto('https://www.goofish.com/search?' + urlencode({'q': 'aph仏英'}), wait_until='domcontentloaded', timeout=60000)
        except Exception:
            pass
        return {'ok': True}

    @app.post('/verify/save')
    @exclusive
    async def verify_save():
        page = verification['page']
        if page is None or page.is_closed() or not verification['ok']:
            return {'ok': False, 'detail': '尚未确认本窗口搜索成功'}
        for selector in ('div.baxia-dialog-mask', 'div.J_MIDDLEWARE_FRAME_WIDGET'):
            if await page.locator(selector).is_visible():
                return {'ok': False, 'detail': '页面仍在验证'}
        state = await runtime.context.storage_state()
        if not any(c['name'] == 'cookie2' and c['value'] for c in state['cookies']):
            return {'ok': False, 'detail': '缺少登录 Cookie'}
        target = ROOT / 'state' / (account + '.json')
        backup = ROOT / 'data/login-backups'
        backup.mkdir(exist_ok=True, parents=True)
        shutil.copy2(target, backup / (account + '-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json'))
        pending = target.with_suffix('.pending')
        pending.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        pending.replace(target)
        runtime.mark_seeded(state)
        await runtime.save_live_state()
        count = verification['count']
        clear_verification()
        return {'ok': True, 'items': count}

    @app.post('/verify/cancel')
    @exclusive
    async def verify_cancel():
        clear_verification()
        return {'ok': True}

    @app.post('/shutdown')
    @exclusive
    async def shutdown():
        if verification['page'] is not None:
            raise HTTPException(409, 'Finish manual verification first')
        await runtime.save_live_state()
        app.state.server.should_exit = True
        return {'ok': True}

    if account == 'private_3' and os.environ.get('FIREFOX_SORT_PROBE_ONCE') == '1':
        sort_probe_used = False

        @app.post('/diagnostics/sort-once')
        @exclusive
        async def sort_once():
            nonlocal sort_probe_used
            if verification['page'] is not None:
                raise HTTPException(409, 'Finish manual verification first')
            if sort_probe_used:
                raise HTTPException(409, 'One-shot sort probe already used')
            sort_probe_used = True
            from src.services.firefox_sort_probe import probe_sort_once
            return await probe_sort_once(runtime, snapshot())

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--account', required=True)
    account = parser.parse_args().account
    os.chdir(ROOT)
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.browsers'))
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from src.services.shared_chrome import browser_for
    if browser_for(account) != 'firefox':
        raise ValueError('Account is not configured for Firefox')
    runtime = FirefoxRuntime(account)
    runtime.profile.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    descriptor = runtime.profile / 'worker.json'
    descriptor.write_text(json.dumps({'port': sock.getsockname()[1], 'token': token, 'pid': os.getpid()}), encoding='utf-8')
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(create_app(account, token, runtime), log_level='warning', access_log=False, loop='asyncio'))
    server.config.app.state.server = server
    async def serve():
        try:
            await server.serve(sockets=[sock])
        finally:
            await runtime.close()
    asyncio.run(serve())


if __name__ == '__main__':
    main()
