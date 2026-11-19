import asyncio
from pathlib import Path
import pytest
from src.services.account_failover import AccountFailover, handle_verification_failure
from src.services.shared_chrome import profile_for


def setup_pool(tmp_path):
    files = [tmp_path / "first.json", tmp_path / "second.json"]
    for file in files:
        file.write_text(file.name)
    return AccountFailover(tmp_path / "pool.sqlite3"), files


def test_failure_switch_survives_process_restart_and_never_reuses_blocked(tmp_path):
    pool, files = setup_pool(tmp_path)
    assert pool.select('task', files, files[0]) == str(files[0])
    assert pool.block_and_select('task', files[0], files) == str(files[1])
    restarted = AccountFailover(pool.path)
    assert restarted.select('task', files, files[0]) == str(files[1])
    assert restarted.block_and_select('task', files[1], files) is None
    assert restarted.select('another-task', files) is None


def test_cooldown_blocks_even_new_login_then_expires(tmp_path):
    pool, files = setup_pool(tmp_path)
    now = [1000.0]
    pool.clock = lambda: now[0]
    pool.block_and_select('task', files[0], files)
    pool.block_and_select('task', files[1], files)
    files[0].touch()
    assert pool.select('task', files) is None
    files[0].write_text('new verified state')
    assert pool.select('task', files) is None
    now[0] += 6 * 60 * 60
    assert pool.select('new-task', files, files[0]) == str(files[0])


def test_missing_accounts_are_not_selected(tmp_path):
    pool, files = setup_pool(tmp_path)
    files[0].unlink()
    assert pool.select('task', files, files[0]) == str(files[1])


def test_bark_message_names_target_and_exhaustion(tmp_path):
    pool, files = setup_pool(tmp_path)
    sent = []
    async def notifier(item, reason):
        sent.append((item, reason))
    assert asyncio.run(handle_verification_failure(pool, 'task', files[0], files, notifier)) == str(files[1])
    assert 'first → second' in sent[0][0]['商品标题']
    assert '尚未确认' in sent[0][1]
    assert '限制状态' in sent[0][1] and '6 小时' in sent[0][1]
    assert asyncio.run(handle_verification_failure(pool, 'task', files[1], files, notifier)) is None
    assert '无可用账号' in sent[1][0]['商品标题']


def test_notification_failure_does_not_undo_switch(tmp_path):
    pool, files = setup_pool(tmp_path)
    async def broken(*args):
        raise RuntimeError('unavailable')
    asyncio.run(handle_verification_failure(pool, 'task', files[0], files, broken))
    assert AccountFailover(pool.path).select('task', files) == str(files[1])


def test_profiles_are_account_isolated():
    assert profile_for('private1') != profile_for('private_2')
    with pytest.raises(ValueError):
        profile_for('../other')


def test_managed_failures_replace_legacy_task_pause(monkeypatch):
    from src.services.account_failover import replaces_task_pause
    monkeypatch.setenv('LOCAL_ACCOUNT_FAILOVER', 'true')
    assert replaces_task_pause('初始搜索: FAIL_SYS_USER_VALIDATE')
    assert replaces_task_pause('baxia-dialog')
    assert replaces_task_pause('TimeoutError')
    assert replaces_task_pause('最新发布排序失败')
    monkeypatch.setenv('LOCAL_ACCOUNT_FAILOVER', 'false')
    assert not replaces_task_pause('baxia-dialog')


def test_retry_exhaustion_switches_after_second_failure(tmp_path):
    from src.services.account_failover import retry_verification
    pool, files = setup_pool(tmp_path)
    events = []
    class Verification(Exception): pass
    async def operation():
        assert pool.select('task', files, files[0]) == str(files[0])
        events.append('attempt')
        raise Verification()
    async def sleep(delay): events.append('wait')
    async def notify(item, reason): events.append('notification')
    async def run():
        try:
            await retry_verification(operation, (Verification,), sleep=sleep)
        except Verification:
            await handle_verification_failure(pool, 'task', files[0], files, notify,
                                              failure_summary='本轮连续 2 次验证失败')
    asyncio.run(run())
    assert events == ['attempt', 'wait', 'attempt', 'notification']
    assert pool.select('task', files) == str(files[1])


@pytest.mark.parametrize('success_at', [1, 2])
def test_retry_stops_on_success(success_at):
    from src.services.account_failover import retry_verification
    calls = []
    class Verification(Exception): pass
    async def operation():
        calls.append(1)
        if len(calls) < success_at: raise Verification()
        return 42
    async def sleep(delay): pass
    assert asyncio.run(retry_verification(operation, (Verification,), sleep=sleep)) == 42
    assert len(calls) == success_at


def test_non_verification_errors_and_cancellation_do_not_retry():
    from src.services.account_failover import retry_verification
    for error in [ValueError(), asyncio.CancelledError()]:
        calls = []
        async def operation():
            calls.append(1)
            raise error
        with pytest.raises(type(error)):
            asyncio.run(retry_verification(operation, (RuntimeError,)))
        assert len(calls) == 1


def test_account_browser_mapping_and_pending_login(tmp_path, monkeypatch):
    import json, hashlib
    from src.services import shared_chrome
    monkeypatch.setattr(shared_chrome, 'ROOT', tmp_path)
    (tmp_path/'data').mkdir()
    (tmp_path/'data/account-browsers.json').write_text(json.dumps({'private1':'chrome','private_2':'edge','private_3':'pending'}))
    assert shared_chrome.browser_for('private1') == 'chrome'
    assert shared_chrome.browser_for('private_2') == 'edge'
    assert not shared_chrome.account_browser_ready(tmp_path/'private_3.json')
    state = tmp_path/'private_2.json'
    state.write_text('old snapshot')
    (tmp_path/'data/account-browser-pending.json').write_text(json.dumps({'private_2':hashlib.sha256(state.read_bytes()).hexdigest()}))
    assert not shared_chrome.account_browser_ready(state)
    state.write_text('new Edge export')
    assert shared_chrome.account_browser_ready(state)


@pytest.mark.parametrize("errors", [
    [TimeoutError("search response"), TimeoutError("search response")],
    [TimeoutError("search response"), RuntimeError("最新发布排序失败")],
    [RuntimeError("验证失败"), TimeoutError("search response")],
])
def test_all_collection_errors_share_two_attempts_then_rotate_once(tmp_path, errors):
    from src.services.account_failover import retry_collection
    pool, files = setup_pool(tmp_path)
    pool.clock = lambda: 1000
    pool.select("task",files,files[0])
    calls, logs, notifications = [], [], []
    async def operation():
        error=errors[len(calls)]
        calls.append(1)
        raise error
    async def no_sleep(_): pass
    async def notify(item,reason):
        notifications.append((item,reason))
    async def run():
        try:
            await retry_collection(operation,attempts=2,sleep=no_sleep,logger=logs.append)
        except Exception:
            await handle_verification_failure(pool,"task",files[0],files,notify,restricted=False)
    asyncio.run(run())
    assert len(calls)==2
    assert "1/2" in logs[0] and "2/2" in logs[1]
    assert len(notifications)==1
    assert "[账号异常/切换]" in notifications[0][0]["商品标题"]
    assert "不代表闲鱼已封禁" in notifications[0][1]
    assert pool.cooldown_until(files[0])==22600
    assert pool.select("task",files)==str(files[1])


def test_collection_retry_success_and_cancellation_do_not_rotate():
    from src.services.account_failover import retry_collection
    async def no_sleep(_): pass
    async def scenario():
        calls=[]
        async def operation():
            calls.append(1)
            if len(calls)==1: raise TimeoutError()
            return 30
        assert await retry_collection(operation,sleep=no_sleep)==30
        assert len(calls)==2
        calls.clear()
        async def cancelled():
            calls.append(1)
            raise asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await retry_collection(cancelled,sleep=no_sleep)
        assert len(calls)==1
    asyncio.run(scenario())


def test_unknown_browser_is_rejected(tmp_path, monkeypatch):
    from src.services import shared_chrome
    monkeypatch.setattr(shared_chrome, 'ROOT', tmp_path)
    (tmp_path/'data').mkdir()
    (tmp_path/'data/account-browsers.json').write_text('{"private_3":"unknown"}')
    with pytest.raises(ValueError):
        shared_chrome.browser_for('private_3')


def test_success_confirmation_only_once_after_matching_switch(tmp_path):
    from src.services.account_failover import handle_account_success
    pool, files = setup_pool(tmp_path)
    sent = []
    async def notifier(item, reason):
        sent.append((item, reason))
        return {'bark': {'success': True}}
    async def run():
        assert not await handle_account_success(pool, 'task', files[0], notifier)
        pool.block_and_select('task', files[0], files)
        assert not await handle_account_success(pool, 'task', files[0], notifier)
        restarted = AccountFailover(pool.path)
        assert await handle_account_success(restarted, 'task', files[1], notifier, browser='firefox')
        assert not await handle_account_success(restarted, 'task', files[1], notifier)
    asyncio.run(run())
    assert len(sent) == 1
    assert 'second' in sent[0][0]['商品标题'] and 'firefox' in sent[0][0]['商品标题']


def test_failed_bark_keeps_confirmation_and_exhaustion_clears_it(tmp_path):
    from src.services.account_failover import handle_account_success
    pool, files = setup_pool(tmp_path)
    pool.block_and_select('task', files[0], files)
    async def failure(*args):
        return {'bark': {'success': False}, 'other': {'success': True}}
    assert not asyncio.run(handle_account_success(pool, 'task', files[1], failure))
    assert pool.pending_confirmation('task', files[1])
    pool.block_and_select('task', files[1], files)
    assert pool.pending_confirmation('task', files[1]) is None


def test_old_ack_cannot_clear_a_new_switch_confirmation(tmp_path):
    pool, files = setup_pool(tmp_path)
    pool.block_and_select('task', files[0], files)
    old = pool.pending_confirmation('task', files[1])
    pool.block_and_select('task', files[1], files)
    files[1].write_text('new verified session')
    later = pool.cooldown_until(files[1]) + 1
    pool.clock = lambda: later
    pool.block_and_select('task', files[0], files)
    newer = pool.pending_confirmation('task', files[1])
    assert newer and newer != old
    pool.acknowledge_confirmation('task', old)
    assert pool.pending_confirmation('task', files[1]) == newer


def test_cooldown_survives_restart_and_restores_candidate_at_deadline(tmp_path):
    pool, files = setup_pool(tmp_path)
    now = [1000.0]
    pool.clock = lambda: now[0]
    until = pool.freeze(files[0])
    assert until == 22600
    restarted = AccountFailover(pool.path, clock=lambda: now[0])
    assert restarted.select('task', [files[0]]) is None
    now[0] = until - 1
    assert restarted.select('task', [files[0]]) is None
    now[0] = until
    assert restarted.select('task', [files[0]]) == str(files[0])


def test_old_block_table_migrates_without_freezing_updated_accounts(tmp_path):
    import sqlite3
    import hashlib
    old = tmp_path / 'old.json'
    old.write_text('unchanged')
    updated = tmp_path / 'new.json'
    updated.write_text('new credentials')
    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE blocked (account TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)')
        db.executemany('INSERT INTO blocked VALUES (?,?)', [(str(old), hashlib.sha256(old.read_bytes()).hexdigest()), (str(updated), 'old-fingerprint')])
    pool = AccountFailover(path, clock=lambda: 1000)
    assert pool.cooldown_until(old) == 22600
    assert pool.cooldown_until(updated) is None
    assert pool.select('task', [old, updated]) == str(updated)


def test_switch_after_cooldown_gets_success_confirmation(tmp_path):
    pool, files = setup_pool(tmp_path)
    now = [1000.0]
    pool.clock = lambda: now[0]
    pool.select('task', files, files[0])
    pool.block_and_select('task', files[0], files)
    now[0] += 10
    assert pool.block_and_select('task', files[1], files) is None
    now[0] = 22600
    assert pool.select('task', files) == str(files[0])
    assert pool.pending_confirmation('task', files[0])
