import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from src.services import browser_diagnostics as diagnostics
from src.services.account_failover import retry_collection


@pytest.mark.parametrize('message,category', [
    ('BrowserType.launch_persistent_context: Timeout 45000ms', 'browser_startup'),
    ('Failed to launch the browser process. exitCode=0', 'browser_startup'),
    ('baxia-dialog 验证失败', 'platform_verification'),
    ('connect_over_cdp ECONNREFUSED', 'browser_connection'),
    ('最新发布排序失败', 'filter'),
    ('Timeout 30000ms waiting for response', 'timeout'),
    ('something unexpected', 'unknown'),
])
def test_classifies_without_claiming_every_error_is_browser_startup(message, category):
    assert diagnostics.classify(RuntimeError(message))['category'] == category


@pytest.mark.parametrize('account,browser', [('private1','chrome'), ('private_2','edge'), ('private_3','firefox')])
def test_report_is_scoped_and_does_not_copy_secrets(tmp_path, monkeypatch, account, browser):
    (tmp_path/'state').mkdir()
    (tmp_path/'data').mkdir()
    state_file = tmp_path/'state'/f'{account}.json'
    state_file.write_text(json.dumps({'cookies':[{'name':'cookie2','value':'COOKIE_SECRET'}]}))
    (tmp_path/'data/account-browsers.json').write_text(json.dumps({account:browser}))
    original = state_file.read_bytes()
    # There is no local endpoint descriptor; no network should be attempted.
    monkeypatch.setattr(httpx.Client, 'get', lambda *a, **k: pytest.fail('Unexpected HTTP request'))
    report = diagnostics.create_report(state_file, [RuntimeError('baxia cookie2=COOKIE_SECRET token=TOKEN_SECRET')],
                                       root=tmp_path, trigger='test')
    content = report.read_text(encoding='utf-8') + report.with_suffix('.json').read_text(encoding='utf-8')
    assert 'COOKIE_SECRET' not in content and 'TOKEN_SECRET' not in content
    assert state_file.read_bytes() == original
    payload = json.loads(report.with_suffix('.json').read_text(encoding='utf-8'))
    assert payload['account'] == account and payload['local_snapshot']['browser'] == browser
    assert payload['local_snapshot']['session_cookie_present']
    assert payload['local_snapshot']['endpoint'] == 'missing'
    assert not (tmp_path/'data/account-failover.sqlite3').exists()


def test_refuses_nonlocal_account(tmp_path):
    with pytest.raises(ValueError):
        diagnostics.create_report(tmp_path/'other/private1.json', root=tmp_path)


def test_actual_handoff_writes_one_report_and_preserves_original_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, 'ROOT', tmp_path)
    (tmp_path/'state').mkdir()
    (tmp_path/'state/private1.json').write_text('{"cookies":[]}')
    operation = AsyncMock(side_effect=[RuntimeError('Failed to launch'), TimeoutError('last failure')])
    logs = []
    async def run():
        with pytest.raises(TimeoutError, match='last failure'):
            await retry_collection(operation, sleep=AsyncMock(), diagnostic_account='state/private1.json',
                                   diagnostic_task='test task', logger=logs.append)
    asyncio.run(run())
    reports = list((tmp_path/'data/browser-diagnostics/private1').glob('*.json'))
    assert len(reports) == 1 and reports[0].with_suffix('.md').is_file()
    payload = json.loads(reports[0].read_text(encoding='utf-8'))
    assert payload['trigger'] == 'two_consecutive_failures' and payload['failure_count'] == 2
    assert payload['task'] == 'test task'
    assert any('[浏览器诊断]' in line for line in logs)


def test_second_failure_hands_off_once_even_if_retry_budget_is_larger(monkeypatch):
    diagnose = AsyncMock(return_value=Path('report.md'))
    monkeypatch.setattr(diagnostics, 'diagnose_failure', diagnose)
    operation = AsyncMock(side_effect=[TimeoutError('one'), RuntimeError('two'), RuntimeError('three')])
    async def run():
        with pytest.raises(RuntimeError, match='three'):
            await retry_collection(operation, attempts=3, sleep=AsyncMock(),
                                   diagnostic_account='state/private1.json', diagnostic_task='task')
    asyncio.run(run())
    assert operation.await_count == 3
    diagnose.assert_awaited_once()
    args = diagnose.call_args
    assert args.args[0] == 'state/private1.json'
    assert len(args.args[1]) == 2
    assert args.kwargs['task'] == 'task'


@pytest.mark.parametrize('second', [30, asyncio.CancelledError()])
def test_success_or_cancellation_does_not_trigger_diagnosis(monkeypatch, second):
    diagnose = AsyncMock()
    monkeypatch.setattr(diagnostics, 'diagnose_failure', diagnose)
    operation = AsyncMock(side_effect=[TimeoutError(), second])
    async def run():
        if isinstance(second, BaseException):
            with pytest.raises(asyncio.CancelledError):
                await retry_collection(operation, sleep=AsyncMock(), diagnostic_account='state/private1.json')
        else:
            assert await retry_collection(operation, sleep=AsyncMock(), diagnostic_account='state/private1.json') == 30
    asyncio.run(run())
    diagnose.assert_not_awaited()


def test_diagnosis_failure_cannot_mask_collection_failure(monkeypatch):
    monkeypatch.setattr(diagnostics, 'diagnose_failure', AsyncMock(side_effect=OSError('disk full')))
    operation = AsyncMock(side_effect=[TimeoutError(), RuntimeError('original failure')])
    async def run():
        with pytest.raises(RuntimeError, match='original failure'):
            await retry_collection(operation, sleep=AsyncMock(), diagnostic_account='state/private_3.json')
    asyncio.run(run())
    assert operation.await_count == 2


def test_firefox_health_only_reads_failed_nodes_loopback_endpoint(tmp_path, monkeypatch):
    (tmp_path/'state').mkdir()
    folder = tmp_path/'data/firefox-private_3'
    folder.mkdir(parents=True)
    (tmp_path/'state/private_3.json').write_text('{"cookies":[]}')
    (tmp_path/'data/account-browsers.json').write_text('{"private_3":"firefox"}')
    (folder/'worker.json').write_text('{"port":12345,"token":"WORKER_SECRET"}')
    calls = []
    def get(client, url, **kwargs):
        calls.append(url)
        assert kwargs['headers']['Authorization'] == 'Bearer WORKER_SECRET'
        return httpx.Response(200, json={'account':'private_3','browser_open':True})
    monkeypatch.setattr(httpx.Client, 'get', get)
    report = diagnostics.create_report('state/private_3.json', root=tmp_path)
    assert calls == ['http://127.0.0.1:12345/health']
    content = report.with_suffix('.json').read_text(encoding='utf-8')
    assert 'WORKER_SECRET' not in content
    assert json.loads(content)['local_snapshot']['endpoint'] == 'reachable'
