import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src.services import firefox_runtime, shared_chrome
from src.services.account_failover import AccountFailover, handle_verification_failure
from src.services.firefox_worker import create_app


def test_three_browser_selection_and_not_cdp(tmp_path, monkeypatch):
    monkeypatch.setattr(shared_chrome, 'ROOT', tmp_path)
    (tmp_path / 'data').mkdir()
    mapping = {'private1': 'chrome', 'private_2': 'edge', 'private_3': 'firefox'}
    (tmp_path / 'data/account-browsers.json').write_text(json.dumps(mapping))
    assert [shared_chrome.browser_for(a) for a in mapping] == list(mapping.values())
    assert shared_chrome.account_browser_ready(tmp_path / 'private_3.json')
    with pytest.raises(RuntimeError, match='CDP'):
        shared_chrome.ensure_shared_chrome('private_3')


def test_three_account_failover_bark_and_refresh(tmp_path):
    async def run():
        paths = [tmp_path / (n + '.json') for n in ('private1', 'private_2', 'private_3')]
        for p in paths:
            p.write_text(p.stem)
        pool = AccountFailover(tmp_path / 'pool.sqlite3')
        sent = []
        async def notify(item, reason):
            sent.append(item['商品标题'])
        assert pool.select('task', paths, paths[0]) == str(paths[0])
        assert await handle_verification_failure(pool, 'task', paths[0], paths, notify) == str(paths[1])
        assert await handle_verification_failure(pool, 'task', paths[1], paths, notify) == str(paths[2])
        assert pool.select('task', paths) == str(paths[2])
        assert await handle_verification_failure(pool, 'task', paths[2], paths, notify) is None
        assert 'private_2 → private_3' in sent[1]
        paths[0].write_text('updated login')
        assert pool.select('task', paths) is None
        later = max(pool.cooldown_until(p) for p in paths) + 1
        pool.clock = lambda: later
        assert pool.select('new-task', paths, paths[0]) == str(paths[0])
    asyncio.run(run())


def test_firefox_profile_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(firefox_runtime, 'ROOT', tmp_path)
    assert firefox_runtime.profile_for('private_3') == tmp_path / 'data/firefox-private_3'
    for bad in ('../private1', '', 'C:\\profile', 'a/b'):
        with pytest.raises(ValueError):
            firefox_runtime.profile_for(bad)


def test_launch_failure_discards_driver_without_extra_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(firefox_runtime, 'ROOT', tmp_path)
    async def run():
        broken = SimpleNamespace(stop=AsyncMock(),firefox=SimpleNamespace(
            launch_persistent_context=AsyncMock(side_effect=RuntimeError('browser exited'))))
        context = SimpleNamespace(clear_cookies=AsyncMock(),add_cookies=AsyncMock(),
            new_page=AsyncMock(return_value=SimpleNamespace(close=AsyncMock())),on=lambda *args:None)
        fresh = SimpleNamespace(stop=AsyncMock(),firefox=SimpleNamespace(
            launch_persistent_context=AsyncMock(return_value=context)))
        factory = SimpleNamespace(start=AsyncMock(return_value=fresh))
        monkeypatch.setattr(firefox_runtime,'async_playwright',lambda:factory)
        runtime=firefox_runtime.FirefoxRuntime('private_3')
        runtime.playwright=broken
        with pytest.raises(RuntimeError,match='browser exited'):
            await runtime.get_context({'cookies':[],'origins':[]})
        broken.stop.assert_awaited_once()
        broken.firefox.launch_persistent_context.assert_awaited_once()
        assert runtime.playwright is None and runtime.context is None
        factory.start.assert_not_called()
        assert await runtime.get_context({'cookies':[],'origins':[]}) is context
        factory.start.assert_awaited_once()
        fresh.firefox.launch_persistent_context.assert_awaited_once()
    asyncio.run(run())


def test_overlapping_context_requests_launch_only_once(tmp_path, monkeypatch):
    monkeypatch.setattr(firefox_runtime,'ROOT',tmp_path)
    async def run():
        context=SimpleNamespace(clear_cookies=AsyncMock(),add_cookies=AsyncMock(),
            new_page=AsyncMock(return_value=SimpleNamespace(close=AsyncMock())),on=lambda *args:None)
        async def launch(*args,**kwargs):
            await asyncio.sleep(.01)
            return context
        launcher=AsyncMock(side_effect=launch)
        runtime=firefox_runtime.FirefoxRuntime('private_3')
        runtime.playwright=SimpleNamespace(firefox=SimpleNamespace(launch_persistent_context=launcher))
        result=await asyncio.gather(*(runtime.get_context({'cookies':[],'origins':[]}) for _ in range(2)))
        assert result==[context,context]
        launcher.assert_awaited_once()
        context.clear_cookies.assert_awaited_once()
    asyncio.run(run())


def test_close_cleans_driver_even_if_saving_fails(tmp_path,monkeypatch):
    monkeypatch.setattr(firefox_runtime,'ROOT',tmp_path)
    async def run():
        runtime=firefox_runtime.FirefoxRuntime('private_3')
        context=SimpleNamespace(close=AsyncMock())
        driver=SimpleNamespace(stop=AsyncMock())
        runtime.context=context
        runtime.playwright=driver
        runtime.save_live_state=AsyncMock(side_effect=OSError('disk unavailable'))
        with pytest.raises(OSError):
            await runtime.close()
        context.close.assert_awaited_once()
        driver.stop.assert_awaited_once()
        assert runtime.context is None and runtime.playwright is None
    asyncio.run(run())


def test_context_is_reused_and_same_export_does_not_overwrite_live_login(tmp_path, monkeypatch):
    monkeypatch.setattr(firefox_runtime, 'ROOT', tmp_path)
    async def run():
        context = SimpleNamespace(clear_cookies=AsyncMock(), add_cookies=AsyncMock(),
            new_page=AsyncMock(return_value=SimpleNamespace(close=AsyncMock())), on=lambda *args: None)
        launch = AsyncMock(return_value=context)
        runtime = firefox_runtime.FirefoxRuntime('private_3')
        runtime.playwright = SimpleNamespace(firefox=SimpleNamespace(launch_persistent_context=launch))
        state = {'cookies': [], 'origins': []}
        assert await runtime.get_context(state) is context
        assert await runtime.get_context(state) is context
        assert launch.await_count == 1
        assert context.clear_cookies.await_count == 1
        await runtime.get_context({'cookies': [], 'origins': [], 'capture': 'new'})
        assert launch.await_count == 1
        assert context.clear_cookies.await_count == 2
        async with firefox_runtime.playwright_scope(runtime) as p:
            assert p is runtime.playwright
    asyncio.run(run())


def test_worker_auth_cancellation_and_single_job(monkeypatch):
    import src.scraper
    async def run():
        started = asyncio.Event()
        cancelled = asyncio.Event()
        async def scrape(*args, **kwargs):
            assert kwargs['_selected_account'].endswith('private_3.json')
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        monkeypatch.setattr(src.scraper, 'scrape_xianyu', scrape)
        runtime = SimpleNamespace(context=None)
        app = create_app('private_3', 'test-secret', runtime)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://local') as client:
            assert (await client.get('/health')).status_code == 401
            client.headers['Authorization'] = 'Bearer test-secret'
            assert (await client.get('/health')).json()['account'] == 'private_3'
            response = await client.post('/run', json={'task': {'task_name': 'test'}})
            job = response.json()['job']
            await asyncio.wait_for(started.wait(), 2)
            assert (await client.post('/run', json={'task': {}})).status_code == 409
            assert (await client.post('/probe')).status_code == 409
            assert (await client.post('/verify/start')).status_code == 409
            assert (await client.post('/jobs/' + job + '/cancel')).status_code == 200
            await asyncio.wait_for(cancelled.wait(), 2)
            status = (await client.get('/jobs/' + job)).json()
            assert status['done'] and status['error'] == 'Firefox task cancelled'
    asyncio.run(run())


def test_worker_rejects_save_without_successful_search():
    async def run():
        app = create_app('private_3', 'test-secret', SimpleNamespace(context=None))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://local',
                headers={'Authorization': 'Bearer test-secret'}) as client:
            result = (await client.post('/verify/save')).json()
            assert result['ok'] is False
    asyncio.run(run())


def test_restart_restores_live_session_but_new_import_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(firefox_runtime, 'ROOT', tmp_path)
    async def run():
        original = {'cookies': [{'name': 'cookie2', 'value': 'old'}], 'origins': []}
        live = {'cookies': [{'name': 'cookie2', 'value': 'renewed'}], 'origins': []}
        profile = firefox_runtime.profile_for('private_3')
        profile.mkdir(parents=True)
        (profile / 'live-state.json').write_text(json.dumps({'source_fingerprint': firefox_runtime.fingerprint(original), 'state': live}))
        for snapshot, expected in [(original, live), ({'cookies': [{'name': 'cookie2', 'value': 'different-account'}], 'origins': []}, None)]:
            context = SimpleNamespace(clear_cookies=AsyncMock(), add_cookies=AsyncMock(),
                new_page=AsyncMock(return_value=SimpleNamespace(close=AsyncMock())), on=lambda *args: None)
            runtime = firefox_runtime.FirefoxRuntime('private_3')
            runtime.playwright = SimpleNamespace(firefox=SimpleNamespace(launch_persistent_context=AsyncMock(return_value=context)))
            await runtime.get_context(snapshot)
            context.add_cookies.assert_awaited_once_with((expected or snapshot)['cookies'])
    asyncio.run(run())


def test_worker_cancels_when_client_stops_polling(monkeypatch):
    import src.scraper
    from src.services import firefox_worker
    monkeypatch.setattr(firefox_worker, 'LEASE_TIMEOUT_SECONDS', .03)
    monkeypatch.setattr(firefox_worker, 'LEASE_POLL_SECONDS', .01)
    async def run():
        cancelled = asyncio.Event()
        async def scrape(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        monkeypatch.setattr(src.scraper, 'scrape_xianyu', scrape)
        runtime = SimpleNamespace(context=None, save_live_state=AsyncMock())
        app = create_app('private_3', 'test-secret', runtime)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://local',
                headers={'Authorization': 'Bearer test-secret'}) as client:
            job = (await client.post('/run', json={'task': {}})).json()['job']
            await asyncio.wait_for(cancelled.wait(), 1)
            status = (await client.get('/jobs/' + job)).json()
            assert status['done'] and status['error'] == 'Firefox task cancelled'
            assert runtime.context is None
    asyncio.run(run())
