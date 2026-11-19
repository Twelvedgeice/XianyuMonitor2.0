"""A persistent Firefox owner; scheduler children connect to the owner, not CDP."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
from playwright.async_api import async_playwright
from src.failure_guard import _FileLock
from src.services.local_browser import storage_from_snapshot

ROOT = Path(__file__).resolve().parents[2]


def profile_for(account):
    if not account or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in account):
        raise ValueError('Invalid Firefox account name')
    return ROOT / 'data' / ('firefox-' + account)


def fingerprint(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class FirefoxRuntime:
    def __init__(self, account):
        self.account = account
        self.profile = profile_for(account)
        self.playwright = None
        self.context = None
        self.seeded = None
        self._context_lock = asyncio.Lock()

    async def get_context(self, snapshot):
        # Serialize startup and login seeding so overlapping callers cannot open
        # the same persistent profile in two Firefox processes.
        async with self._context_lock:
            return await self._get_context(snapshot)

    async def _get_context(self, snapshot):
        if self.playwright is None:
            self.playwright = await async_playwright().start()
        if self.context is None:
            from src.services.firefox_profile import prepare_background_rendering
            prepare_background_rendering(self.account, self.profile)
            self.profile.mkdir(parents=True, exist_ok=True)
            try:
                context = await self.playwright.firefox.launch_persistent_context(
                    str(self.profile / 'profile'), headless=False, no_viewport=True, timeout=45000,
                    env={**os.environ, 'MOZ_DISABLE_SAFE_MODE_KEY': '1'})
            except BaseException:
                # No extra launch here: the existing account retry budget owns
                # retries. Its next attempt must get a fresh Playwright driver.
                driver, self.playwright = self.playwright, None
                self.context = None
                self.seeded = None
                try:
                    await driver.stop()
                except Exception:
                    print("Firefox 启动失败后的连接清理未完成；下一次尝试将重新建立连接。")
                raise
            self.context = context
            context.on('close', lambda: setattr(self, 'context', None))
            # Session cookies may disappear when the process closes. Always seed a
            # new context, preferring the last live state for the same imported file.
            self.seeded = None
        current = fingerprint(snapshot)
        if self.seeded != current:
            state = storage_from_snapshot(snapshot)
            if self.seeded is None:
                try:
                    live = json.loads((self.profile / 'live-state.json').read_text(encoding='utf-8'))
                    if live.get('source_fingerprint') == current:
                        state = storage_from_snapshot(live['state'])
                except (OSError, ValueError, KeyError):
                    pass
            await self.context.clear_cookies()
            await self.context.add_cookies(state['cookies'])
            page = await self.context.new_page()
            try:
                for origin in state['origins']:
                    if origin.get('origin') not in ('https://www.goofish.com', 'https://passport.goofish.com'):
                        continue
                    # Seed storage without making an authenticated network request.
                    url = origin['origin'] + '/'
                    await page.route(url, lambda route: route.fulfill(status=200, body='<html></html>'))
                    await page.goto(url)
                    await page.evaluate('items => {localStorage.clear(); for (const x of items) localStorage.setItem(x.name,x.value);}', origin.get('localStorage', []))
                    await page.unroute(url)
            finally:
                await page.close()
            self.mark_seeded(snapshot)
        return self.context

    def mark_seeded(self, snapshot):
        self.seeded = fingerprint(snapshot)
        (self.profile / 'seeded.json').write_text(json.dumps({'fingerprint': self.seeded}), encoding='utf-8')

    async def save_live_state(self):
        if self.context is not None and self.seeded is not None:
            state = await self.context.storage_state()
            target = self.profile / 'live-state.json'
            pending = target.with_suffix('.pending')
            pending.write_text(json.dumps({'source_fingerprint': self.seeded, 'state': state}, ensure_ascii=False), encoding='utf-8')
            pending.replace(target)

    async def close(self):
        async with self._context_lock:
            try:
                if self.context is not None:
                    await self.save_live_state()
            finally:
                try:
                    if self.context is not None:
                        await self.context.close()
                finally:
                    driver, self.playwright = self.playwright, None
                    self.context = None
                    self.seeded = None
                    if driver is not None:
                        await driver.stop()


@asynccontextmanager
async def playwright_scope(runtime=None):
    if runtime is not None:
        # The worker owns lifetime. A scheduled attempt must never stop its driver.
        yield runtime.playwright
    else:
        async with async_playwright() as playwright:
            yield playwright


def ensure_worker(account):
    directory = profile_for(account)
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = directory / 'worker.json'

    def ready():
        try:
            info = json.loads(descriptor.read_text(encoding='utf-8'))
            port = int(info['port'])
            if not 1 <= port <= 65535:
                return None
            with httpx.Client(trust_env=False, timeout=1) as client:
                response = client.get(f'http://127.0.0.1:{port}/health', headers={'Authorization': 'Bearer ' + info['token']})
                if response.status_code == 200 and response.json().get('account') == account:
                    return info
        except (OSError, ValueError, KeyError, httpx.HTTPError):
            pass
        return None

    with (directory / 'startup.lock').open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0'); lock.flush()
        with _FileLock(lock):
            info = ready()
            if info:
                return info
            env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                       PLAYWRIGHT_BROWSERS_PATH=str(ROOT / '.browsers'))
            with (directory / 'worker.log').open('ab') as log:
                process = subprocess.Popen([sys.executable, '-u', '-m', 'src.services.firefox_worker', '--account', account],
                    cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0)
            for _ in range(60):
                info = ready()
                if info:
                    return info
                if process.poll() is not None:
                    raise RuntimeError('Firefox worker exited; inspect its local worker.log')
                time.sleep(.25)
            raise RuntimeError('Firefox worker startup timed out')


@asynccontextmanager
async def worker_client(account):
    info = await asyncio.to_thread(ensure_worker, account)
    async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{info["port"]}',
            headers={'Authorization': 'Bearer ' + info['token']}, trust_env=False, timeout=90) as client:
        yield client


async def remote_scrape(account, task_config, debug_limit):
    async with worker_client(account) as client:
        response = await client.post('/run', json={'task': task_config, 'debug_limit': debug_limit})
        response.raise_for_status()
        job = response.json()['job']
        cursor = 0
        try:
            while True:
                response = await client.get('/jobs/' + job, params={'after': cursor})
                response.raise_for_status()
                status = response.json()
                for sequence, line in status['logs']:
                    print(line, end='', flush=True)
                    cursor = sequence
                if status['done']:
                    if status.get('error'):
                        raise RuntimeError(status['error'])
                    return status['result']
                await asyncio.sleep(.5)
        finally:
            # Also cancel on Ctrl+C or client/network failure. A lease handles killed clients.
            try:
                await asyncio.shield(client.post('/jobs/' + job + '/cancel', timeout=5))
            except (httpx.HTTPError, asyncio.CancelledError):
                pass
